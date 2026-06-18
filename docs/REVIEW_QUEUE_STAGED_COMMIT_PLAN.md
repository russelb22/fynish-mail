# Review Queue Staged Commit Plan

Implementation guide: `docs/REVIEW_QUEUE_STAGED_COMMIT_IMPLEMENTATION_SPEC.md`.

Status: proceed with client-side staged review plus backend batch commit. The implementation spec is the controlling guide for slice boundaries, validation gates, and deployment cadence.

## Purpose

Make the Review Queue feel faster and more resilient by letting the browser hold a local working set of queue messages while the user reviews them.

Instead of sending every Keep, Bulk, Junk, Trash, or rule-teaching click immediately to the backend, Fynish can stage the user's decisions in the browser and apply them in a single batch when the user clicks `Commit Changes`.

This is a standard web application pattern often described as:

- client-side state cache
- optimistic UI
- staged changes
- unit of work
- batch commit
- write-behind workflow

For Fynish, the goal is not offline email processing. The goal is a faster review experience with clearer recovery when Gmail, credentials, or the database are slow or temporarily unavailable.

## Current Model

The current Review Queue behavior is intentionally simple:

1. The browser loads the review queue from the Fynish backend.
2. The user clicks an action on one message.
3. The frontend calls the backend immediately.
4. The backend updates Fynish's database and, when needed, Gmail.
5. The frontend updates or refreshes the queue.

This keeps server state authoritative at all times, but it means each user decision can feel dependent on a full backend and Gmail round trip.

## Proposed Model

The browser should load the queue once, keep a local copy of message metadata, and track staged decisions separately from committed server state.

The user can move quickly through messages. Each click updates the local working set immediately and records a pending action. Nothing is written to Gmail or the database until the user clicks `Commit Changes`.

At commit time, the frontend sends one batch request to the backend. The backend validates ownership and message state, applies database and Gmail changes, and returns per-message results.

## Important Boundary

The browser must not talk directly to Gmail.

The browser may cache only safe message metadata and previews already returned by Fynish's backend. Gmail credentials, refresh tokens, OpenAI keys, and provider-specific write access must remain server-side.

## UX Direction

Preserve the current bootstrap-first Review Queue layout:

- sender and subject
- collapsed preview with inline expansion
- recommendation
- reasons
- `This Message`
- `Teach Fynish`

Add a visible staged-work toolbar when any local changes exist:

`5 changes staged | Undo Last | Discard | Commit Changes`

Recommended behavior:

- Clicking `Keep`, `Bulk`, `Junk`, or `Trash` stages a one-message action.
- Clicking `Always Keep Domain` or `Always Junk Domain` stages both a rule creation and an action for the current message.
- Staged messages should visually leave the active queue or move into a compact `Staged` section.
- The user should be able to undo the last staged action.
- The user should be able to discard all staged actions.
- The user should clearly see that staged changes are not yet committed.
- After commit, successful messages disappear from the active queue.
- Failed messages remain visible with a specific error.

## Frontend Implementation

Add a local staged action model in the Review Queue component.

Example shape:

```ts
type StagedQueueAction = {
  messageId: number
  accountEmail: string
  action: 'keep' | 'bulk' | 'junk' | 'trash'
  rule?: {
    scope: 'domain'
    action: 'keep' | 'junk'
    pattern: string
  }
  stagedAt: string
  originalVersion?: string
}
```

Suggested frontend state:

```ts
const [queue, setQueue] = useState<ReviewAccount[]>([])
const [stagedActions, setStagedActions] = useState<Record<number, StagedQueueAction>>({})
const [commitBusy, setCommitBusy] = useState(false)
const [commitErrors, setCommitErrors] = useState<Record<number, string>>({})
```

On action click:

1. Build a `StagedQueueAction`.
2. Add it to `stagedActions`.
3. Update the visible queue immediately.
4. Show a staged notice.
5. Do not call Gmail or the backend action endpoint yet.

Derived UI should compute:

- active messages: queue messages without a staged action
- staged messages: queue messages with a staged action
- staged count
- whether commit/discard controls are visible

## Backend Implementation

Add a batch commit endpoint.

Candidate route:

`POST /api/review-queue/staged-actions/commit`

Candidate request:

```json
{
  "idempotency_key": "uuid-from-browser",
  "actions": [
    {
      "message_id": 123,
      "action": "junk",
      "expected_version": "2026-06-03T08:15:00Z"
    },
    {
      "message_id": 124,
      "action": "keep",
      "rule": {
        "scope": "domain",
        "action": "keep",
        "pattern": "example.com"
      },
      "expected_version": "2026-06-03T08:16:00Z"
    }
  ]
}
```

Candidate response:

```json
{
  "committed": 2,
  "failed": 1,
  "results": [
    {
      "message_id": 123,
      "status": "committed"
    },
    {
      "message_id": 124,
      "status": "failed",
      "error_code": "gmail_reconnect_required",
      "message": "Stored Gmail credentials were expired or revoked. Reconnect the account."
    }
  ]
}
```

Backend responsibilities:

1. Require the current authenticated user.
2. Verify each message belongs to the current user.
3. Verify each monitored account is enabled and actionable.
4. Check whether each message is still pending and not already processed.
5. Optionally compare `expected_version` to detect stale browser state.
6. Create any requested rules.
7. Apply message actions to the Fynish database.
8. Apply Gmail label/archive/trash changes server-side.
9. Return per-message success or failure.
10. Log a structured summary of the batch.

## Transaction Strategy

The safest implementation is partial success with per-message results.

Fynish should not fail the whole batch because one message was stale or one account needs reconnecting. Instead:

- commit valid messages
- skip failed messages
- return clear errors for failed messages
- keep failed messages visible in the frontend

For rule creation plus current-message action, treat that pair as one unit:

- if the rule cannot be created, do not apply the message action as a rule-backed action
- if the rule is created but Gmail action fails, return a warning-style failure that makes the final state clear

## Error Handling

This feature should use the error handling strategy already described in `docs/ERROR_HANDLING_STRATEGY.md`.

Expected errors:

- Gmail credentials expired or revoked
- Gmail account missing required scope
- Gmail API timeout or rate limit
- message already processed in another tab
- account disabled while the page was open
- database save failure
- unsupported staged action
- validation error in staged rule pattern

User-facing messages should be actionable:

- `Stored Gmail credentials were expired or revoked. Reconnect the account.`
- `This message was already processed. The queue has been refreshed.`
- `Fynish could not save this change. Please try again.`

Technical details should go to logs, not the UI.

## Data Freshness and Conflict Handling

Add or reuse a per-message freshness token.

Good candidates:

- `updated_at`
- `processed_at`
- a numeric row version

The frontend should include the expected value when committing. If the backend sees that a message changed after the queue was loaded, it should return a stale-state result for that message.

This avoids silently overwriting work from another browser tab, a background sync, or a previous commit.

## Idempotency

The commit request should include an `idempotency_key`.

This protects against duplicate submits if:

- the user double-clicks `Commit Changes`
- the browser retries a request
- the network drops after the backend commits but before the frontend receives the response

Initial implementation can log and accept the key without a full idempotency table. A later implementation can persist commit attempts if duplicate handling becomes important.

## Performance Benefits

Expected improvements:

- individual review clicks feel instant
- fewer round trips during review
- fewer full queue refreshes
- Gmail latency is paid once per batch instead of once per decision
- users can continue making decisions even if the previous click would have been slow

This should help most when a user is quickly processing a large Review Queue.

## Tradeoffs

This adds complexity because the frontend now has two states:

- server-loaded queue state
- local staged state

The UI must make staged state obvious. Otherwise a user could believe a message has been processed when it has only been staged.

The backend also needs per-message batch result reporting rather than a single success/failure response.

## Suggested Implementation Slices

The detailed implementation spec supersedes the original slice order below. The first deploy batch should now be:

1. backend commit API for `This Message` actions
2. frontend staged Review Queue for `This Message` actions
3. local validation
4. deploy the validated pair to the VM

The older slice outline is retained as historical context.

### Slice 1: Frontend-only staging prototype

- Add local staged state.
- Stage `This Message` actions without calling the backend.
- Add staged toolbar with count, undo, discard, and disabled commit button.
- Keep existing immediate backend behavior behind a temporary internal toggle if needed.

### Slice 2: Batch commit endpoint

- Add backend request/response schemas.
- Implement batch validation.
- Reuse existing single-message action services where possible.
- Return per-message results.
- Add structured logging.

### Slice 3: Wire frontend commit

- Enable `Commit Changes`.
- Send staged actions to the new endpoint.
- Reconcile per-message results.
- Show specific errors for failures.
- Refresh queue after successful commit.

### Slice 4: Rule-teaching support

- Stage `Always Keep Domain` and `Always Junk Domain`.
- Commit rule creation plus message action as a unit.
- Show rule-specific success/failure copy.

### Slice 5: Hardening

- Add stale-state/version checks.
- Add idempotency key handling.
- Add tests for partial failure.
- Add tests for credential failure.
- Add tests for rule creation plus action.

## Acceptance Criteria

- A user can process multiple queue messages without waiting on a backend call after each click.
- The UI clearly shows how many changes are staged.
- The user can undo the last staged action.
- The user can discard all staged actions.
- No Gmail or database changes occur before `Commit Changes`.
- On commit, successful messages are processed and removed from the active queue.
- Failed messages remain visible with actionable error messages.
- Gmail credentials remain server-side.
- The implementation preserves the current Review Queue layout and one-click decision model.

## Open Questions

- Should staged messages disappear from the active queue or move into a visible `Staged` section?
- Should Fynish auto-commit after a threshold, such as 25 staged messages, or require explicit commit every time?
- Should the Review Queue support keyboard shortcuts once staging exists?
- Should preview body text be prefetched for every queued message or loaded only when preview is expanded?
- Should commit apply Gmail changes sequentially per account or in parallel with rate-limit controls?

## Recommendation

Proceed with explicit staging and manual commit.

Do not make this a hidden write-behind system. The user should always know whether decisions are staged or committed. This gives Fynish the speed benefits of a client-side working set while keeping Gmail and database writes deliberate, auditable, and recoverable.
