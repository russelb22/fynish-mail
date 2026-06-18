# Fynish Error Handling Audit

This document turns `docs/ERROR_HANDLING_STRATEGY.md` into an implementation checklist.

The goal is to harden the highest-risk boundaries first: user clicks, provider credentials, background jobs, and digest delivery. Avoid broad try/catch additions that make failures quieter without making them more understandable.

## Closeout Status

Status: first implementation pass completed and deployed to the single VM on 2026-06-04.

The pass now has no known high-priority user-facing error handling gaps. It added stable API error codes, stale UI handling, per-item bulk failure results, digest and AI fallback behavior, field-level settings validation, and a global unexpected-error handler.

Latest deployment validation:

- backend service active
- frontend service active
- `GET /api/health` returned `{"status":"ok"}`
- local frontend returned `302`
- public login endpoint returned `200`

## Priority Legend

- `P0`: User-facing failure that can currently mislead the user, block a core workflow, or produce an avoidable `500`.
- `P1`: User-facing or scheduled failure that should be clearer and better logged.
- `P2`: Useful cleanup or consistency improvement.
- `P3`: Nice-to-have polish after the core handling is reliable.

## Backend API Routes

| Area | Priority | Current behavior | Desired behavior |
| --- | --- | --- | --- |
| `POST /api/messages/{message_id}/live-execute` | P0 | Done 2026-06-04: expired/revoked Gmail credentials return `400` with stable code `gmail_reconnect_required`; frontend `ApiError` carries the code. | Extend stable codes to additional domain errors as they become UI-significant. |
| `POST /api/messages/apply-selected-live` | P0 | Done 2026-06-04: returns per-message results for executed, blocked, provider-failed, and stale/missing messages. | Good current baseline. |
| `POST /api/rules` | P0 | Done 2026-06-04: rule creation remains successful when the optional source-message apply returns missing or raises a known apply error. The response includes `apply_error` for the UI. | Continue monitoring for other source-apply exceptions that should become domain errors instead of unexpected failures. |
| Frontend `Teach Fynish` live path | P0 | Done 2026-06-03: rule creation success is preserved when later source/live apply fails. | Good current baseline. |
| `POST /api/messages/{message_id}/recover` | P0 | Done 2026-06-04: catches `GmailReadonlySyncError`, returns `400`, and includes stable code `gmail_reconnect_required`; missing message returns `404`. | Good current baseline. |
| `POST /api/messages/{message_id}/action` | P1 | Done 2026-06-04: missing message returns `404`, unsafe action plans return `400` with stable code `unsafe_message_action`, and the frontend refreshes stale queue items. | Unexpected persistence errors are covered by the global handler; add operation-specific logs only if needed. |
| `POST /api/messages/apply-selected` | P1 | Done 2026-06-04: returns `applied` plus per-message `failed` entries for stale messages and known apply errors. | Frontend can now surface partial success if a bulk non-live UI returns. |
| `POST /api/sync/unread` | P1 | Done 2026-06-03: service records per-account Gmail failures and returns `failed_accounts`; frontend shows all failed accounts or a concise summary. | Add more mixed provider tests only if regressions appear. |
| `POST /api/tasks/sync-unread` | P1 | Done 2026-06-03: scheduled service returns structured totals and the sync service handles per-account failures. | Good current baseline. |
| `POST /api/tasks/send-digests` | P1 | Done 2026-06-04: catches unexpected scheduler-level exceptions, logs the operation, and returns a structured failed summary. | Keep per-user failures in the digest service and continue monitoring sender/AI fallback behavior. |
| `GET /api/digests/processed/preview` | P1 | Done 2026-06-04: AI summary failure degrades to a normal digest with `ai_summary_error`; preview remains `200`. | Continue treating AI as optional and non-blocking. |
| `PATCH /api/settings/notifications` | P1 | Done 2026-06-04: returns field-specific `400` validation messages for invalid digest time, timezone, and recipient email. | Add frontend field-level hints later only if generic notice text proves insufficient. |
| Gmail OAuth start/callback routes | P1 | Done 2026-06-04: maps configuration, unsupported mode, denied consent, missing scopes, expired/invalid sessions, and mismatched signed-in user errors to stable codes. | Continue keeping OAuth codes/tokens out of logs. |
| Digest sender OAuth routes | P1 | Done 2026-06-04: callback path returns friendly missing `gmail.send` scope message with `gmail_oauth_missing_scope`; callback proxy preserves the code for UI redirects. | Good current baseline. |
| Account enable/disable routes | P2 | Done 2026-06-03: missing account returns `404`; account responses include credential status so the UI can show enabled-but-reconnect-required states after refresh/re-enable. | Good current baseline. |
| Rule update/delete routes | P2 | Done 2026-06-04: missing rule returns `404`, and the frontend refreshes the rule list with a stale-rule notice. | Add validation mapping for unsupported updates. |
| Global API exception handler | P1 | Done 2026-06-04: unexpected exceptions are logged with safe method/path context and return `500` with stable code `internal_error`. | Add more operation-specific logs where they would aid debugging. |

## Backend Services

| Service | Priority | Risk | Desired hardening |
| --- | --- | --- | --- |
| `gmail_readonly.py` | P0 | Expired/revoked credentials and missing scopes are common and user-fixable. | Continue raising `GmailReadonlySyncError` with actionable text. Ensure provider details are logged safely and never expose tokens. |
| `gmail_write_executor.py` | P0 | Done 2026-06-04: live and bulk modify paths convert known Gmail failures into blocked/failed execution results by account/message. | Continue adding provider-specific failure classes only when they improve UI or logs. |
| `message_recovery.py` | P0 | Done 2026-06-04: recovery maps expired/revoked Gmail credentials to stable reconnect-required responses. | Add broader missing-connection coverage only if production logs show gaps. |
| `review_queue.py` | P1 | Done 2026-06-04: sync and action paths preserve partial-failure behavior and stale-message handling. | Keep using this as the model for provider loops: continue per account, record failed accounts, log safe warning context. |
| `digests.py` | P1 | Done 2026-06-04: digest generation catches AI summary failures and renders a short summary-unavailable note in text and HTML. | Keep sender failures separate from optional AI failures. |
| `ai_digest_summary.py` | P1 | Done 2026-06-04: OpenAI quota, permissions, model limits, timeout, or malformed output degrade to a normal digest with `ai_summary_error`. | Treat AI as a non-critical enhancement. Log provider status and model, never log API keys, and cap prompt/output sizes. |
| `mailer.py` | P1 | Gmail send may fail due to missing sender credentials or send scope. | Raise a domain-level send error with friendly text. Logs should include recipient/user id and omit credential material. |
| `gmail_web_oauth.py` | P1 | Done 2026-06-04: OAuth state mismatch, denied consent, missing scopes, wrong login, unsupported mode, and missing config are normalized into explicit user-action messages and stable codes. | Continue keeping OAuth codes/tokens out of logs. |
| `accounts.py` | P2 | Done 2026-06-03: account auth status distinguishes enabled accounts from accounts that need reconnect. | Good current baseline. |
| `rules.py` | P2 | Done 2026-06-04: account/source-message availability validation uses named domain exceptions with stable codes. | Consider domain exceptions for duplicate/conflicting rules once rule complexity grows. |

## Frontend Actions

| Action | Priority | Current behavior | Desired behavior |
| --- | --- | --- | --- |
| `handleTeachFynish` | P0 | Done 2026-06-03: rule creation success is preserved when later source/live apply fails, and the UI explains the partial result. | Good current baseline. |
| `handleSync` | P1 | Done 2026-06-03: shows all failed accounts when there are a few, or a summary count plus first examples when many fail. | Good current baseline. |
| `handleSingleAction` | P1 | Done 2026-06-04: stale `404` refreshes the queue and shows a clear no-longer-available notice; reconnect-required API codes now flow through the frontend API layer. | Good current baseline. |
| `handleRecoverProcessedMessage` | P1 | Done 2026-06-04: stale `404` refreshes processed mail and shows a clear no-longer-available notice. | Good current baseline. |
| `handleReconnectGmailAccount` | P1 | Opens OAuth and surfaces API errors. | Good current baseline. Consider disabling the button while navigating away to avoid duplicate clicks. |
| `handleConnectDigestSender` | P1 | Opens OAuth and surfaces API errors. | Good current baseline. Ensure missing send scope text is friendly. |
| `handleSaveDigestSettings` | P1 | Done 2026-06-04: shows field-level hints for invalid digest time, timezone, and recipient email while preserving the masthead notice; backend validation returns stable code `notification_settings_validation_failed`. | Good current baseline. |
| Rule toggle/delete handlers | P2 | Done 2026-06-04: stale `404` refreshes the rule list and shows `Rule no longer exists. Refreshed the list.` | Continue to show API error text for non-stale failures. |
| Account enable/disable handlers | P2 | Done 2026-06-03: account status refreshes after changes, and enabled-but-reconnect-required state is visible from account metadata. | Good current baseline. |
| OAuth account ownership and digest sender validation | P2 | Done 2026-06-04: named domain exceptions return stable codes `gmail_account_already_connected` and `digest_sender_validation_failed`. | Continue replacing generic `ValueError` only where the UI benefits from stable codes. |

## Background Jobs And Logs

| Job | Priority | Desired behavior |
| --- | --- | --- |
| Scheduled unread sync | P1 | Per-account failures, concise warning logs, structured counts, no repeated tracebacks for known revoked credentials. |
| Scheduled digest send | P1 | Per-user failures, normal digest fallback if AI summary fails, clear log entry when sender credentials or Gmail send scope are missing. |
| AI summary generation | P1 | Time-bound provider call, capped input size, fallback to normal digest, safe logs with provider/model/status. |
| Gmail OAuth callback | P1 | Safe audit log for success/failure, no OAuth code/token logging, clear user-facing redirects or API messages. |

## First Implementation Queue

1. Done 2026-06-03: Harden the `Teach Fynish` rule creation/live apply flow so a saved rule is never reported as a failed rule creation because the later Gmail live action failed.
2. Done 2026-06-03: Improve bulk live Gmail execution to return per-message failures instead of letting one provider exception fail the whole selected batch.
3. Partially done 2026-06-03: Add regression coverage for expired/revoked Gmail credentials on live action and recover routes. Live action coverage already existed; recover route coverage was added.
4. Done 2026-06-03: Surface account credential status in the Accounts UI so enabled-but-needs-reconnect is visible without requiring a failed click.
5. Done 2026-06-03: Introduce a small backend exception mapping helper for recurring domain exceptions after the first few route fixes prove the shape.
6. Done 2026-06-04: Harden `POST /api/rules` source-message apply so stale messages or known apply failures are reported as partial success instead of failed rule creation.
7. Done 2026-06-04: Harden `POST /api/messages/apply-selected` so non-live bulk apply returns per-message failures for stale or known apply errors.
8. Done 2026-06-04: Add stable error code support for Gmail reconnect-required failures and teach the frontend API layer to expose error codes.
9. Done 2026-06-04: Add stable OAuth error codes for denied consent, missing Gmail scopes, invalid/expired sessions, and OAuth configuration failures.
10. Done 2026-06-04: Make AI digest summary failures non-blocking for preview and delivery payload rendering.
11. Done 2026-06-04: Add notification settings validation coverage for digest time, timezone, and recipient email.
12. Done 2026-06-04: Add frontend field-level validation hints for digest settings.
13. Done 2026-06-04: Add global unexpected-exception handler with safe logs and stable `internal_error` response.
14. Done 2026-06-04: Complete bulk live action partial-failure handling for stale/missing messages.
15. Done 2026-06-04: Replace account-ownership and digest-sender setup `ValueError`s with named domain exceptions and stable codes.
16. Done 2026-06-04: Replace rule availability and unsafe-message-action `ValueError`s with named domain exceptions and stable codes.
17. Done 2026-06-04: Replace remaining unsupported OAuth mode, notification-settings validation, and digest missing-user `ValueError`s with named domain exceptions and stable codes.

## Remaining Known Gaps

- No known high-priority user-facing error handling gaps remain from this pass.
- Add operation-specific logs only where production debugging shows the global `internal_error` log context is too coarse.
- Continue adding named domain exceptions only where the frontend benefits from stable codes.

## Stable Error Codes Added

| Code | Meaning |
| --- | --- |
| `gmail_reconnect_required` | Stored Gmail credentials are expired, revoked, missing required scopes, or otherwise require reconnect. |
| `gmail_oauth_not_configured` | Google OAuth environment/configuration is missing. |
| `google_oauth_denied` | The user denied Google OAuth consent. |
| `gmail_oauth_missing_scope` | Google OAuth completed without a required Gmail scope. |
| `google_oauth_session_invalid` | OAuth state/session data is invalid or mismatched. |
| `google_oauth_session_expired` | OAuth state/session data has expired. |
| `gmail_oauth_unsupported_mode` | OAuth was started with an unsupported mode. |
| `gmail_account_already_connected` | A Gmail account is already connected to another Fynish account. |
| `digest_sender_validation_failed` | Digest sender setup failed validation, such as wrong sender account. |
| `rule_account_unavailable` | A rule references an unavailable or unauthorized monitored account. |
| `rule_source_message_unavailable` | A rule source message is missing, stale, or unavailable. |
| `unsafe_message_action` | A requested message action would be unsafe or unsupported. |
| `notification_settings_validation_failed` | Notification settings input failed field validation. |
| `digest_user_not_found` | A digest operation referenced an unknown user. |
| `internal_error` | An unexpected backend failure occurred and was logged safely. |

## Definition Of Done For Each Hardening Slice

Each hardened boundary should have:

- a category from the taxonomy in `docs/ERROR_HANDLING_STRATEGY.md`
- an intentional HTTP status for known failures
- a plain-language user message
- safe log context with no secrets
- frontend behavior that leaves the user with a final state
- at least one focused regression test for the expected failure
