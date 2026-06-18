# Fynish Functional Guide

## Purpose

Fynish is a Gmail triage tool for reviewing unread Inbox messages, applying consistent actions, and gradually replacing repeated manual decisions with explicit rules.

The current product is intentionally conservative:

- it focuses on unread Inbox mail only
- it avoids destructive Gmail behavior
- it keeps actions reversible through the app's local history
- it favors explainable rules and visible message recommendations over opaque automation

## Current Runtime Modes

Fynish currently runs in three practical modes:

### 1. Local development mode

- frontend on local Vite or local Node frontend
- backend on local FastAPI
- database typically SQLite or local Postgres for development

### 2. Cloud Run / Cloud SQL hosted mode

- browser-accessible hosted frontend
- hosted backend
- managed PostgreSQL
- used as the earlier private hosted environment

### 3. Single-VM hosted mode

- public HTTPS frontend on one `e2-small` VM
- backend and frontend on the same VM
- local PostgreSQL on the VM
- local scheduled sync on the VM

This single-VM mode is now the lower-cost preferred path for active testing.

## Users and Access

Fynish is now multi-user aware.

Each signed-in user should only see:

- their own connected mail accounts
- their own review queue
- their own processed-mail history
- their own rules
- their own settings

Access currently depends on:

- Google sign-in
- explicit allowlisting for frontend access

## Account Model

Each Fynish user can connect one or more mail accounts.

Current account types:

- `gmail_readonly`
  - used for real Gmail accounts
  - despite the legacy provider name, the normal user-facing connection path is modify-capable
- `mock_gmail`
  - used only for development/testing harness behavior

For each connected account, the UI shows:

- account address
- provider
- enabled/disabled state
- access level
- last sync time

Access levels currently mean:

- `Modify-capable`
  - Fynish can import messages and execute live Gmail label changes
  - this is the normal current user-facing Gmail path

## Sync Model

Fynish syncs unread Inbox mail only.

The sync path currently:

- imports unread messages that are still in Gmail Inbox
- stores message metadata and preview text
- classifies each message
- applies matching explicit rules during sync when appropriate
- reconciles the local queue against Gmail's current unread Inbox state

Reconciliation means:

- if a message leaves unread Inbox outside Fynish, it disappears from the queue on a later refresh
- if it later returns to unread Inbox, it can reappear in the queue

Scheduled sync currently runs:

- every 10 minutes in the active hosted environments

## Review Queue

The Review Queue is the main operational view.

Current queue behavior:

- grouped by connected account
- within each account, grouped by recommended category
- displays unread queue items only
- no multi-select checkboxes
- one-message-at-a-time handling with staged commit for `This Message` actions
- `This Message` clicks leave the active queue immediately and wait for `Commit Changes`
- `Teach Fynish` rule buttons stage rule creation plus source-message action and wait for `Commit Changes`

Each message row currently shows:

- suggested category pill
- confidence percentage
- sender
- sender domain
- subject
- received time
- attachment indicator when present
- inline preview
- classification reasons
- optional protection reasons
- per-message action buttons

### Current category model

The current recommendation categories are:

- `Keep`
- `Bulk`
- `Junk`
- `Trash`
- `Review`

Their intended meanings are:

- `Keep`
  - should remain visible / worthwhile
- `Bulk`
  - legitimate mass mail, but low priority
- `Junk`
  - unwanted sender/domain pattern, often rule-worthy
- `Trash`
  - discard this specific message
- `Review`
  - uncertain, should remain visible for human judgment

### Current queue color system

The queue now uses:

- a colored category pill
- a lightly tinted message card

Current visual mapping:

- `Keep`
  - green family
- `Bulk`
  - gold family
- `Junk`
  - ochre / orange-brown family
- `Trash`
  - muted rose / red family
- `Review`
  - cool blue / slate family

## Message Actions

Fynish currently supports these message actions:

- `Keep`
- `Bulk Mail`
- `Junk Review`
- `Trash`

Current semantics:

`This Message` and queue `Teach Fynish` actions are staged locally first. Gmail and Fynish database changes happen when the user clicks `Commit Changes`. Successful commits remove messages from the queue; failed commits restore messages with actionable error text. Rule-teaching staged actions create or reuse the rule, reclassify the remaining queue, and apply the source-message action during commit.

The staged review panel groups pending changes by receiving account, and the masthead summary separates active unread queue count from staged-but-not-yet-committed count.

Keyboard shortcuts are available on the Review Queue when focus is not in a text field or select control: `1` Keep, `2` Bulk, `3` Junk, `4` Trash, `u` undo last staged action, and `c` commit staged changes.

Each staged commit includes the queue item's state version. If a message changed or the version is missing, Fynish returns that item as stale instead of committing it. Commit requests also use a persisted idempotency key, so retrying the same unchanged commit request does not duplicate action logs or rule side effects.

Fynish validates all items in a staged batch before executing any of them, so a rule-teaching action that reclassifies the queue does not make later items in the same commit batch look stale.

Refreshing mail accounts clears stale per-message commit warnings and reloads the latest queue state. Identical Gmail refreshes preserve a queued message's state version, so routine sync activity does not create a false stale warning when the message payload and classification are unchanged.

When the user scrolls down in the Review Queue, a small floating up-arrow button appears near the bottom center of the viewport. It returns the page to the masthead/top navigation without changing staged actions or backend state.

### Keep

- marks the message reviewed in Fynish
- removes it from the visible queue
- does not change Gmail labels

### Bulk Mail

- applies the Fynish bulk label strategy
- removes the message from Inbox
- preserves unread state
- can be applied manually or by rule

### Junk Review

- applies the Fynish junk label strategy
- removes the message from Inbox
- preserves unread state
- is the most rule-oriented action

### Trash

- applies the Fynish trash label strategy
- removes the message from Inbox
- preserves unread state
- is not Gmail Trash / not permanent delete

Important safety note:

- `Trash` in Fynish is still a soft-removal workflow, not actual Gmail trashing or deletion

## Live Gmail Writes

Modify-capable Gmail accounts can use live Gmail writes.

Live Gmail writes are gated by:

- the account having Gmail modify scope

Current live-write behavior:

- modify-capable Gmail accounts update both Fynish and Gmail
- there is no separate per-account live-mode toggle in the normal UI

## Rules

Fynish rules exist to turn repeated decisions into repeatable behavior.

Current rule types include:

- sender
- domain
- subject contains
- list-id

Rules can be created:

- from the queue
- from the Rules page

Current rule behavior:

- matching rules can auto-apply during sync
- matching messages usually skip the visible queue unless the outcome is `Needs Review`
- identical rules are reused or re-enabled instead of duplicated

When the user scrolls down in Rules, the same floating up-arrow button returns the page to the masthead/top navigation.

### Domain rule behavior

Domain rules are exact matches.

Example:

- a rule for `nextdoor.com` matches:
  - `foo@example.com`
- it does not match:
  - `foo@mail.example.com`

This is deliberate so users can control subdomains separately.

## Processed Mail

Processed Mail is the audit/history view.

Current behavior:

- merged chronological list across visible accounts
- auto-cleaned messages from the last two days sorted above other processed messages
- older auto-cleaned messages return to normal newest-first chronology
- one-row summary view
- expandable inline detail
- `Recover` available for eligible items

Current processed-row labels intentionally distinguish rule-like vs one-off outcomes:

- `Junk Rule`
- `Bulk Rule`
- `Trash Msg`
- `Keep Msg`

Processed Mail uses the same category palette family as the queue, but in a slightly calmer historical presentation.

When the user scrolls down in Processed Mail, the same floating up-arrow button returns the page to the masthead/top navigation.

## Recover

Processed messages can be recovered through the Processed Mail view.

Recover currently exists to support:

- undoing a Fynish action
- re-surfacing a message into the queue workflow

The goal is to keep the system reversible and safe while trust is still being built.

## Accounts View

The Accounts view is the control surface for connected mail accounts.

Current functions:

- connect Gmail with modify scope
- review access level
- review last sync time
- disable an account
- re-enable a disabled account

## Settings View

The Settings view currently contains:

- a compact summary of active current behavior
- digest sender connection controls
- daily digest scheduling controls
- per-user AI digest summary toggle
- AI digest attention notes
- temporary development/testing controls when running locally

AI digest attention notes are user-scoped notes for sender domains such as `example.net` or `truecoach.co`.

They guide only the AI-generated daily digest briefing. They do not change Gmail actions, Review Queue classification, rules, auto-cleaning, or processed-mail history.

Reminder controls and digest previews are no longer part of the normal current product surface.

## Mock Accounts

Mock accounts still exist as a development harness.

They are useful for:

- local testing
- UI density checks
- safe flow testing without touching real Gmail

They are not part of the intended normal user-facing experience.

## Current Limitations

Fynish is still intentionally narrow.

Current functional limitations include:

- Gmail-focused only
- unread Inbox-focused only
- no permanent delete
- no true Gmail Trash action
- no broad provider support yet
- no full public/open signup
- digest delivery currently depends on the configured Gmail digest sender and per-user schedule settings

## Recommended Functional Reading Order

If you want the current product behavior quickly, read in this order:

1. this functional guide
2. [docs/ACCOUNT_AUTHORIZATION_USE_CASES.md](docs/ACCOUNT_AUTHORIZATION_USE_CASES.md)
3. [docs/testing/TESTING_STRATEGY.md](docs/testing/TESTING_STRATEGY.md)
