# Fynish Error Handling Strategy

Companion implementation checklist: `docs/ERROR_HANDLING_AUDIT.md`.

## Purpose

This document defines a strategy for identifying and improving error handling across Fynish.

Status: the first hardening pass was completed on 2026-06-04. The implementation checklist and closeout details are in `docs/ERROR_HANDLING_AUDIT.md`.

The goal is not to hide errors. The goal is to make failures:

- understandable to users
- actionable when user action can fix them
- visible in logs when operator action is needed
- safe by default when external systems fail
- consistent across backend routes, background jobs, and frontend interactions

Recent examples:

- expired Gmail credentials caused live Gmail actions to fail with a backend `500`
- users saw clicks that felt non-responsive instead of a clear reconnect message
- scheduled sync correctly logged invalid credentials, but the interactive path did not consistently translate the same failure into user-friendly UI feedback

## Implementation Outcome

The first pass focused on the highest-risk boundaries: Gmail credentials, OAuth callbacks, live and bulk message actions, rule creation, digest delivery, AI summaries, settings validation, stale UI state, and unexpected backend exceptions.

Completed areas:

- Gmail reconnect-required failures return stable API codes and friendly frontend messages.
- OAuth failures for denied consent, missing scopes, invalid/expired sessions, unsupported modes, and missing configuration are mapped explicitly.
- Bulk live and non-live message actions return per-message failures instead of collapsing the whole request.
- Rule creation can succeed even when the optional source-message apply fails, and the UI reports the partial result.
- AI digest summary failures degrade to normal digest delivery and preview.
- Notification settings validation returns field-level errors.
- Stale messages and stale rules refresh the affected UI lists.
- Unexpected backend exceptions are logged with safe method/path context and return a stable `internal_error` code.

Remaining posture:

- Add operation-specific logs only when production debugging shows the global unexpected-error context is too coarse.
- Add named domain exceptions only where stable codes improve the frontend or scheduled job reporting.
- Keep AI, Gmail, and OAuth secrets out of all user messages and logs.

## Guiding Principles

1. User-facing errors should be plain language.
2. Logs should preserve technical detail.
3. Expected operational failures should not become `500 Internal Server Error`.
4. Background jobs should record per-account/per-user failures without stopping the whole job.
5. Frontend actions should always leave the user with a visible final state.
6. Sensitive values must never appear in user messages or logs.
7. Error handling should be added at boundaries first, not scattered everywhere.

## Error Taxonomy

Fynish should classify errors into a small set of categories.

### 1. Authentication and Authorization

Examples:

- user not signed in
- inactive user
- user attempts to access another user's account/message/rule
- OAuth state mismatch

Expected user message:

- `Please sign in again.`
- `You do not have access to this item.`

Logging:

- warning for denied access
- include user id and resource type when safe
- do not log OAuth codes or tokens

### 2. External Credential State

Examples:

- Gmail token expired or revoked
- Gmail account lacks required scope
- digest sender OAuth missing or invalid
- OpenAI API key missing or quota unavailable

Expected user message:

- `Stored Gmail credentials were expired or revoked. Reconnect the account.`
- `Gmail send permission was not granted. Reconnect the digest sender.`
- `AI summary is unavailable because OpenAI billing or quota is not ready. The normal digest was sent.`

Logging:

- warning for user-fixable credential failures
- include account email and provider
- do not log access tokens, refresh tokens, auth codes, or API keys

### 3. External Service Runtime Failures

Examples:

- Gmail API timeout
- Gmail API rate limit
- OpenAI timeout
- OpenAI malformed/empty response
- mail send provider error

Expected user message:

- `Gmail is temporarily unavailable. Try again in a few minutes.`
- `The AI summary could not be generated, so Fynish sent the normal digest.`

Logging:

- warning for transient failures
- exception stack for unexpected provider errors
- include provider, operation, user id, account email when safe

### 4. Validation and User Input

Examples:

- invalid timezone
- invalid digest time
- missing rule pattern
- unsupported rule action
- invalid message action

Expected user message:

- directly state the invalid field and expected format

Logging:

- usually no stack trace
- warning only if repeated or suspicious

### 5. Not Found and Stale UI State

Examples:

- message already processed
- rule deleted in another tab
- account disabled while page is open

Expected user message:

- `Message not found. Refresh the page and try again.`
- `This item is no longer available.`

Logging:

- usually info/debug, not error

### 6. Database and Persistence

Examples:

- database unavailable
- schema mismatch
- transaction failure
- duplicate/constraint conflict

Expected user message:

- `Fynish could not save this change. Please try again.`

Logging:

- exception stack
- operation name
- user id if available
- never log full message bodies unless deliberately debugging locally

### 7. Background Job Partial Failures

Examples:

- one monitored account fails sync but others succeed
- one user digest fails but other users send
- AI summary fails but normal digest sends

Expected user message:

- user-facing only if triggered interactively
- digest/report should degrade gracefully

Logging:

- structured per-user/per-account summary
- totals for succeeded, skipped, failed

## Boundary Strategy

Add error handling at system boundaries first.

### Backend API Boundary

Each API route should translate known service exceptions into intentional HTTP responses.

Recommended pattern:

- `400` for user-fixable provider/config/validation errors
- `401` for missing auth
- `403` for forbidden access
- `404` for missing resources
- `409` for conflict/stale state
- `502` or `503` for upstream provider outage if the user cannot fix it
- `500` only for unexpected bugs

Routes should not expose raw tracebacks to users.

### Service Boundary

Services should raise meaningful domain exceptions instead of raw provider/library exceptions.

Examples:

- `GmailReadonlyNotConfiguredError`
- `GmailReadonlySyncError`
- `DigestSenderAuthError`
- future: `FynishProviderUnavailableError`
- future: `FynishUserActionRequiredError`

Services should not decide how HTTP maps errors unless they are already API-specific.

### Frontend Boundary

The frontend should display clean error messages from API `detail`.

Every user action should:

- set a busy state
- show an in-progress notice
- clear or update busy state in `finally`
- show a success notice or actionable error notice

Avoid silent failures and raw JSON errors.

### Background Job Boundary

Scheduled jobs should:

- keep running if one account/user fails
- return structured summaries
- log failures with enough detail to diagnose
- avoid repeating noisy stack traces for known repeated failures

## First-Pass Audit Scope

Status: completed. This section is retained as the original audit scope and as a starting point for future hardening passes.

## Backend Routes

Audit `backend/app/api/routes.py` for routes that call services without known exception mapping.

Priority routes:

- `POST /api/messages/{message_id}/live-execute`
- `POST /api/messages/apply-selected-live`
- `POST /api/messages/{message_id}/recover`
- `POST /api/messages/{message_id}/action`
- `POST /api/rules`
- `PATCH /api/rules/{rule_id}`
- `DELETE /api/rules/{rule_id}`
- `GET /api/digests/processed/preview`
- `POST /api/tasks/send-digests`
- `POST /api/tasks/sync-unread`

Completed examples:

- expired-token Gmail live action now maps to a friendly reconnect error instead of a raw `500`
- rule creation followed by live/source-message apply reports partial success when apply fails
- recover path maps expired Gmail credentials to reconnect guidance
- bulk live and non-live apply report per-message failures
- digest preview and delivery degrade when the AI provider fails

## Backend Services

Audit service modules for raw provider/library exceptions that should become domain exceptions.

Priority files:

- `backend/app/services/gmail_readonly.py`
- `backend/app/services/gmail_write_executor.py`
- `backend/app/services/mail_provider_adapter.py`
- `backend/app/services/message_recovery.py`
- `backend/app/services/review_queue.py`
- `backend/app/services/digests.py`
- `backend/app/services/ai_digest_summary.py`
- `backend/app/services/mailer.py`
- `backend/app/services/gmail_web_oauth.py`

## Frontend User Actions

Audit action handlers in `frontend/src/App.tsx`.

Priority handlers:

- refresh mail account
- single message action
- teach Fynish / create rule from message
- recover processed message
- reconnect Gmail
- digest sender connect
- save settings
- disable/enable account

Target behavior:

- user always sees either success or actionable failure
- reconnect-required errors should guide the user to Accounts page/Reconnect Gmail
- stale message/rule/account errors should suggest refresh

## Scheduled Jobs

Audit:

- sync timer
- digest timer
- AI digest generation
- Gmail sender

Target behavior:

- summary logs should include counts by status
- repeated known failures should be concise
- unexpected failures should include stack traces

## Logging Strategy

## Log Levels

Use:

- `info`: normal scheduled job summaries, successful important operations
- `warning`: user-fixable expected failures, provider temporary failures, skipped account sync
- `exception`: unexpected errors or bugs needing stack trace
- `debug`: local-only diagnostic detail

## Minimum Log Context

When safe, include:

- operation name
- user id
- account email
- provider
- message id or rule id
- status
- error class

Avoid logging:

- OAuth tokens
- OpenAI API keys
- auth codes
- full email bodies
- long snippets unless explicitly debugging locally

## Error Response Shape

FastAPI currently returns:

```json
{"detail": "Message"}
```

Fynish now preserves `detail` and adds `code` for stable user-action cases:

```json
{
  "detail": "Stored Gmail credentials were expired or revoked. Reconnect the account.",
  "code": "gmail_reconnect_required"
}
```

Recommendation:

- keep `detail` for compatibility
- use `code` when the frontend needs stable behavior beyond displaying the message
- add fields like `action` or `account_email` only if a future UI needs them

## Implementation Phases

Status: phases 1 through 4 were completed in the first hardening pass. Phase 5 has baseline coverage through per-account/per-user summaries and AI fallback behavior. Phase 6 remains the checklist before publishing more widely.

## Phase 1: Error Handling Audit

Create an audit table covering each route and key frontend action.

Columns:

- area
- file/function
- likely failure modes
- current behavior
- desired user message
- desired log behavior
- priority
- test needed

Deliverable status:

- complete in `docs/ERROR_HANDLING_AUDIT.md`

## Phase 2: Backend Exception Mapping

Add a small backend error module.

Recommended file:

- `backend/app/core/errors.py`

Potential classes:

- `FynishError`
- `UserActionRequiredError`
- `ProviderCredentialError`
- `ProviderUnavailableError`
- `ValidationUserError`
- `StaleResourceError`

Potential helper:

```python
def http_exception_for_error(error: Exception) -> HTTPException:
    ...
```

Status: complete for the first pass. Existing and newly named domain exceptions map through `backend/app/core/errors.py`.

## Phase 3: Route Hardening

Update highest-risk routes first:

1. live Gmail action routes
2. recover route
3. rule creation with apply/live-apply
4. sync route
5. digest preview/send route

Status: complete for the first pass, with focused regression coverage for the highest-risk paths.

## Phase 4: Frontend Error UX

Improve user notices:

- parse API `detail`
- recognize reconnect-required messages
- surface account email when available
- keep busy state correct
- consider inline account status badges for credential problems

Status: complete for the first pass.

The Accounts page shows `Reconnect required` when a token is known invalid.

## Phase 5: Background Job Observability

Improve log summaries for:

- sync runs
- digest runs
- AI summary failures

Possible later enhancement:

- persist recent job status in a table so Settings can show system health.

## Phase 6: Production Review Checklist

Before publishing wider:

- no expected provider error produces `500`
- expired credentials always produce reconnect guidance
- user-scoped access failures are `403` or `404`, not data leakage
- background jobs degrade per account/user
- frontend never leaves busy state stuck
- logs contain enough context but no secrets

## Initial Priority List

Highest priority:

1. Done: Gmail credential errors across sync, live apply, recover, and rule-apply flows
2. Done: frontend display of API `detail` and stable `code`
3. Done: AI digest provider failure behavior
4. Done: digest sender auth and send-scope errors
5. Done: stale message/rule/account errors

Medium priority:

1. Later: database constraint conflicts
2. Done: OAuth callback edge cases
3. Done: bulk action partial failure reporting
4. Baseline done: scheduler partial-failure summaries

Lower priority:

1. formal typed error envelope
2. in-app operational health dashboard
3. persisted job status history

## Testing Strategy

For every hardened path, add at least one regression test.

Recommended test patterns:

- mock service raises known domain exception
- assert HTTP status and `detail`
- assert frontend API helper extracts `detail`
- assert normal fallback path still succeeds
- assert background job continues after one item fails

Examples:

- expired Gmail token during `live-execute` returns `400` with reconnect detail
- AI summary provider error still sends normal digest
- digest sender revoked token returns friendly sender reconnect message
- recover with expired token returns friendly reconnect message

## Definition of Done

An error handling improvement is done when:

- the failure has a known category
- backend maps it to intentional HTTP status
- user message is clear and actionable
- log message contains safe diagnostic context
- frontend displays the message cleanly
- regression test covers the behavior
