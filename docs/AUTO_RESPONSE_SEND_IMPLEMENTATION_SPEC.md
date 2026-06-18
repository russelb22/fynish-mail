# Auto-Response Send Implementation Spec

Status: V1 send implemented and deployed 2026-06-11. Gmail thread-history quoting V1 implemented locally 2026-06-11; pending VM deployment.

## Purpose

Extend Auto-Respond from draft-only generation to an explicit user-approved Gmail send flow inside Fynish.

The current Auto-Respond feature generates a draft response that the user manually copies into Gmail. This spec defines the safer next step: Fynish can send a response only after the user reviews the draft and explicitly clicks a send action.

## Product Decision

Do not implement one-click autonomous replies.

V1 should be:

- draft first
- user editable
- explicit send confirmation
- Gmail-thread aware where possible
- fully audited
- gated by feature flag and Gmail send/modify scope

## Current Baseline

Implemented now:

- `POST /api/messages/{message_id}/auto-response-draft`
- Review Queue `Auto-Respond` button
- guidance textbox
- copyable draft modal
- feature gate by signed-in user email
- OpenAI generation with structured draft output

Existing Gmail capabilities:

- Gmail readonly and modify connections
- Gmail write executor for label/archive/trash actions
- digest sender flow using Gmail send scope
- Gmail OAuth scope constants:
  - readonly
  - modify
  - send

Implemented V1:

- `POST /api/messages/{message_id}/auto-response-send`
- feature flag `FYNISH_AUTO_RESPONSE_SEND_ENABLED`
- allowlist `FYNISH_AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS`
- max body guard `FYNISH_AUTO_RESPONSE_SEND_MAX_BODY_CHARS`
- user-owned message and mail-account credential validation
- reviewed-body submit with confirmation flag and idempotency key
- send-preview endpoint that returns the exact editable body text including quoted context
- Gmail threaded send using the monitored account credentials
- bounded Gmail thread-history quote at send time, with stored-message fallback
- audit table `auto_response_sends`
- Review Queue modal edit/send UI

## Goals

- Let an allowlisted user send a reviewed Auto-Response from Fynish.
- Preserve the Gmail thread when possible.
- Save an audit record of exactly what was sent.
- Keep sending disabled for users who are not explicitly enabled.
- Make failures clear and non-destructive.

## Non-Goals

Do not include these in V1:

- autonomous send without review
- scheduled delayed send
- bulk auto-replies
- sending attachments
- rich HTML composition
- complex signature management
- follow-up tracking
- automatic classification/archival after send

## Recommended V1 UX

In the existing Auto-Respond modal:

1. User clicks `Auto-Respond`.
2. User adds optional context.
3. User clicks `Generate Draft`.
4. Draft appears in an editable textarea.
5. If sending is enabled, show `Send Reply` as a separate primary action.
6. On click, show confirmation:
   - recipient
   - sending account
   - subject/thread
   - final body preview
7. User confirms `Send Reply`.
8. Fynish sends via Gmail.
9. Modal shows sent status and Gmail message id.

Button states:

- `Generate Draft`
- `Regenerate Draft`
- `Copy Draft`
- `Send Reply`
- `Sending...`
- `Sent`

If sending is not enabled, keep the current draft-only UI.

## Safety Rules

Before sending, backend must verify:

- current user owns the message
- current user owns the receiving Gmail account
- feature flag allows this user
- message has a Gmail id and thread id
- account has Gmail send-capable credentials
- final body is non-empty
- final body length is within limit
- final body was reviewed/confirmed by the user
- request has an idempotency key

Backend must not trust:

- client-supplied account email
- client-supplied sender identity
- client-supplied ownership claims
- client-supplied Gmail thread id unless verified against DB

## Feature Flags

Backend env vars:

- `FYNISH_AUTO_RESPONSE_SEND_ENABLED=0`
- `FYNISH_AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS=primary.user@example.com`
- `FYNISH_AUTO_RESPONSE_SEND_REQUIRE_APPROVED_STYLE_CARD=0`
- `FYNISH_AUTO_RESPONSE_SEND_MAX_BODY_CHARS=8000`
- `FYNISH_AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS=1800`
- `FYNISH_AUTO_RESPONSE_SEND_THREAD_HISTORY_MESSAGES=2`
- `FYNISH_AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS=3000`

Rollout:

1. deploy disabled
2. enable for Russel only
3. test with a low-risk real message
4. keep Kim disabled until explicitly ready

## Gmail Scope

Preferred V1:

- use the user's own Gmail account credentials with `gmail.modify` if Gmail API send works with the granted scope
- otherwise require `gmail.send` or an upgraded OAuth scope mode

Important implementation check:

- Verify whether existing modify-capable connections include enough scope for `users.messages.send`.
- If not, add an account reconnect path for `modify+send`.

Recommended scope modes:

- `readonly`
- `modify`
- `send`
- `modify_send`

For normal account responses, prefer `modify_send` so Fynish can both send and continue queue operations for the same account.

## Data Model

Add a table:

```sql
CREATE TABLE IF NOT EXISTS auto_response_sends (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    mail_account_id BIGINT NULL REFERENCES mail_accounts(id) ON DELETE SET NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'gmail',
    account_email TEXT NOT NULL,
    to_email TEXT NOT NULL,
    cc_email TEXT NULL,
    bcc_email TEXT NULL,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    gmail_thread_id TEXT NULL,
    gmail_sent_message_id TEXT NULL,
    gmail_response JSONB NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ NULL
);
```

Uniqueness:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_response_sends_idempotency
ON auto_response_sends(user_id, idempotency_key);
```

Status values:

- `pending`
- `sent`
- `failed`
- `duplicate_replayed`

Store the sent body because it is the user-approved outbound message and auditability matters. This is different from style-sample raw corpora, which should not be persisted.

## API

Add endpoint:

```http
POST /api/messages/{message_id}/auto-response-send
```

Preview endpoint:

```http
POST /api/messages/{message_id}/auto-response-send-preview
```

The preview endpoint accepts the generated or edited draft body and returns the final proposed outbound body, including bounded Gmail thread context or stored-message fallback. The frontend places this returned body in the editable textarea so the user reviews exactly what will be submitted to Gmail. When sending from that preview, the frontend submits `include_context: false` to prevent the backend from appending the same context a second time.

Request:

```json
{
  "idempotency_key": "browser-generated-uuid",
  "draft_body": "Hi ...",
  "to_email_override": null,
  "cc": [],
  "bcc": [],
  "confirmed": true
}
```

Response:

```json
{
  "send": {
    "status": "sent",
    "message_id": 123,
    "gmail_sent_message_id": "18f...",
    "gmail_thread_id": "18e...",
    "sent_at": "2026-06-08T22:05:00Z"
  }
}
```

Validation errors:

- `403`: feature not enabled for user
- `404`: message not found or not owned by user
- `409`: idempotency conflict
- `422`: body missing or invalid
- `503`: Gmail send credentials missing
- `502`: Gmail API send failed

Optional endpoint:

```http
GET /api/messages/{message_id}/auto-response-send-plan
```

This can return whether send is available and why not:

```json
{
  "plan": {
    "send_available": true,
    "account_email": "user@example.com",
    "to_email": "sender@example.com",
    "subject": "Re: Original subject",
    "gmail_thread_id": "18e...",
    "notes": []
  }
}
```

## Backend Service

Add `backend/app/services/auto_response_send.py`.

Responsibilities:

- validate feature flag and allowlist
- fetch owned source message
- determine recipient from `reply_to` or sender email
- build reply subject
- build RFC 2822 email message
- attach `In-Reply-To` and `References` headers if available
- send through Gmail API
- persist audit row
- enforce idempotency

Recipient selection:

1. use `reply_to` email if present and valid
2. else use extracted sender email
3. reject if no valid recipient

Subject selection:

- if source subject already starts with `Re:`, preserve it
- otherwise prefix `Re: `

Threading:

- include Gmail `threadId` in send body when available
- include `In-Reply-To` if original RFC `Message-ID` is captured
- include `References` if captured

If Fynish does not currently persist RFC `Message-ID` headers, add it to future Gmail import. Gmail `threadId` alone may be enough for practical threading, but RFC headers are better.

## Gmail Thread-History Quoting V1

Purpose:

- Include useful visible context in the sent reply without sending an unbounded Gmail thread.
- Prefer live Gmail thread text when the monitored account has read-capable credentials.
- Keep sending reliable by falling back to the stored message excerpt when thread history cannot be fetched.

Behavior:

1. At send time, after ownership and credential validation, Fynish fetches the Gmail thread using `gmail_thread_id`.
2. It transforms Gmail message payloads with the same plain-text-preferred extraction used by inbox sync.
3. It quotes the most recent existing thread messages up to and including the current source message.
4. It excludes any Gmail messages after the current source message if the current message can be located in the fetched thread.
5. It caps the number of quoted messages with `FYNISH_AUTO_RESPONSE_SEND_THREAD_HISTORY_MESSAGES`.
6. It caps total quoted body text with `FYNISH_AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS`.
7. If no usable thread text is available, it falls back to the stored message excerpt capped by `FYNISH_AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS`.
8. The exact final outbound body, including any quoted context, is stored in `auto_response_sends.body_text`.

Scope note:

- Read-capable tokens such as `gmail.modify` can fetch thread history.
- Send-only tokens may not be able to read Gmail thread content. In that case, Fynish should still send using the stored excerpt fallback.

Non-goals for this slice:

- full Gmail thread rendering
- attachments
- HTML quote preservation
- user-selectable quote depth in the UI
- fetching or quoting messages outside the source Gmail thread

## Gmail Send Implementation

Construct raw message:

```python
from email.message import EmailMessage
import base64

message = EmailMessage()
message["To"] = to_email
message["From"] = account_email
message["Subject"] = reply_subject
message.set_content(body_text)

raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
body = {"raw": raw}
if gmail_thread_id:
    body["threadId"] = gmail_thread_id

service.users().messages().send(userId="me", body=body).execute()
```

If Gmail rejects `From`, use `me` semantics only in the API path but still set the header to the account email that owns the token.

## Draft Versus Send Relationship

V1 can send any edited body submitted from the modal.

Do not require sending the exact original generated draft because the user should be able to edit it.

Recommended guard:

- user must generate a draft or paste/edit body in the Auto-Respond modal
- body submitted to send endpoint is the source of truth
- audit row stores the submitted body

Optional later:

- persist generated drafts as draft records before send
- store model, style source, and prompt metadata for audit

## Frontend Changes

Types:

- `AutoResponseSendPlan`
- `AutoResponseSendResult`

API:

- `fetchAutoResponseSendPlan(messageId)`
- `sendAutoResponse(messageId, payload)`

UI:

- make generated draft textarea editable when send is enabled
- add `Send Reply` button only when feature flag allows it and plan says available
- add confirmation step
- show recipient/account details
- disable send while request is in flight
- show success with Gmail sent message id
- preserve `Copy Draft` for fallback

Feature flags:

- extend `/api/features` with `auto_response_send`

## Audit And Observability

Persist every send attempt.

Log:

- user id
- source message id
- account email
- status
- Gmail sent id
- error class/message

Do not log full body text to application logs.

Store full sent body only in `auto_response_sends.body_text`.

## Tests

Backend unit tests:

- feature flag blocks unauthorized users
- owned-message check is enforced
- recipient resolution uses `reply_to` before sender
- subject prefixing works
- body length and empty body validation works
- MIME message is constructed correctly
- idempotency replay returns prior result
- Gmail provider errors produce safe API errors

Backend integration tests:

- user A cannot send response for user B's message
- missing Gmail send credentials returns `503`
- successful fake Gmail send persists audit row
- duplicate idempotency key does not send twice

Frontend build/tests:

- Send button hidden when feature disabled
- Send button disabled when plan unavailable
- confirmation dialog shows recipient/account/body preview
- success state renders
- error state renders

Manual VM validation:

1. enable for Russel only
2. choose a harmless real message
3. generate draft
4. edit draft
5. send
6. confirm Gmail thread contains sent response
7. confirm `auto_response_sends` row exists
8. confirm Kim cannot see send controls and receives 403 if API is called

## Deployment Plan

Slice 1:

- add feature flag
- add send plan endpoint
- add frontend availability display
- no actual send

Slice 2:

- add send endpoint with fake provider tests
- add audit table
- add idempotency
- add frontend confirmation flow
- deploy disabled

Slice 3:

- enable for Russel only
- test one live message
- refine threading and error copy

Slice 4:

- decide whether to add Gmail draft creation as an intermediate option
- decide whether invited users should get send or remain draft-only

## Open Questions

- Does the current Gmail modify scope allow `users.messages.send`, or do we need `modify_send` reconnect?
- Should Fynish create a Gmail Draft first instead of sending directly?
- Should sent replies automatically mark the source message as `keep` or leave queue state unchanged?
- Should sends include a user-managed signature?
- Should the approved writing style card be required before send is enabled?

## Recommendation

Implement Gmail Draft creation before direct send if testing shows threading or user trust concerns.

If direct send is implemented first, keep it limited to:

- one user
- explicit confirmation
- no automation
- no bulk mode
- full audit records

## Acceptance Criteria

- Auto-Respond remains draft-only for users not allowlisted.
- Allowlisted user can review, edit, confirm, and send one response.
- Backend verifies ownership and Gmail credentials.
- Gmail receives the sent message in the expected account/thread.
- Send attempt is audited.
- Repeated submit with the same idempotency key does not send twice.
- Kim remains blocked until explicitly allowlisted.
