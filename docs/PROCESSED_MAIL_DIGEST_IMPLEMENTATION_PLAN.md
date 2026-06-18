# Processed Mail Digest Implementation Plan

## Purpose

This document turns the processed-mail digest spec into a concrete implementation plan.

It assumes the approved V1 product definition:

- one daily per-user digest
- sent in the user's timezone
- one combined digest across all connected accounts
- includes processed counts, counts by action, counts by action source, top sender domains, new rules created, current queue count, and a processed-mail list
- processed-mail list capped at 50 rows
- plain text first

Reference:

- [PROCESSED_MAIL_DIGEST_SPEC.md](docs/PROCESSED_MAIL_DIGEST_SPEC.md)

## Implementation Summary

Recommended delivery order:

1. add digest persistence and settings fields
2. build digest data/query service
3. build plain-text rendering and preview
4. add mail transport abstraction
5. add scheduled send endpoint and due-user selection
6. add settings UI
7. test with one trusted user before broader rollout

## Current Implementation Status

As of May 31, 2026, the project already has meaningful digest scaffolding in place.
The next implementation pass should build on it rather than starting from scratch.

Already present:

- `backend/app/services/digests.py`
- `backend/app/services/mailer.py`
- `GET /api/digests/processed/preview`
- `POST /api/tasks/send-digests`
- `digest_delivery_log`
- `notification_settings_by_user.digest_enabled`
- `notification_settings_by_user.digest_time`
- plain-text digest rendering
- scheduled due-user selection
- duplicate-send protection by local digest day
- Postmark and SendGrid mailer support
- Gmail sender support through `digest.sender@example.com`
- HTML digest rendering with plain-text fallback
- Settings UI controls for digest enabled, recipient, time, and timezone

Still needed before turning this on:

- flip `FYNISH_SCHEDULED_DIGESTS_ENABLED=1` on the VM when ready for live scheduled sends
- watch the first scheduled run after enabling

Selected provider choice:

- use Gmail API send access from the dedicated sender account `digest.sender@example.com`
- do not add `digest.sender@example.com` as a monitored mail account
- store sender OAuth separately in `digest_sender_connections`

Required VM env vars:

- `FYNISH_MAIL_PROVIDER=gmail`
- `FYNISH_GMAIL_SENDER_EMAIL=digest.sender@example.com`
- `FYNISH_FRONTEND_URL=https://your-fynish-host.example.com/`
- `FYNISH_SCHEDULED_DIGESTS_ENABLED=1` only after manual testing passes

Operational preflight:

1. verify `notification_settings_by_user` has the target user with `digest_enabled = 1`
2. verify `digest_time` is in the user's timezone
3. verify `digest_sender_connections` has `digest.sender@example.com` with Gmail send scope
4. call `build_processed_digest_payload` for the target user and inspect the text
5. call `send_processed_digest` manually once
6. confirm one `digest_delivery_log` row with `status = sent`
7. only then enable the scheduled endpoint

## Phase 1: Data Model

### Goals

- track digest send history
- prevent duplicate sends
- store digest-specific settings cleanly

### Schema changes

#### 1. Add `digest_delivery_log`

Recommended columns:

- `id`
- `user_id`
- `digest_type`
- `window_start`
- `window_end`
- `scheduled_for`
- `sent_at`
- `status`
- `recipient_email`
- `processed_count`
- `new_rules_count`
- `queue_count`
- `error_message`
- `created_at`
- `updated_at`

Recommended status values:

- `pending`
- `sent`
- `skipped`
- `failed`

Recommended digest type values:

- `daily_processed`

#### 2. Extend `notification_settings_by_user`

Recommended new fields:

- `digest_enabled`
- `digest_time`

Optional but not required in V1:

- `digest_frequency`
- `digest_only_if_activity`

### Notes

- keep this small and additive
- do not redesign the existing reminder settings table yet
- use current user-scoped settings infrastructure

## Phase 2: Backend Digest Query Service

### Goals

- compute the correct digest window
- gather digest metrics for one user
- gather processed-mail rows for one user

### New service

Recommended file:

- `backend/app/services/digests.py`

### Recommended functions

- `get_digest_window(user_id: int, as_of: datetime | None = None) -> tuple[datetime, datetime]`
- `build_processed_digest_payload(user_id: int, as_of: datetime | None = None) -> dict`
- `render_processed_digest_text(payload: dict) -> str`

### Query behavior

#### Processed count

Use `actions_log` rows in the digest window, scoped to the user.

Exclude:

- recovery-only audit rows

Include:

- automatic actions
- manual actions

#### Counts by action source

Return per-source counts using `actions_log.action_source`.

Recommended V1 source buckets:

- `manual`
- `rule_auto_apply`
- `high_confidence_auto_clean`
- `legacy_unknown`

Render these in user-friendly language:

- Manual
- Rule auto
- Auto-clean
- Legacy

Why this matters:

- it answers how much Fynish did automatically
- it makes high-confidence auto-clean visible
- it prevents older, pre-stamp rows from being misrepresented

#### Counts by action

Return per-action counts for:

- `keep`
- `bulk_mail`
- `junk_review`
- `trash`
- `needs_review`, if it exists in processed history

#### New rule count

Use `rules.created_at` within the same digest window, scoped to the user.

#### Queue count

Use current queue state at send time:

- `messages.reviewed = 0`
- scoped to the user's accounts

#### Domain summary

Add a same-domain summary to the digest payload.

Recommended V1 name:

- `top_sender_domains`

Recommended row fields:

- `sender_domain`
- `message_count`
- `counts_by_action`
- `counts_by_source`
- `latest_processed_at`
- `sample_subjects`

Recommended cap:

- top 10 domains by processed-message count
- include up to 3 sample subjects per domain

Recommended sort:

1. `message_count DESC`
2. `latest_processed_at DESC`
3. `sender_domain ASC`

Recommended SQL shape:

```sql
WITH processed AS (
  SELECT
    l.id,
    l.selected_action,
    COALESCE(l.action_source, 'legacy_unknown') AS action_source,
    l.created_at AS processed_at,
    COALESCE(NULLIF(m.sender_domain, ''), 'unknown') AS sender_domain,
    COALESCE(m.subject, 'Unknown subject') AS subject
  FROM actions_log l
  LEFT JOIN messages m
    ON l.message_id = m.id
    OR (
          l.message_id IS NULL
      AND l.gmail_message_id = m.gmail_message_id
      AND l.account_email = m.account_email
    )
  LEFT JOIN mail_accounts owned_ma
    ON owned_ma.id = m.mail_account_id
  LEFT JOIN mail_accounts account_ma
    ON account_ma.external_account_email = l.account_email
   AND account_ma.user_id = :user_id
  WHERE l.selected_action != 'recover'
    AND l.created_at >= :window_start
    AND l.created_at < :window_end
    AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
)
SELECT
  sender_domain,
  COUNT(*) AS message_count,
  MAX(processed_at) AS latest_processed_at
FROM processed
GROUP BY sender_domain
ORDER BY message_count DESC, latest_processed_at DESC, sender_domain ASC
LIMIT :limit;
```

For `counts_by_action`, `counts_by_source`, and sample subjects, prefer either:

- one additional grouped query per detail type, or
- one broader row query in Python that folds rows into domain buckets

Recommended implementation:

- use one broader row query in Python for V1

Reason:

- digest windows are daily and capped by normal user volume
- Python aggregation keeps the SQL readable
- the same row set can produce top domains, per-domain action counts, per-domain source counts, and samples

Important details:

- normalize blank domains to `unknown`
- keep domains lowercase
- do not include recovery rows
- include both manual and automatic processed messages
- domain summary should match the same user/window scoping as processed count

Recommended plain-text rendering:

```text
Top sender domains:
- wsj.com: 8 messages (Bulk 6, Keep 2; Auto-clean 2, Rule auto 4, Manual 2)
  Examples: Tokenmaxxing Maxes Out; The 10-Point
- example.net: 5 messages (Trash 5; Rule auto 5)
```

If there are no processed messages:

```text
Top sender domains: none
```

Product value:

- quickly shows repeated senders/domains without reading every row
- helps identify domains that deserve explicit rules
- gives a compact "what was noisy today?" summary
- pairs well with the new Processed Mail auto-clean feedback buttons

#### Processed-mail list

Return newest first, capped at 50 rows.

Recommended row fields:

- `selected_action`
- `action_source`
- `sender`
- `sender_domain`
- `subject`
- `processed_at`
- `account_email`

### Digest window rule

Recommended V1 window:

- local midnight to current digest send cutoff in the user's timezone

This is easier to reason about than a rolling 24-hour window.

## Phase 3: Preview and Internal API

### Goals

- inspect digest output before sending live mail
- make testing easier

### New preview endpoint

Recommended endpoint:

- `GET /api/digests/processed/preview`

Behavior:

- current signed-in user only
- returns payload plus plain-text preview

### Response shape

Recommended fields:

- `generated_at`
- `window_start`
- `window_end`
- `recipient_email`
- `processed_count`
- `counts_by_action`
- `counts_by_source`
- `new_rules_count`
- `queue_count`
- `top_sender_domains`
- `processed_messages`
- `plain_text_preview`

### Why this matters

- lets us validate content without wiring outbound email first
- gives the settings screen something previewable later

## Phase 4: Mail Transport

### Goals

- send email through one clear backend abstraction
- avoid coupling digest logic to a single provider

### New service

Recommended file:

- `backend/app/services/mailer.py`

### Recommended interface

- `send_plain_text_email(to_email: str, subject: str, body: str) -> dict`

### Provider choice

Recommended:

- Gmail API with the dedicated sender account `digest.sender@example.com`

Earlier notes considered Postmark or SendGrid. Gmail is the current implementation choice because the project has a dedicated Gmail sender account and does not need separate branded-domain deliverability work for the first beta.

### Config needed

Likely new env vars:

- provider selection
- API key secret
- sender/from email

Recommended examples:

- `FYNISH_MAIL_PROVIDER`
- `FYNISH_GMAIL_SENDER_EMAIL`

Postmark/SendGrid support can still use:

- `FYNISH_MAIL_FROM_EMAIL`
- `FYNISH_MAIL_API_KEY`

### V1 scope

- plain text only
- one message per digest

## Phase 5: Scheduled Delivery

### Goals

- send digests automatically
- avoid duplicate sends
- honor user timezone and digest time

### New scheduled endpoint

Recommended endpoint:

- `POST /api/tasks/send-digests`

### Backend behavior

1. load users where `digest_enabled = 1`
2. determine whether each user is due right now
3. compute that user's digest window
4. build the digest payload
5. decide whether to skip sending based on activity rule
6. send the email if appropriate
7. write a `digest_delivery_log` row

### Skip rule

Approved V1 rule:

- still send if queue count is nonzero, even if processed count is zero

So skip only when all are true:

- processed count is 0
- new rule count is 0
- queue count is 0

### Duplicate protection

Before sending, check whether a successful `daily_processed` digest already exists for:

- same user
- same window start

Do not include the exact window end in duplicate protection. The VM scheduler runs more often than once per day, so `window_end` changes on every scheduler pass. Using the local-day window start prevents repeated sends after a user's due time.

If yes:

- skip

### Scheduler integration

On the single VM, use a local `systemd` timer similar to unread sync.

Recommended cadence:

- every 5 minutes

Reason:

- the backend can decide whether a user is actually due
- no need to create one Cloud Scheduler job per user

Current VM timer:

- `fynish-send-digests.timer`
- invokes `POST http://127.0.0.1:8000/api/tasks/send-digests`
- active while `FYNISH_SCHEDULED_DIGESTS_ENABLED=0`, so it is safe until the backend env flag is enabled

## Phase 6: Settings UI

### Goals

- let users enable/disable digests
- configure send time
- show where the digest will go

### Frontend files likely involved

- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/types.ts`

### UI additions

In `Settings`, add:

- digest enabled toggle
- digest send time
- digest recipient display
- short helper copy explaining what the digest includes
- read-only preview button or panel for the current daily digest payload

Recommended copy:

- `Send a daily summary of processed mail, new rules, and current queue state.`
- `Includes top sender domains so repeated sources are easy to spot.`

### Recipient logic

Approved rule:

- use notification recipient if set
- otherwise fall back to signed-in user email

### Preview

Recommended for V1.5 or V2:

- show a read-only digest preview card

Not required to ship the first live version if backend preview already exists.

## Phase 7: Testing

### Backend tests

Add coverage for:

- digest window calculation by timezone
- processed count scoping by user
- rule count scoping by user
- queue count scoping by user
- action-source counts
- top sender domains by count
- per-domain counts by action
- per-domain counts by action source
- domain sample subject cap
- unknown sender domain handling
- processed list capped at 50
- recovery rows excluded
- duplicate-send protection
- skip logic for empty activity
- due-user selection

### Frontend tests

Add coverage for:

- digest settings rendering
- digest toggle persistence
- digest time editing
- recipient fallback display

### Manual tests

#### Single-user

- enable digest
- set digest time near the current time
- create processed activity
- create a rule
- verify digest content

#### Multi-user

- user A and user B both enabled
- ensure user A receives only user A data
- ensure user B receives only user B data

#### Empty-state behavior

- no processed activity, no rules, no queue
- confirm digest is skipped

#### Nonzero queue with no processed activity

- confirm digest still sends

## Phase 8: Rollout

### First rollout target

Recommended:

- one trusted user first

### Live rollout steps

1. deploy schema and backend preview
2. verify preview payload in hosted mode
3. configure mail provider secret
4. send one manual test digest
5. enable scheduled endpoint
6. enable digest for one trusted user
7. observe for several days

### Operational checks

Watch for:

- duplicate sends
- missing sends
- timezone mismatches
- incorrect queue count
- unexpectedly large emails

## Risks and Mitigations

### Risk: timezone mistakes

Mitigation:

- keep the window rule simple
- test with explicit timezone cases

### Risk: user data leakage

Mitigation:

- keep every digest query user-scoped
- add multi-user integration tests before rollout

### Risk: digest too long

Mitigation:

- cap processed list at 50
- add `+ N more not shown`
- cap domain summary at 10 domains and 3 sample subjects per domain

### Risk: domain summary overstates rule recommendations

Mitigation:

- present domain summary as an observation, not an instruction
- keep rule creation inside the app where the user can inspect examples
- include action/source counts so a noisy domain is not mistaken for an automatically bad domain

### Risk: mail provider complexity

Mitigation:

- isolate it behind `mailer.py`
- start with plain text only

## Recommended Immediate Next Step

The best next implementation pass is:

1. extend `build_processed_digest_payload` with `counts_by_source`
2. add `top_sender_domains` aggregation
3. render the domain summary in `render_processed_digest_text`
4. update digest tests
5. re-expose digest settings and preview in the Settings UI
6. configure Postmark on the VM
7. send one manual digest to a trusted recipient

This keeps the next pass focused on content quality and confidence before scheduled delivery is enabled.
