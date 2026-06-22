# Spam Rescue Implementation Spec

Status: drafted for product and technical review.

## Purpose

Add a conservative Spam Rescue workflow that helps users find Gmail Spam messages that may not belong in Spam.

The goal is not to manage the Spam folder broadly. The goal is to surface likely false positives with clear reasons, then let the user explicitly restore the message to Inbox or leave it in Spam.

Spam Rescue should reinforce Fynish's existing product posture:

- explainable recommendations
- user-approved actions
- reversible or low-risk behavior
- no destructive Gmail operations
- no opaque automation for trust-sensitive mail

## Product Decision

Spam Rescue should be a separate review lane, not an expansion of the normal Inbox Review Queue.

The current Review Queue is optimized for unread Inbox triage: Fynish reviews messages that Gmail already left visible, then helps the user keep, bulk, junk, or soft-trash them.

Spam Rescue is the opposite workflow: Gmail has already hidden the message, and Fynish is looking for reasons the message might deserve attention.

For V1:

- keep the feature behind a feature flag
- sync recent unread Spam only
- do not auto-restore messages from Spam
- do not auto-create rescue rules
- do not mix Spam Rescue candidates into the normal Inbox queue by default
- do not expose broad Spam cleanup operations
- do not permanently delete anything

## Current Baseline

Current Fynish behavior is intentionally narrow:

- syncs unread Gmail Inbox messages
- imports message metadata and preview text
- classifies each message as Keep, Bulk, Junk, Trash, or Needs Review
- applies explicit rules during sync when appropriate
- presents unreviewed messages in the Review Queue
- stages user actions locally before commit
- preserves unread state for Gmail label operations
- avoids Gmail Trash and permanent delete operations

Relevant current areas:

- `backend/app/services/gmail_readonly.py`
- `backend/app/services/review_queue.py`
- `backend/app/services/classifier.py`
- `backend/app/services/gmail_write_planner.py`
- `backend/app/services/gmail_write_executor.py`
- `backend/app/services/staged_commit.py`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/types.ts`

## Target UX

Add a distinct Spam Rescue surface, probably as a top-level tab or secondary queue view.

Suggested user-facing model:

- The main Review Queue remains for unread Inbox triage.
- Spam Rescue shows recent unread Spam messages that have rescue signals.
- Each row explains why Fynish thinks the message might not belong in Spam.
- The user can explicitly choose:
  - `Restore to Inbox`
  - `Leave in Spam`

Suggested row content:

- receiving account
- sender
- sender domain
- subject
- received time
- attachment indicator when present
- preview/snippet
- rescue confidence or priority
- rescue reasons
- protection reasons, if applicable
- current Gmail source marker, such as `Spam`

Suggested empty state:

> No likely Spam false positives found.

Avoid implying that every Spam message is safe. Spam Rescue should feel like a cautious watchlist, not a general Spam reader.

## V1 Decisions

Recommended V1 boundaries:

- keep Spam Rescue behind a feature flag
- run Spam Rescue as a separate sync step, even if it is triggered by the same scheduler as Inbox sync
- use a config-level lookback window, not a user-facing control
- start with recent unread Spam messages, such as the last 7 to 14 days
- cap fetched Spam messages per account
- show only messages with positive rescue signals
- use Always Keep rules as strong surfacing signals, but never as automatic restore instructions
- preserve unread state on restore
- do not add a `Fynish/Rescued` Gmail label in V1
- record local action history for both `Restore to Inbox` and `Leave in Spam`
- count `Restore to Inbox` as positive sender/domain history only after the user explicitly restores
- track `Leave in Spam` separately from normal Junk/Trash history, or treat it as a weak negative signal
- support mock data for local development and UI validation

## Non-Goals For V1

Do not include these in the first implementation:

- automatic restore from Spam
- permanent delete
- Gmail Trash operations
- training Gmail's spam model directly
- broad Spam folder cleanup
- bulk restore
- user-facing Spam Rescue schedule controls
- user-facing Spam Rescue lookback controls
- rule auto-apply inside Spam
- AI-generated safety judgments without deterministic visible reasons
- reading full message bodies beyond the existing preview-oriented approach

## Rescue Candidate Definition

Spam Rescue should only surface messages that have at least one meaningful reason to inspect.

Possible rescue signals:

- sender previously kept by this user
- sender domain previously kept by this user
- explicit Always Keep sender/domain/list rule matched
- protected keywords detected, such as invoice, legal, healthcare, tax, school, job, account recovery, payroll, benefits, utilities, or government
- personal or conversational wording detected
- known account or sender pattern from prior history
- message appears transactional rather than promotional
- sender is from a domain the user has historically interacted with positively

Possible suppression signals:

- explicit Junk, Bulk, or Trash rule matched
- suspicious sender or reply-to mismatch with no protective signals
- spam-like urgency wording with no positive history
- message is too old for the configured rescue window
- message already reviewed in Spam Rescue

The classifier should produce visible rescue reasons instead of relying on a hidden score alone.

## Recommended Data Model

Spam Rescue needs source context. The current system mostly assumes visible queue messages came from unread Inbox.

Recommended V1 approach:

Add source/provenance fields to `messages` if they do not already exist in the target branch:

- `source_label TEXT NOT NULL DEFAULT 'inbox'`
- `review_surface TEXT NOT NULL DEFAULT 'review_queue'`

Suggested values:

- `source_label`: `inbox`, `spam`
- `review_surface`: `review_queue`, `spam_rescue`

Alternative:

- add only `source_label`
- infer the surface from `source_label = 'spam'`

The explicit `review_surface` is more verbose but safer. It avoids coupling future surfaces to Gmail labels and makes frontend filtering clearer.

Spam Rescue also likely needs a way to distinguish normal classification from rescue classification:

- `current_category = 'spam_rescue'` or `current_category = 'needs_review'` with `review_surface = 'spam_rescue'`
- `classification_results.reasons_json` stores rescue reasons
- `messages.queue_source` can remain available for provenance such as `spam_rescue_classifier` or `rule_keep`

Recommendation:

- keep the existing category model intact where possible
- use `review_surface = 'spam_rescue'` for routing
- add a small rescue-specific response shape rather than forcing Spam Rescue into normal category semantics

## Gmail Fetch Behavior

Add a Gmail fetch path for Spam candidates.

Suggested Gmail query:

- label IDs: `SPAM` and `UNREAD`
- cap by configured max results
- optionally use a query window such as `newer_than:14d`

Implementation shape:

- add `list_unread_spam_message_ids(...)`
- add `fetch_unread_spam_messages(...)`
- reuse existing `fetch_message(...)` and message parsing helpers
- include Gmail labels in `provider_labels_json`
- mark imported messages with `source_label = 'spam'`
- route them to the Spam Rescue surface only if rescue candidate logic passes

Reconciliation:

- if a message leaves Gmail Spam outside Fynish, remove it from active Spam Rescue visibility on the next refresh
- if a message is restored to Inbox outside Fynish, it should leave Spam Rescue
- if it later appears in unread Inbox, the normal Inbox sync can decide whether it belongs in the Review Queue

## Rescue Classification

Do not reuse the normal Inbox cleanup classifier as-is.

Recommended implementation:

- create `classify_spam_rescue_candidate(...)`
- share helper functions such as `extract_email`, `extract_domain`, keyword detection, rule matching, and history counters
- return a rescue-oriented result:

```python
@dataclass
class SpamRescueResult:
    should_surface: bool
    confidence: float
    reasons: list[str]
    protection_reasons: list[str]
    matched_rule_ids: list[int]
```

Decision rule:

- surface only when `should_surface` is true
- require at least one visible reason
- prefer false negatives over false positives in V1

## Actions

Spam Rescue should have two V1 actions.

### Restore to Inbox

User meaning:

- this message probably should not be in Spam
- move it back to Gmail Inbox
- preserve unread state
- mark the Spam Rescue item reviewed locally
- log the action

Gmail label plan:

- add `INBOX`
- remove `SPAM`
- do not remove `UNREAD`
- do not add a `Fynish/Rescued` label in V1
- do not use Gmail Trash
- do not delete permanently

Suggested action value:

- `restore_to_inbox`

### Leave in Spam

User meaning:

- Fynish surfaced this message, but the user agrees it can stay in Spam
- mark it reviewed locally
- do not mutate Gmail
- log the decision

Suggested action value:

- `leave_in_spam`

This action should not train Gmail, delete the message, or add Fynish cleanup labels in V1.

## Backend API

Possible V1 endpoints:

- `POST /api/spam-rescue/sync`
- `GET /api/spam-rescue`
- `POST /api/spam-rescue/staged-actions/commit`

Alternative:

- reuse the existing staged commit endpoint with a new action type and source validation

Recommendation:

- start with Spam Rescue-specific endpoints unless the existing staged commit implementation already generalizes cleanly
- keep the response shape close to Review Queue patterns so frontend code can share components later

Example queue response item:

```json
{
  "id": 123,
  "account_email": "user@example.com",
  "sender": "Example Billing <billing@example.com>",
  "sender_domain": "example.com",
  "subject": "Invoice for June",
  "received_at": "2026-06-21T15:30:00+00:00",
  "snippet": "Your invoice is ready...",
  "body_preview": "Your invoice is ready...",
  "has_attachments": false,
  "source_label": "spam",
  "review_surface": "spam_rescue",
  "confidence": 0.86,
  "rescue_reasons": ["Protected keyword detected: invoice"],
  "protection_reasons": ["Protected keyword detected: invoice"],
  "state_version": "2026-06-21T15:31:00+00:00"
}
```

## Safety Rules

Spam Rescue commit validation should require:

- current user owns the mail account
- message belongs to the current user
- message is still on the Spam Rescue surface
- message source is still Spam, or the result is returned as stale
- expected state version matches
- action is allowed for this source
- Gmail modify scope exists for `restore_to_inbox`

Planner safety notes should explicitly state:

- UNREAD label will be preserved
- Gmail Trash will not be used
- permanent delete will not be used
- restore removes SPAM and adds INBOX

## Frontend Behavior

Recommended V1 frontend:

- add a Spam Rescue tab or route near Review Queue
- show account-grouped rescue candidates
- reuse existing message row primitives where practical
- use distinct action labels, not normal Keep/Bulk/Junk/Trash labels
- stage changes before commit if this fits the current app pattern
- keep staged Spam Rescue changes visually separate from Inbox staged changes

Suggested controls:

- `Restore to Inbox`
- `Leave in Spam`
- `Undo Last`
- `Discard`
- `Commit Changes`
- refresh/sync control

Suggested visual tone:

- cautious, calm, and sparse
- avoid red-heavy styling that makes every candidate feel dangerous
- make reasons prominent enough that the user understands why the row appeared

## Mock Data

Add mock Spam messages for local development.

Suggested fixture groups:

- obvious false positive invoice
- job or recruiting message
- school or healthcare message
- sender previously kept
- Always Keep domain match
- obvious spam that should not surface
- promotional message with no rescue signal
- suspicious reply-to mismatch with protected keyword

Mock mode should support:

- Spam Rescue sync
- queue rendering
- restore planning
- leave-in-spam logging
- processed history visibility

## Testing Plan

Backend tests:

- Spam fetch uses `SPAM` and `UNREAD`
- Spam messages are stored with Spam source context
- normal Inbox queue is unchanged
- rescue classifier surfaces protected/known sender cases
- rescue classifier suppresses obvious spam with no positive signals
- `restore_to_inbox` plans `add=['INBOX']`, `remove=['SPAM']`
- `restore_to_inbox` preserves `UNREAD`
- `restore_to_inbox` does not add extra Gmail labels in V1
- `leave_in_spam` does not mutate Gmail labels
- stale Spam Rescue messages fail safely
- user/account scoping is enforced

Frontend tests or smoke checks:

- Spam Rescue view renders empty state
- candidates render with rescue reasons
- actions stage correctly
- commit success removes candidates
- commit failure restores candidate with actionable error
- normal Review Queue still works

Manual validation:

- run backend tests
- run frontend build
- validate mock Spam Rescue flow
- validate real Gmail restore only with a test account

## Implementation Slices

### Slice 1: Spec and Mock Harness

- add this spec
- add mock Spam candidate fixtures
- add initial backend tests for rescue classifier behavior

### Slice 2: Gmail Spam Fetch

- add Spam message listing and fetch helpers
- add sync path for unread Spam candidates
- store source context
- reconcile missing Spam messages

### Slice 3: Rescue Classifier

- add rescue-specific classifier result
- implement positive/suppression signals
- persist rescue reasons
- test false-positive and suppression examples

### Slice 4: Action Planning and Commit

- add `restore_to_inbox` action planning
- add `leave_in_spam` local handling
- add safety validation
- add action logging
- add stale-state handling

### Slice 5: API and Frontend View

- add Spam Rescue API endpoints
- add frontend API types
- add Spam Rescue tab/view
- add staged action UI
- add empty, loading, error, and success states

### Slice 6: Polish and Validation

- refine copy
- add account grouping
- add processed history labels
- run regression tests
- prepare PR notes and screenshots

## Remaining Open Questions

- What should the feature flag be named?
- Should the default config lookback window be 7 days or 14 days?
- Should `Leave in Spam` appear in Processed Mail with a dedicated label such as `Left in Spam`?
- Should `Restore to Inbox` appear in Processed Mail with a dedicated label such as `Rescued from Spam`?
- Should Spam Rescue candidates be included in any summary counts outside the Spam Rescue view?
- Should the first code PR implement only mock/test behavior before any real Gmail Spam sync?

## Suggested PR Description

This change introduces the first Spam Rescue implementation spec: a conservative review lane for recent unread Gmail Spam messages that may be false positives.

The proposed feature intentionally does not auto-restore messages. It surfaces only messages with visible rescue reasons and lets the user explicitly choose whether to restore the message to Inbox or leave it in Spam.

The V1 safety model keeps Spam Rescue separate from the normal Inbox Review Queue, preserves unread state, avoids Gmail Trash/permanent delete, and uses source-aware validation so Inbox cleanup actions cannot accidentally run against Spam messages.
