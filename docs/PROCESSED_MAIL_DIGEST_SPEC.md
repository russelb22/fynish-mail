# Processed Mail Digest Spec

## Purpose

This document defines a new Fynish notification feature:

- send a daily digest email to each user
- summarize what Fynish processed during the digest window
- include a compact processed-mail report
- later expand to weekly digests once users trust the product more

The digest should help users feel informed without needing to open Fynish constantly.

## Product Goal

The digest should answer:

- what did Fynish do for me since the last digest?
- how many items were processed?
- what kinds of actions were taken?
- did Fynish create any new rules?
- what messages were processed?

The overall tone should be:

- transparent
- useful
- confidence-building
- non-alarmist

## Recommendation Summary

Recommended rollout:

1. build a daily digest first
2. send it once per day in the user's configured timezone
3. include both summary metrics and a processed-mail list
4. keep weekly digest out of V1 implementation, but design data structures so it can be added cleanly later

## Why This Feature Fits Fynish

Fynish is now:

- classifying unread Inbox mail
- applying rules automatically
- logging processed actions
- allowing recovery when Fynish got something wrong

That means a digest can:

- reinforce trust
- make automation visible
- reduce the fear that mail is disappearing silently

This is especially important as Fynish moves from:

- active manual triage
to:
- always-on background assistance

## User Experience

### V1 user story

As a Fynish user, I receive a daily email digest that tells me:

- how many messages Fynish processed
- how many messages remain unprocessed
- how many new rules were created
- which messages were processed, with their selected action

So that I can quickly verify Fynish's behavior and decide whether I need to open the app.

## Digest Scope

### In scope for V1

- daily digest email
- per-user digest generation
- digest window based on the user's timezone
- summary counts
- processed-mail list
- configurable recipient email using existing notification settings
- scheduled server-side delivery
- Gmail API delivery from `digest.sender@example.com`, with sender OAuth stored outside monitored mail accounts

### Out of scope for V1

- weekly digest
- attachments
- HTML-rich report styling beyond a simple, readable email body
- per-account opt-out inside one user
- digest editing/templates in the UI
- in-app digest history
- per-message links directly into specific processed rows

## Digest Content

## 1. Header

Suggested subject line:

- `Fynish daily digest for May 17`

Alternative subject line if more action-oriented:

- `Fynish daily digest: 18 messages processed`

Recommended header fields in body:

- digest date
- user email
- digest window

## 2. Top Summary

Recommended metrics:

- total messages processed during the window
- count by action:
  - Keep
  - Bulk
  - Junk
  - Trash
  - Needs Review, if any are auto-logged into processed history
- count by action source:
  - Manual
  - Rule auto
  - Auto-clean
  - Legacy, for rows processed before source stamping existed
- number of new rules created during the window
- current queue count at send time
- top sender domains by processed-message count

Optional later metrics, not required for V1:

- count of recovered messages
- sender-domain trend comparison versus previous days

## 2a. Top Sender Domains

Include a compact domain summary so the user can quickly see repeated sources.

Recommended V1 content:

- top 10 sender domains by number of processed messages
- total processed count per domain
- count by action for each domain
- count by action source for each domain
- up to 3 sample subjects per domain

Suggested rendering:

- `wsj.com: 8 messages (Bulk 6, Keep 2; Auto-clean 2, Rule auto 4, Manual 2)`
- `Examples: Tokenmaxxing Maxes Out; The 10-Point`

Why this belongs in V1:

- it turns a long processed-message list into a useful pattern summary
- it helps the user spot domains that may deserve explicit rules
- it makes automation more transparent without requiring the user to open the app

This section should not create rules directly from email. Rule creation should stay inside Fynish where the user can inspect examples and context.

## 3. Processed Mail List

Include a processed-mail section similar in spirit to the current `Processed Mail` UI.

Recommended row fields:

- processed action
- action source
- sender
- sender domain
- subject
- processed timestamp
- account email

Optional row fields for later:

- whether the user overrode Fynish
- whether the action created a rule

### Recommended cap

For V1, cap the inline list at:

- first 50 processed items, newest first

Then add a footer line such as:

- `+ 12 more processed messages not shown`

This avoids turning the digest into an unbounded wall of text.

## 4. Footer

Footer should include:

- current queue count
- link back to Fynish
- short trust-building line such as:
  - `You can review or recover processed messages from the Processed Mail screen.`

## Delivery Rules

## Daily only for V1

V1 should send:

- at most one digest per user per day

The digest window should be:

- previous successful digest cutoff -> current digest cutoff

For a simpler first implementation, V1 may define the window as:

- local midnight to send time in the user's timezone

That is easier to reason about than rolling 24-hour windows.

## Send time

Recommended approach:

- add a dedicated digest time setting

If you want the smallest possible V1, reuse the existing notification framework and interpret:

- morning reminder time

as the digest send time.

Recommended long-term model:

- separate digest settings from reminder-preview settings

But for V1 implementation speed, reusing the current notification settings shape is acceptable.

## Empty-state sending rule

Recommended default:

- do not send the digest if all of these are true:
  - processed count is 0
  - new rule count is 0
  - current queue count is 0

This avoids low-value empty digests.

Possible softer rule:

- still send if queue count is nonzero, even when processed count is 0

That version is more informative and likely better for Fynish.

## Data Sources

## Primary tables

- `actions_log`
- `rules`
- `messages`
- `notification_settings_by_user`
- `users`
- `mail_accounts`

## Suggested data definitions

### Processed messages count

Count `actions_log` rows in the digest window, excluding:

- recovery rows that are hidden from the normal Processed Mail list

This keeps the digest aligned with what users mentally treat as "processed mail."

### New rules count

Count `rules.created_at` rows in the digest window for the current user.

### Queue count

Count current `messages` rows where:

- `reviewed = 0`

and scope them to the current user.

## Multi-user Requirements

The digest must be fully user-scoped.

Each digest may only include:

- that user's accounts
- that user's processed messages
- that user's rules
- that user's queue counts

No cross-user leakage is acceptable.

## Backend Design

## New service area

Recommended new backend service:

- `backend/app/services/digests.py`

Responsibilities:

- compute the digest window
- gather summary metrics
- gather processed-message rows
- render plain-text digest content
- later optionally render HTML content too

## Suggested functions

- `get_processed_digest_preview(user_id: int, as_of: datetime | None = None) -> dict`
- `render_processed_digest_text(payload: dict) -> str`
- `send_processed_digest(user_id: int) -> dict`

## Scheduling

Recommended implementation:

- new scheduled backend endpoint
- Cloud Scheduler hits it regularly
- backend decides which users are due

Suggested endpoint:

- `POST /api/tasks/send-digests`

Server behavior:

1. load users with digest notifications enabled
2. compute whether each user is due based on timezone and configured time
3. generate payload
4. skip users who are not due
5. skip users whose digest would be empty, according to the chosen rule
6. send outbound email
7. store send metadata so the same digest is not sent twice

## Persistence Needed

V1 likely needs a new table.

Recommended table:

- `digest_delivery_log`

Suggested columns:

- `id`
- `user_id`
- `digest_type` such as `daily_processed`
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

Why this matters:

- prevents duplicate sends
- gives auditability
- allows debugging
- gives a clean foundation for weekly digests later

## Email Delivery

Fynish does not yet appear to have production outbound email delivery wired in.

So V1 needs an email transport decision.

Reasonable options:

- SendGrid
- Mailgun
- Postmark
- Gmail SMTP with app password, though this is less attractive operationally

Recommended product choice:

- use a transactional provider such as Postmark or SendGrid

Recommended technical design:

- abstract sending behind a small mailer service:
  - `backend/app/services/mailer.py`

## Email Format

Recommended V1:

- plain text first

Why:

- easiest to implement
- aligns with current reminder preview generation
- low risk
- easy to inspect and test

Optional V1.5:

- add a simple HTML version with a summary card and table-like processed list

## UI / Settings

## Existing settings reuse

Current notification settings already store:

- enabled
- recipient email
- timezone
- morning enabled/time
- evening enabled/time
- send only if queue nonempty

Recommended V1 interpretation:

- add digest-specific settings instead of overloading everything permanently

### Preferred eventual settings

- `digest_enabled`
- `digest_frequency` with `daily` for now
- `digest_time`
- `digest_recipient_email`
- `digest_only_if_activity`

### Fast-path V1 option

If speed matters more than schema cleanliness:

- reuse existing notification settings for recipient and timezone
- add only the minimum digest fields needed

Recommended minimum additions:

- `digest_enabled`
- `digest_time`

## Preview

Recommended V1.5:

- add a digest preview card in `Settings`

This would mirror the current reminder preview pattern and help users trust the feature before enabling it.

Given the new sender-domain summary, the preview card should be promoted into the V1 implementation if practical. It gives the user a quick way to verify that domain rollups are understandable before email delivery is enabled.

## Rollout Plan

## Phase 1: Spec and data model

- define digest rules
- add delivery log table
- decide email provider
- decide settings shape

## Phase 2: Backend preview generation

- build digest payload service
- build plain-text rendering
- expose an internal preview endpoint

## Phase 3: Delivery plumbing

- integrate mail transport
- add scheduled task endpoint
- add due-user selection logic
- add duplicate-send protection

## Phase 4: Settings UI

- expose digest controls in the existing Settings screen
- add preview if helpful

## Phase 5: Live daily rollout

- enable for one trusted user
- watch content quality and timing
- then expand to other users

## Weekly Digest Later

Weekly digest should be treated as a later feature, not a setting added immediately.

Recommended later additions:

- `digest_frequency = daily | weekly`
- separate weekly summary metrics
- broader trend statistics:
  - total processed this week
  - top domains processed
  - top actions
  - rules created this week
  - recoveries this week

## Open Product Questions

These are the decisions I would want from you before implementation:

1. Should the digest include only messages processed automatically by Fynish, or both automatic and manual processed actions?

Recommended:

- include both, because the Processed Mail screen itself represents both.

2. Should recovered messages appear in the digest metrics?

Recommended:

- no, not in the main processed count for V1.

3. Should the processed-mail list include every processed item or be capped?

Recommended:

- cap at 50 inline rows.

4. If nothing was processed that day but the queue still has items, should Fynish still send the digest?

Recommended:

- yes, because that is still useful information.

5. Should digest recipient default to the signed-in Fynish user email, or the existing notification recipient field?

Recommended:

- use `notification recipient` if set, otherwise fall back to signed-in user email.

6. Should the digest be one combined per-user digest across all connected accounts, or one digest per connected account?

Recommended:

- one combined digest per user.

7. Should the digest be plain text only at first, or should we build HTML immediately?

Recommended:

- plain text first.

## Recommended Final Product Definition

V1 digest should be:

- one daily per-user email
- sent in the user's timezone
- summarizing processed messages across all of that user's connected accounts
- including:
  - processed count
  - counts by action
  - counts by action source
  - top sender domains
  - new rules created
  - current queue count
  - capped processed-mail list
- delivered only when there was either:
  - processed activity, or
  - nonzero queue state worth surfacing

That is the smallest version that still feels genuinely useful and trust-building.

## Future Enhancement: High-Activity Digest Trigger

One idea worth preserving for later is:

- send an extra digest when processed activity gets unusually high

Recommended future interpretation:

- keep the normal daily digest as the primary delivery model
- optionally add a second "high activity" digest if processed volume exceeds a threshold such as 50 messages before the normal daily send

Why this should stay out of V1:

- threshold-triggered timing is less predictable for users
- it adds more delivery-state complexity
- the daily digest is the cleaner trust-building baseline

So for now:

- V1 stays daily
- processed-mail list cap becomes 50
- threshold-triggered sending remains a later enhancement
