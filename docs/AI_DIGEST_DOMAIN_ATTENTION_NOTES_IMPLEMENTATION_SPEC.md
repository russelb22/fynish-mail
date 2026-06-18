# AI Digest Domain Attention Notes Implementation Spec

## Purpose

Add domain-specific attention notes to the AI digest summary so Fynish can interpret recurring automated mail more intelligently without changing queue classification, Gmail actions, auto-clean behavior, or processed-mail history.

Examples:

- `example.net`: highlight only alarm/security conditions more severe than routine `End-of-Bypass`, `Low Battery`, status, or informational messages.
- `truecoach.co`: highlight likely personal coach/client communication, but do not elevate routine workout assignment, missed-workout, or schedule reminder messages.

This feature should influence only the AI digest briefing: what the summary highlights, downplays, or treats as routine. It must not mutate messages or rules.

## Product Boundary

This is a digest-interpretation feature, not a classifier or auto-processing feature.

In scope:

- per-domain notes that are injected into AI digest summary input
- prompt instructions telling the model how to apply the notes
- structured output that can mention note-driven highlights or caveats
- tests proving notes are included only when relevant domains appear
- an eventual Settings UI for managing notes

Out of scope for the first deployment batch:

- changing Review Queue classification
- changing rule matching
- changing auto-clean behavior
- sending alerts outside the digest email
- hard-blocking or hard-promoting individual messages
- using AI to execute Gmail actions
- storing AI decisions per message

## Design Decision

Start with domain-specific AI digest attention notes, not hard-coded classifier rules.

Reasoning:

- The examples require judgment from sender, subject, and preview text.
- False positives are much safer in digest wording than in Gmail actions.
- The first implementation can be low-risk and reversible.
- The same concept can later graduate into rule suggestions, dedicated alerting, or classifier inputs if it proves reliable.

## Current Integration Points

Relevant files:

- `backend/app/services/ai_digest_summary.py`
- `backend/app/services/digests.py`
- `backend/app/services/notification_settings.py`
- `backend/app/schemas/api.py`
- `backend/app/api/routes.py`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/types.ts`

Current AI digest behavior:

- `build_digest_summary_input()` builds structured JSON from the processed digest payload.
- `_call_openai_digest_summary()` sends that structured JSON to OpenAI Responses API.
- `AI_DIGEST_INSTRUCTIONS` tells the model to use only the structured input.
- The summary is not persisted.
- AI failure degrades to a normal digest.

## Data Model

### V1 Config Object

For Slice 1, use a small backend config object instead of a database table.

Recommended structure:

```python
DOMAIN_ATTENTION_NOTES = [
    {
        "domain": "example.net",
        "label": "Example Security",
        "note": "Highlight only alarm/security conditions more severe than routine End-of-Bypass, Low Battery, status, or informational messages.",
        "routine_examples": ["End-of-Bypass", "Low Battery", "status", "informational"],
        "attention_examples": ["alarm condition", "security alert", "emergency", "intrusion"],
    },
    {
        "domain": "truecoach.co",
        "label": "TrueCoach",
        "note": "Highlight likely personal coach/client communication. Treat routine workout assignment, missed-workout, and schedule reminder messages as routine.",
        "routine_examples": ["workout for Thursday", "missed your workout", "scheduled workout"],
        "attention_examples": ["personal message", "coach replied", "direct note"],
    },
]
```

The exact examples should be phrased carefully. They are guidance for the digest summary, not deterministic matching rules.

### V2 Database Table

For Slice 2, add a persisted user-scoped table.

Recommended table:

`ai_digest_domain_attention_notes`

Columns:

- `id INTEGER PRIMARY KEY`
- `user_id INTEGER NOT NULL`
- `domain TEXT NOT NULL`
- `label TEXT NOT NULL DEFAULT ''`
- `note TEXT NOT NULL`
- `enabled BOOLEAN NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Recommended uniqueness:

- unique `(user_id, lower(domain))`

Postgres equivalent:

- use `SERIAL` or identity primary key
- use `BOOLEAN`
- use a unique index on `user_id, lower(domain)`

## Structured AI Input

Add this field to the AI digest summary input:

```json
{
  "domain_attention_notes": [
    {
      "domain": "example.net",
      "label": "Example Security",
      "note": "Highlight only alarm/security conditions more severe than routine End-of-Bypass, Low Battery, status, or informational messages.",
      "matched_message_count": 3,
      "sample_subjects": [
        "Low Battery alert",
        "End-of-Bypass report"
      ]
    }
  ]
}
```

Rules:

- include notes only for domains present in the digest payload
- match exact sender domain first
- optionally include subdomain matching only if explicitly configured later
- cap matched notes to a small number, such as `10`
- cap sample subjects to `3`
- never include full bodies
- use the same text cleaning/truncation pattern as processed messages

## Prompt Update

Extend `AI_DIGEST_INSTRUCTIONS` with:

```text
If domain_attention_notes are provided, apply them when deciding what deserves attention.
These notes are user preferences for digest interpretation only. Do not claim that Fynish
changed any rule, classifier, or Gmail behavior because of them.

For domains with attention notes:
- highlight messages only when the note says they appear attention-worthy
- treat note-described routine messages as routine
- if evidence is ambiguous, mention uncertainty or omit the item from highlights
- do not invent severity, sender intent, or message content beyond provided fields
```

The prompt should keep the existing privacy and grounding instructions.

## Structured Output

Keep the existing output shape for Slice 1.

Do not add a required new output field immediately. Instead, instruct the model to reflect note-driven interpretation through existing fields:

- `headline`
- `summary`
- `key_takeaways`
- `notable_kept_messages`
- `top_noise_sources`
- `caveats`

Optional later output field:

```json
"attention_note_matches": [
  {
    "domain": "example.net",
    "summary": "Only routine low-battery and bypass messages appeared today.",
    "attention_worthy": false
  }
]
```

Do not add that field until the first batch proves the model behavior is useful.

## Slice Advancement Rule

After implementation begins, do not pause for approval between slices when the current slice meets its "Good Enough To Advance" definition.

Pause only if:

- the implementation would affect queue classification, Gmail actions, rules, or auto-clean
- a database migration is more invasive than the additive table described here
- the OpenAI input would include more sensitive data than existing AI digest input
- tests show the model input cannot be scoped to relevant domains
- the UI needs a product decision not covered in this spec

## Implementation And Deployment Cadence

Work locally for two slices, validate both slices together, then deploy the validated pair to the VM.

Batch 1:

- Slice 1: backend configured attention notes in AI digest input
- Slice 2: persisted per-user notes API and Settings UI
- local validation
- deploy Batch 1 to the VM
- VM validation

This lets implementation proceed past the backend-only version into a user-manageable version before spending time on deployment.

## Slice 1: Backend Configured Attention Notes

### Scope

Add backend support for configured domain attention notes and inject matching notes into AI digest summary input.

Files likely touched:

- `backend/app/services/ai_digest_summary.py`
- `backend/tests/unit/test_ai_digest_summary.py`
- docs

### Requirements

Add configured notes:

- define the two initial notes for `example.net` and `truecoach.co`
- keep the notes close to the AI digest input builder or in a small helper module
- keep notes disabled from any non-AI behavior

Add input builder support:

- identify sender domains present in `payload["processed_messages"]`
- include only matching notes
- include `matched_message_count`
- include up to 3 sample subjects from matched messages
- clean/truncate note fields and subjects
- include `domain_attention_notes` in the structured summary input

Update prompt instructions:

- tell the model how to apply domain notes
- state that notes are digest interpretation preferences only
- avoid implying Gmail/rule/classifier behavior changed

### Good Enough To Advance

Slice 1 is good enough when:

- `build_digest_summary_input()` includes `domain_attention_notes` when matching processed messages contain `example.net` or `truecoach.co`.
- `domain_attention_notes` is empty or omitted when no configured domains appear.
- Matching is exact-domain only.
- Sample subjects are capped.
- Existing processed message truncation remains intact.
- No queue, rule, auto-clean, or Gmail action code changes are needed.
- Unit tests cover:
  - example.net note included
  - truecoach.co note included
  - unrelated domain omitted
  - sample subject cap
  - no snippets/full bodies added beyond existing digest input behavior

### Local Validation

Run:

```bash
.venv/bin/pytest backend/tests/unit/test_ai_digest_summary.py
```

## Slice 2: Per-User Notes API And Settings UI

### Scope

Add persisted per-user attention notes and a small Settings UI so the notes can be managed without code changes.

Files likely touched:

- `backend/app/db/schema.sql`
- `backend/app/db/schema.postgres.sql`
- `backend/app/db/database.py`
- `backend/app/services/ai_digest_attention_notes.py`
- `backend/app/api/routes.py`
- `backend/app/schemas/api.py`
- `backend/tests/unit/test_ai_digest_attention_notes.py`
- `backend/tests/integration/test_ai_digest_attention_notes_api.py`
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/App.css`

### Requirements

Backend:

- add additive table `ai_digest_domain_attention_notes`
- create service functions:
  - `list_ai_digest_attention_notes(user_id)`
  - `create_ai_digest_attention_note(user_id, domain, note, label=None)`
  - `update_ai_digest_attention_note(user_id, note_id, changes)`
  - `delete_ai_digest_attention_note(user_id, note_id)`
- normalize domains to lowercase
- reject blank domains
- reject blank notes
- keep notes user-scoped
- use persisted notes instead of static configured notes when user notes exist
- seed default notes for a user only if no persisted notes exist, or expose them as suggested defaults

API:

- `GET /api/settings/ai-digest-attention-notes`
- `POST /api/settings/ai-digest-attention-notes`
- `PATCH /api/settings/ai-digest-attention-notes/{note_id}`
- `DELETE /api/settings/ai-digest-attention-notes/{note_id}`

Frontend:

- add a Settings section titled `AI digest attention notes`
- show existing notes with domain, label, enabled state, and note text
- allow adding a domain and note
- allow enabling/disabling a note
- allow deleting a note
- do not over-build; simple inline controls are enough

Suggested helper copy:

`Attention notes guide only the AI digest summary. They do not change Gmail actions, queue rules, or auto-cleaning.`

### Good Enough To Advance

Slice 2 is good enough when:

- The new table is additive and works for SQLite and Postgres schemas.
- API routes are user-scoped.
- A user can list, add, edit/enable/disable, and delete notes.
- Persisted enabled notes are used by `build_digest_summary_input()`.
- Disabled notes are not injected.
- If no persisted notes exist, the two defaults are available by service default or seeded safely.
- Frontend Settings can manage notes without page reload.
- Frontend clearly states notes affect only AI digest summaries.
- Tests cover service CRUD, API scoping, disabled notes, and input-builder use of persisted notes.
- Frontend build passes.

### Local Validation

Run:

```bash
.venv/bin/pytest backend/tests/unit/test_ai_digest_summary.py backend/tests/unit/test_ai_digest_attention_notes.py backend/tests/integration/test_ai_digest_attention_notes_api.py
npm run build
```

## Batch 1 Deployment Gate

Deploy Slice 1 and Slice 2 together only after:

- backend tests pass
- frontend build passes
- no OpenAI API call is required for tests
- no queue/rule/Gmail action behavior changes are included
- docs reflect the current behavior

After deployment validate:

- backend service active
- frontend service active
- `GET /api/health` returns `{"status":"ok"}`
- public login endpoint returns `200`
- Settings page loads
- attention notes section renders
- API can list notes for the signed-in user
- manual AI digest preview or send still degrades safely if OpenAI is unavailable

## Slice 3: Optional Output Field For Attention Matches

### Scope

Add structured model output specifically describing attention-note interpretation.

Potential field:

```json
"attention_note_matches": [
  {
    "domain": "example.net",
    "summary": "Only routine Low Battery and End-of-Bypass messages appeared.",
    "attention_worthy": false
  }
]
```

### Good Enough To Advance

- output schema validates
- HTML and plain-text digest render the new field compactly
- tests cover generated and empty states
- the field does not duplicate the full processed-message list

## Slice 4: Quality Feedback And Examples

### Scope

Let the user record whether a note behaved correctly in a digest.

Options:

- simple local documentation/examples first
- later feedback buttons in digest preview
- later sample-message matching preview in Settings

### Good Enough To Advance

- feedback does not send extra data to OpenAI
- feedback does not alter Gmail or rules
- any saved feedback is user-scoped

## Privacy And Safety

This feature uses the same AI digest data boundary:

- send sender, domain, subject, action metadata, processed time, and preview only when AI digest summaries are enabled
- do not send Gmail credentials
- do not send OpenAI keys
- do not send full message bodies beyond existing preview/snippet behavior
- do not store raw prompts
- do not store generated AI summary unless a future spec explicitly adds persistence

## Testing Strategy

Backend tests:

- configured note matching
- persisted note matching
- exact-domain behavior
- disabled notes omitted
- user-scoped note reads/writes
- validation errors for blank domain/note
- no OpenAI calls in normal tests

Frontend/manual tests:

- Settings renders notes
- add note
- edit note
- disable note
- delete note
- build passes
- digest preview still loads

## Documentation Updates During Implementation

Update as behavior lands:

- `docs/AI_DIGEST_SUMMARY_IMPLEMENTATION_PLAN.md`
- `docs/AI_DIGEST_SUMMARY_FEATURE_SPEC.md`
- `docs/FYNISH_FUNCTIONAL_GUIDE.md`

This spec is the controlling implementation guide for domain-specific AI digest attention notes.
