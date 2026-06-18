# AI Digest Summary Implementation Plan

## Purpose

This document turns the AI digest summary feature spec into a concrete implementation plan.

Reference:

- [AI_DIGEST_SUMMARY_FEATURE_SPEC.md](docs/AI_DIGEST_SUMMARY_FEATURE_SPEC.md)
- [PROCESSED_MAIL_DIGEST_SPEC.md](docs/PROCESSED_MAIL_DIGEST_SPEC.md)
- [PROCESSED_MAIL_DIGEST_IMPLEMENTATION_PLAN.md](docs/PROCESSED_MAIL_DIGEST_IMPLEMENTATION_PLAN.md)

## Implementation Summary

Recommended delivery order:

1. add configuration and user setting fields
2. build provider-neutral summarizer service
3. implement OpenAI provider using the Responses API
4. add prompt/input builder with strict data minimization
5. add structured output schema and validation
6. insert AI summary into digest payload and renderers
7. add tests for enabled, disabled, failure, and fallback behavior
8. deploy disabled-by-default
9. enable for one test user

Resolved V1 choices:

- include snippets/body previews in the model input
- generate summaries send-only; do not persist generated summaries in the database
- enable AI summaries for Russel only during the first live trial
- use `AI digest summary` as the Settings label
- use `gpt-5-mini` as the default model
- include AI summaries in manual review digests when the user setting is enabled
- keep model choice as an operator env var

## Current Implementation Status

As of June 1, 2026, the first local implementation pass is complete.

Implemented locally:

- backend env/config settings for AI digest summaries
- additive `notification_settings_by_user.ai_digest_summary_enabled` setting
- Settings API support for `ai_digest_summary_enabled`
- frontend Settings toggle labeled `AI digest summary`
- AI digest summary service with:
  - OpenAI provider path
  - strict structured output schema
  - digest input builder
  - snippet/body preview inclusion
  - input truncation
  - provider failure fallback
- digest payload integration
- HTML digest rendering for `Today's inbox briefing`
- plain-text digest rendering for the AI briefing
- focused tests for settings, input building, provider failure, and digest rendering

Still needed before live use:

- add `FYNISH_OPENAI_API_KEY` to `/etc/fynish/backend.env`
- enable `FYNISH_AI_DIGEST_SUMMARIES_ENABLED=1`
- enable `ai_digest_summary_enabled` for Russel only
- send a manual review digest and inspect the result

Completed VM prep:

- deployed disabled-by-default to the VM
- applied the additive Postgres schema column on the VM
- installed the `openai` Python dependency in the VM backend venv
- verified backend health after deploy
- verified Russel's digest payload still builds with `ai_summary_enabled = false`

As of June 4, 2026, domain-specific AI digest attention notes are implemented locally for the first deployment batch.

Implemented locally:

- additive `ai_digest_domain_attention_notes` table for user-scoped notes
- default notes for `example.net` and `truecoach.co`
- AI summary input field `domain_attention_notes`
- exact sender-domain matching for attention notes
- cap of 10 matched notes and 3 sample subjects per note
- prompt instructions that treat notes as digest interpretation preferences only
- CRUD API under `/api/settings/ai-digest-attention-notes`
- Settings UI card titled `AI digest attention notes`
- focused backend tests for input scoping, service validation, and API user scoping

Important boundary:

- attention notes do not change Review Queue classification
- attention notes do not change rules, auto-cleaning, Gmail labels, or processed-mail history
- generated summaries still are not persisted

## Current Digest Integration Points

Existing code to extend:

- `backend/app/services/digests.py`
- `backend/app/services/mailer.py`
- `GET /api/digests/processed/preview`
- `POST /api/tasks/send-digests`
- `notification_settings_by_user`
- frontend Settings digest controls

The AI summary should be added to the existing daily processed digest payload, not as a separate email.

## Phase 1: Configuration

### Environment variables

Recommended backend env vars:

- `FYNISH_AI_DIGEST_SUMMARIES_ENABLED=0`
- `FYNISH_AI_DIGEST_PROVIDER=openai`
- `FYNISH_OPENAI_API_KEY`
- `FYNISH_OPENAI_DIGEST_MODEL=gpt-5-mini`
- `FYNISH_OPENAI_DIGEST_TIMEOUT_SECONDS=20`
- `FYNISH_OPENAI_DIGEST_MAX_OUTPUT_TOKENS=3000`
- `FYNISH_OPENAI_DIGEST_REASONING_EFFORT=minimal`
- `FYNISH_OPENAI_DIGEST_MAX_INPUT_MESSAGES=50`
- `FYNISH_OPENAI_DIGEST_INCLUDE_SNIPPETS=1`

Notes:

- the global feature flag prevents accidental production use
- per-user settings should still be required
- model choice can be changed without code deployment
- the API key belongs in `/etc/fynish/backend.env` on the VM

### Settings fields

Recommended new field on `notification_settings_by_user`:

- `ai_digest_summary_enabled BOOLEAN DEFAULT 0`

Optional later fields:

- `ai_digest_include_snippets BOOLEAN DEFAULT 1`
- `ai_digest_detail_level TEXT DEFAULT 'brief'`
- `ai_digest_model TEXT NULL`

V1 should keep settings minimal.

## Phase 2: Data Model

### Option A: no persistence for generated summaries

The digest summary is generated during delivery and sent only in the email.

Pros:

- simplest
- stores less email-derived data
- avoids summary history and deletion policy

Cons:

- cannot inspect past summaries from the app
- manual review sends may produce slightly different wording

### Option B: persist generated summaries

Add `digest_ai_summaries`.

Recommended columns:

- `id`
- `user_id`
- `digest_delivery_log_id NULL`
- `window_start`
- `window_end`
- `provider`
- `model`
- `status`
- `summary_json`
- `input_message_count`
- `input_token_estimate`
- `output_token_estimate`
- `error_message`
- `created_at`
- `updated_at`

Recommendation:

- choose Option A for V1
- log metadata only, not raw prompts
- revisit persistence after user testing

## Phase 3: Service Design

### New service files

Recommended files:

- `backend/app/services/ai_digest_summary.py`
- `backend/app/services/llm_providers.py`

If that feels too abstract for V1, start with:

- `backend/app/services/ai_digest_summary.py`

and keep provider methods small enough to split later.

### Public service function

Recommended function:

```python
def build_ai_digest_summary(
    payload: dict,
    *,
    user_id: int,
    enabled_for_user: bool,
) -> dict | None:
    ...
```

Return `None` when:

- global feature flag is off
- user setting is off
- provider config is missing
- payload has no useful activity
- provider call fails

Do not raise provider failures into normal digest delivery.

### Payload shape

Recommended returned object:

```json
{
  "generated": true,
  "provider": "openai",
  "model": "gpt-5-mini",
  "headline": "Most processed mail today was promotional.",
  "summary": "Fynish processed 74 messages today...",
  "key_takeaways": [
    "Finance newsletters were the largest junk cluster."
  ],
  "auto_clean_review": {
    "count": 0,
    "summary": "No messages were auto-cleaned in this digest window.",
    "notable_items": []
  },
  "notable_kept_messages": [
    {
      "subject": "Security alert for digest.sender@example.com",
      "reason": "Account-security message kept."
    }
  ],
  "top_noise_sources": [
    {
      "sender_domain": "tradivore.com",
      "summary": "Promotional finance mail."
    }
  ],
  "caveats": [
    "Summary is based on sender, subject, and snippet only."
  ]
}
```

## Phase 4: OpenAI Provider

### API choice

Use the OpenAI Responses API.

Reasons:

- OpenAI recommends Responses API for new text generation apps
- it supports structured JSON output
- it works cleanly for one-shot summarization

Reference:

- [OpenAI text generation guide](https://platform.openai.com/docs/guides/text?api-mode=responsesPer)
- [OpenAI Responses API reference](https://platform.openai.com/docs/api-reference/responses?lang=curl)

### Structured output

Use Structured Outputs with a JSON schema.

Reasons:

- digest renderer should not parse free-form prose
- tests can validate a stable shape
- missing keys should fail cleanly
- refusals/errors can be handled programmatically

Reference:

- [OpenAI Structured Outputs guide](https://platform.openai.com/docs/guides/structured-outputs?api-mode=responses)

### SDK

Recommended dependency:

- `openai`

Add to:

- `backend/requirements.txt`

Optional:

- pin a compatible major version once tested

### Provider call behavior

The OpenAI provider should:

- construct a single request per digest
- use a strict schema
- set a timeout
- cap output tokens
- avoid storing the raw prompt
- return parsed JSON
- log provider, model, status, latency, and error class

It should not:

- use web search
- call tools
- include attachments
- include OAuth tokens
- send full bodies by default

## Phase 5: Prompt and Input Builder

### Input builder

Recommended helper:

```python
def build_digest_summary_input(payload: dict, *, include_snippets: bool) -> dict:
    ...
```

The input should be structured JSON, not a long prose prompt.

Include:

- digest window
- processed_count
- counts_by_action
- counts_by_source
- top_sender_domains
- processed_messages capped at configured limit

Each processed message should include:

- account_email
- sender
- sender_domain
- subject
- snippet/body_preview if available and enabled
- selected_action
- selected_action_label
- action_source
- action_source_label
- processed_at

### Truncation

Recommended caps:

- max processed messages: `50`
- max sender length: `200`
- max subject length: `240`
- max snippet length: `500`
- max top domains: `10`
- max sample subjects per domain: `3`

### Prompt instructions

System/developer instructions should include:

- summarize only from provided input
- do not infer beyond sender, subject, snippet, action, and domain
- be concise
- call out auto-cleaned messages separately
- avoid certainty about safety
- do not recommend rule changes in V1
- do not include raw email addresses unless needed for clarity
- return only the requested JSON schema

## Phase 6: Digest Payload Integration

### Backend payload

Add to `build_processed_digest_payload`:

- `ai_summary_enabled`
- `ai_summary`
- `ai_summary_error` only for preview/debug, not regular email body

Recommended behavior:

- build normal payload first
- call `build_ai_digest_summary`
- attach result if available
- continue without it on failure

### HTML renderer

Add an `AI Briefing` section above `Processed Mail`.

Render:

- headline
- summary paragraph
- key takeaways
- auto-clean review
- notable kept messages
- top noise sources
- caveat line

Keep it visually distinct but quiet.

### Plain text renderer

Include a compact section:

```text
Today's inbox briefing:
Most processed mail today was promotional.

Key takeaways:
- Finance newsletters were the largest junk cluster.
- No messages were auto-cleaned in this digest window.
```

## Phase 7: API and Settings UI

### Backend settings

Extend notification settings API:

- include `ai_digest_summary_enabled`
- allow update from Settings UI

### Frontend Settings

Add a digest setting:

- label: `AI digest summary`
- control: toggle
- helper text: `Adds a short AI-generated briefing to the daily digest.`

Possible privacy copy:

- `When enabled, Fynish may send digest message metadata and snippets to OpenAI to generate the summary.`

Keep this copy concise and visible near the toggle.

### Preview

The existing digest preview endpoint should include the AI summary when:

- global feature flag is enabled
- user setting is enabled
- provider config exists

If this makes previews slow, add:

- `?include_ai_summary=1`

Recommendation:

- do not generate AI summaries automatically on every Settings page load
- generate only for an explicit preview/test action

## Phase 8: Testing

### Unit tests

Add tests for:

- input builder truncates long fields
- input builder excludes full body fields
- disabled global feature returns `None`
- disabled user setting returns `None`
- provider missing config returns `None`
- provider failure returns `None` and normal digest still renders
- parsed AI summary renders in HTML
- parsed AI summary renders in plain text
- auto-cleaned rows are represented in the summary input

### Provider tests

Use a fake provider by default.

Do not call OpenAI in normal tests.

Optional manual smoke script:

- `scripts/send_test_ai_digest_summary.py`

This script should require an explicit confirmation flag, such as:

- `--confirm-openai-call`

### Integration tests

Add tests for:

- preview endpoint includes AI summary when mocked provider returns one
- send digest does not fail if mocked provider raises
- settings API persists `ai_digest_summary_enabled`

## Phase 9: Deployment Plan

### Local

1. add env vars to local example docs
2. run backend tests
3. run frontend build
4. manually generate digest preview with mocked provider
5. manually test one real OpenAI call only after API key is configured

### VM

1. deploy code with `FYNISH_AI_DIGEST_SUMMARIES_ENABLED=0`
2. add `FYNISH_OPENAI_API_KEY` to `/etc/fynish/backend.env`
3. set model env var
4. restart backend
5. verify normal scheduled digest still works without AI
6. enable global feature flag
7. enable user setting for Russel only
8. send one manual review digest
9. inspect result
10. leave Kim disabled until Russel approves the summary quality

## Phase 10: Failure Behavior

The daily digest should still send if:

- OpenAI API is down
- API key is missing
- model returns invalid schema
- request times out
- rate limit occurs

Fallback:

- omit the AI section
- log the failure
- keep the normal digest intact

The email should not include an alarming "AI failed" message. For preview/debug screens, a quiet warning is acceptable.

## Phase 11: Cost Controls

Controls:

- per-user opt-in
- global feature flag
- one model call per digest
- cap processed rows
- truncate snippets
- no retries on scheduled sends beyond one safe retry
- log provider/model and estimated input size

Initial expected cost should be low at current user volume, but the implementation should still make costs observable.

## Phase 12: Future Enhancements

Later features:

- user-selectable detail level
- weekly AI summary
- "what changed from yesterday" trend summary
- AI-generated suggested rules, reviewed before creation
- local LLM provider
- per-account AI summary opt-out
- in-app digest history
- summary quality feedback buttons

## Initial Implementation Checklist

- [x] Decide whether V1 includes snippets/body previews.
- [x] Decide whether summaries are stored or send-only.
- [x] Add env vars and config parsing.
- [x] Add `ai_digest_summary_enabled` setting.
- [x] Add summarizer service with fake provider test hook.
- [x] Add OpenAI provider.
- [x] Add structured output schema.
- [x] Add digest input builder.
- [x] Integrate summary into digest payload.
- [x] Render summary in HTML and plain text.
- [x] Add Settings toggle.
- [x] Add backend tests.
- [x] Add frontend type/build updates.
- [x] Deploy disabled-by-default.
- [ ] Configure API key on VM.
- [ ] Enable for Russel first.
- [ ] Send manual review digest.

## Open Questions Before Coding

Resolved:

1. V1 includes snippets/body previews.
2. The AI summary is opt-in per Fynish user.
3. Generated summaries are not stored in the database for V1.
4. Kim should not receive AI summaries until Russel reviews examples.
5. The Settings label is `AI digest summary`.

Remaining:

1. None for V1.

Final V1 decisions:

- model: `gpt-5-mini`
- manual review digests include AI summaries when the user setting is enabled
- model choice remains an operator env var
