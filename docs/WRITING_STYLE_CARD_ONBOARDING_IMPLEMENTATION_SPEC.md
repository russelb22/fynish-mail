# Writing Style Card Onboarding Implementation Spec

Status: proposed next feature slice.

## Purpose

Build a hosted Fynish flow that lets each signed-in user create a private writing style card from their own Gmail Sent mail.

The style card will be used by Auto-Respond and later agent workflows so generated replies sound more like the user while staying grounded in the current email and user-provided facts.

## Product Decision

Proceed with derived style cards, not long-term storage of raw sent-mail samples.

Fynish should:

- sample a bounded set of Sent messages from a user's connected Gmail account
- extract only enough text to infer writing style
- generate a compact style card
- store the derived style card per user and account
- discard raw sampled message bodies after generation
- let the user view, edit, save, approve, regenerate, or disable the card

## Current Baseline

Local tooling already exists:

- `scripts/export_sent_writing_samples.py`
- `scripts/build_writing_style_profile.py`
- `backend/app/services/writing_sample_export.py`
- `backend/app/services/writing_style_profile.py`
- local output under `backend/data/writing_samples/<account>/`
- Auto-Respond reads `writing_style_card.md` from local account folders when present

Hosted Fynish currently does not have:

- a user-facing `Build my writing style` flow
- per-user style-card storage in Postgres
- a VM-safe Sent-mail sampling service
- a background job status model for long-running sampling
- a UI surface to view, edit, save, approve, or regenerate the card

## Goals

- Generate a useful style card for a new Fynish user from Gmail Sent mail.
- Keep the feature safe for hosted multi-user use.
- Make the user explicitly opt in.
- Avoid storing raw sent-mail corpora in the database.
- Let users inspect and strengthen the style card before Fynish uses it.
- Make Auto-Respond use the approved per-user card automatically.
- Support rollout to one user first, then invited users.

## Non-Goals

Do not implement these in the first slice:

- iMessage sampling
- full writing-style fine-tuning
- storing a vector database of sent messages
- automatic background sampling without user initiation
- cross-user or global style model sharing
- direct reuse of another user's style card

## Data Model

Add a table:

```sql
CREATE TABLE IF NOT EXISTS writing_style_cards (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mail_account_id BIGINT NULL REFERENCES mail_accounts(id) ON DELETE SET NULL,
    account_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    source_provider TEXT NOT NULL DEFAULT 'gmail_sent',
    sample_start_date TEXT NULL,
    sample_end_date TEXT NULL,
    sample_bucket_count INTEGER NOT NULL DEFAULT 0,
    sampled_message_count INTEGER NOT NULL DEFAULT 0,
    sampled_word_count INTEGER NOT NULL DEFAULT 0,
    style_card_markdown TEXT NOT NULL,
    style_card_json JSONB NULL,
    user_edited INTEGER NOT NULL DEFAULT 0,
    edited_at TIMESTAMPTZ NULL,
    generator_model TEXT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMPTZ NULL,
    disabled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Recommended uniqueness rule:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_writing_style_cards_active_account
ON writing_style_cards(user_id, lower(account_email))
WHERE status IN ('draft', 'approved');
```

Status values:

- `draft`
- `approved`
- `disabled`
- `superseded`
- `failed`

Optional job table if generation runs asynchronously:

```sql
CREATE TABLE IF NOT EXISTS writing_style_generation_jobs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mail_account_id BIGINT NOT NULL REFERENCES mail_accounts(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    error_message TEXT NULL,
    progress_message TEXT NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Sampling Policy

Default V1 sampling:

- source: Gmail `in:sent`
- date range: last 24 months, with fallback expansion to 5 years if too sparse
- buckets: month buckets
- target: 2 to 3 messages per month
- cap: 72 total messages
- minimum useful threshold: 12 messages or 2,000 words
- exclude messages under 30 words
- exclude likely forwards, receipts, automated replies, newsletters, attachments-only sends, and calendar/system messages
- strip quoted reply history where possible
- cap per-message text at 2,500 characters
- cap aggregate style input at a configurable token/character budget

The selector should favor messages that are:

- written by the user
- medium or long enough to show style
- addressed to humans
- spread across time
- diverse in recipients and subjects

The selector should not favor:

- highly sensitive obvious categories if detectable
- one-word acknowledgements
- forwarded chains
- raw pasted documents
- huge technical dumps

## Privacy Boundary

Raw sampled sent-message text should be transient.

Allowed to persist:

- account email
- sample counts
- date/bucket metadata
- derived style card markdown
- derived structured style summary
- generation timestamps and status

Not allowed to persist in V1:

- raw sent message body corpus
- complete recipient lists
- complete subject list unless explicitly needed for debugging
- generated prompt packets containing raw samples

If debugging artifacts are needed locally, they must be behind a dev-only flag and never enabled on the VM by default.

## Backend Services

Add `backend/app/services/writing_style_cards.py`.

Responsibilities:

- list current user's style cards
- get active card for user/account
- create generation job
- update draft card markdown
- approve card
- disable card
- supersede old cards on regeneration
- expose only cards owned by the current user

Add `backend/app/services/hosted_writing_style_generation.py`.

Responsibilities:

- validate user owns the selected mail account
- load Gmail credentials from `provider_connections`
- query Gmail Sent mail using readonly/modify credentials
- sample Sent messages according to policy
- clean and trim message text
- call style-card builder
- persist only the derived card and metadata

Prefer reusing these local services where possible:

- `writing_sample_export.py` for text extraction and scoring
- `writing_style_profile.py` for heuristics

However, the hosted service should not write JSONL/markdown sample corpora to `backend/data`.

## LLM Use

V1 can start with the existing deterministic `writing_style_profile.py` approach if that is good enough.

Recommended V1.1 uses OpenAI to convert the sampled style evidence into a concise style card.

Provider behavior:

- gated by `FYNISH_WRITING_STYLE_GENERATION_ENABLED`
- provider from `FYNISH_AI_DIGEST_PROVIDER`
- API key from `FYNISH_OPENAI_API_KEY`
- model from `FYNISH_OPENAI_STYLE_MODEL`, default `gpt-5-mini`
- structured output required

The output should include:

- `style_card_markdown`
- `tone_traits`
- `formatting_habits`
- `typical_openings`
- `typical_closings`
- `do`
- `avoid`
- `confidence`
- `sample_summary`

The prompt must tell the model:

- infer style only
- do not preserve private facts from samples
- do not include names, addresses, phone numbers, URLs, or sensitive specifics
- write guidance that helps draft new emails without quoting source samples

## API

Add endpoints:

```http
GET /api/writing-style/cards
POST /api/writing-style/cards/generate
GET /api/writing-style/cards/{card_id}
PATCH /api/writing-style/cards/{card_id}
POST /api/writing-style/cards/{card_id}/approve
POST /api/writing-style/cards/{card_id}/disable
```

Request for generation:

```json
{
  "mail_account_id": 123,
  "sample_months": 24,
  "max_messages": 72
}
```

Response for generation:

For synchronous V1:

```json
{
  "card": {
    "id": 10,
    "account_email": "user@example.com",
    "status": "draft",
    "sampled_message_count": 42,
    "style_card_markdown": "..."
  }
}
```

For async V1:

```json
{
  "job": {
    "id": 55,
    "status": "queued"
  }
}
```

Synchronous generation is acceptable for the first private VM slice if it completes reliably within a backend timeout. If generation may exceed 30 seconds, implement the job table.

Request for editing a draft card:

```json
{
  "style_card_markdown": "Private writing style guidance..."
}
```

Editing rules:

- only the owner can edit the card
- only `draft` and `approved` cards can be edited
- editing an `approved` card should move it back to `draft` unless the request explicitly saves and approves in one backend operation
- maximum card length should be enforced, recommended 8,000 characters
- empty or extremely short cards should be rejected
- `user_edited` should become true and `edited_at` should be updated

Approving rules:

- approving a card marks it as the active card for that user/account
- any older approved card for the same user/account should become `superseded`
- approval should use the latest saved markdown, whether generated or user-edited

## Frontend UX

Add a Settings section titled `Writing style`.

Initial controls:

- account selector for connected Gmail accounts
- `Build Style Card`
- status row showing generated/approved/disabled state
- editable style-card text area
- `Save Changes`
- `Approve`
- `Regenerate`
- `Disable`

UX copy should be plain:

- `Fynish samples your Sent mail to create a private style card. Raw samples are not stored.`
- `Review and edit the card before approving it. Auto-Respond uses the approved version when drafting replies.`

Do not add a long marketing explanation.

Recommended editing UX:

1. Generated style card appears in a text area.
2. User can edit wording, add preferences, remove traits that feel wrong, or add examples of preferred phrasing.
3. Unsaved edits show a small `Unsaved changes` state.
4. `Save Changes` persists the markdown and keeps the card in `draft`.
5. `Approve` saves current edits if needed, then marks that card active.
6. Auto-Respond should use only approved cards, not unsaved browser text.

The card should not be hidden behind a collapsed advanced panel. The trust moment is seeing what Fynish thinks the user's style is.

## Auto-Respond Integration

Update `auto_response_draft.py` style-card lookup order:

1. approved `writing_style_cards` row for `current_user.id` and the message's receiving account
2. approved `writing_style_cards` row for `current_user.id` by account email
3. local dev fallback file under `backend/data/writing_samples/<account>/writing_style_card.md`
4. built-in generic default style

Auto-Respond responses should include:

- `style_source`: `approved_style_card`, `local_style_card`, or `default_style`
- `style_card_id`: nullable

## Feature Flags

Backend env vars:

- `FYNISH_WRITING_STYLE_GENERATION_ENABLED=0`
- `FYNISH_WRITING_STYLE_ALLOWED_USER_EMAILS=primary.user@example.com`
- `FYNISH_OPENAI_STYLE_MODEL=gpt-5-mini`
- `FYNISH_WRITING_STYLE_MAX_SENT_MESSAGES=72`
- `FYNISH_WRITING_STYLE_SAMPLE_MONTHS=24`
- `FYNISH_WRITING_STYLE_STORE_RAW_SAMPLES=0`

Rollout:

1. deploy disabled
2. enable for Russel only
3. generate Russel's hosted card
4. validate Auto-Respond uses DB card
5. enable for one invited user

## Tests

Backend unit tests:

- sampling policy excludes short/forwarded/quoted-heavy messages
- style-card persistence stores derived card only
- style-card edits update markdown, `user_edited`, and `edited_at`
- editing an approved card returns it to draft or otherwise prevents accidental silent active changes
- approval supersedes older active cards
- disabled card is not used by Auto-Respond
- lookup order prefers approved DB card over local file fallback
- feature flag blocks unauthorized users

Backend integration tests:

- user A cannot list, approve, or disable user B's cards
- generation requires owned mail account
- generation handles sparse Sent mail
- generation handles Gmail credential errors
- editing rejects empty or overlong card text

Frontend build/tests:

- Settings card appears only when feature flag allows it
- generated card text area renders safely
- save/approve/disable/regenerate controls call the correct API
- unsaved edits are visible before save

## Deployment Plan

Slice 1:

- add DB table and service CRUD
- add API list/update/approve/disable
- add Settings UI around manually seeded cards with edit/save/approve flow
- update Auto-Respond to use approved DB card

Slice 2:

- add hosted Gmail Sent sampler
- add synchronous generation for allowlisted users
- add focused tests
- deploy disabled, then enable for Russel

Slice 3:

- add async job table if generation latency demands it
- improve progress/status UI
- enable for invited users

## Acceptance Criteria

- A signed-in allowlisted user can generate a draft style card from their own Sent mail.
- The raw sample corpus is not persisted on the VM.
- The user can view, edit, save, approve, or disable the card.
- Auto-Respond uses the approved card.
- Auto-Respond does not use unsaved or unapproved edits.
- Another user cannot see or use that card.
- Kim does not see this feature until explicitly allowlisted.
