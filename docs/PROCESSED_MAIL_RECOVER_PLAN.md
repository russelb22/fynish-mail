# Processed Mail Recover Plan

## Current status

This feature is now implemented and validated in the hosted stack.

Current live behavior:
- `Recover` is available inside the expanded panel for each processed message row
- recovery restores Gmail Inbox-oriented state when needed
- recovered messages return to `needs_review`
- recovered messages are pinned in the Fynish queue with a `recovery_pending` flag until they are explicitly reprocessed
- rules remain unchanged
- recovery audit events are preserved but hidden from the normal `Processed Mail` list

Hosted validation completed:
- `Keep` message recovered successfully
- `Trash` message recovered successfully
- `Junk` message recovered successfully
- all three were reprocessed successfully afterward

## Summary

Add a `Recover` action to the `Processed Mail` screen so a user can restore a previously processed message back into the active review flow.

For V1, `Recover` should be a message-level undo only. It should:
- restore the message to the Inbox-oriented working state
- preserve or restore `UNREAD` when possible
- remove the Fynish-applied routing outcome
- return the message to the review queue as `needs_review`
- keep audit history
- leave rules unchanged

## Product definition

### What Recover means

`Recover` means:
- “put this message back in front of me”

It does **not** mean:
- delete the rule that may have led to the action
- disable the rule
- erase past audit history

### Returned state

After recovery, the message should be:
- back in `INBOX`
- `UNREAD` if supported by the current Gmail state
- marked `needs_review` in Fynish
- visible in the review queue again

Important refinement now implemented:
- if Gmail restores the message as read, Fynish still keeps it visible in the queue until the user reprocesses it
- this avoids the confusing case where a recovered message disappears immediately because unread-only sync would otherwise sweep it away

### Rules behavior

Rules remain untouched.

Reason:
- the user may want to recover a single exception without discarding a rule that is still correct for other messages

## UI plan

### Placement

Place the `Recover` button inside the expanded panel for each processed message row.

Why:
- preserves horizontal space in the compact processed list
- avoids making every row feel overloaded
- makes recovery a deliberate secondary action

### V1 expanded panel content

Within the expanded panel:
- preview text
- processed timestamp if useful
- created rule indicator if present
- `Recover` button

### V1 user feedback

On success:
- show a notice such as:
  - `Message recovered to Inbox and returned to review queue.`

On failure:
- show a clear error message

## Backend plan

### New endpoint

Add:
- `POST /api/messages/{message_id}/recover`

### Recover service behavior

For the target message:
1. load the message and provider/account context
2. determine the current provider type
3. if Gmail-backed and live writes are enabled:
   - add `INBOX` if missing
   - remove Fynish-applied labels such as:
     - `Fynish/Bulk Mail`
     - `Fynish/Junk Review`
     - `Fynish/Trash`
     - `Fynish/Needs Review`
   - preserve `UNREAD`
4. for mock/local accounts:
   - update only the local DB state
5. update local message state:
   - `reviewed = 0`
   - `current_category = 'needs_review'`
   - `recovery_pending = 1`
6. append an audit log entry for the recovery event
7. return a recovery result payload

### Audit/history behavior

Recovery should create an audit record, but that record should not appear as a normal `Processed Mail` row.

Recommended approach:
- log `selected_action = 'recover'` in `actions_log`
- exclude `recover` rows from the normal processed mail query

This preserves history without cluttering the processed list.

### Safety behavior

Recovery should **not** immediately reapply rules.

Reason:
- otherwise the message could bounce straight back out of the queue

So after recovery, the message should return as `needs_review` regardless of prior rule matches.

Recovery should also tolerate a Gmail no-op case.

If the message is already back in `INBOX` and no Fynish labels remain, recovery should:
- skip the Gmail `messages.modify` call
- still restore the message inside Fynish

Reason:
- Gmail rejects empty modify requests with `No label or Classification Label updates provided`
- this is common for some `Keep` recovery cases

## Data/API changes

### Processed Mail payload

The processed mail payload should expose the underlying local `message_id`, because the current processed row ID is the action-log row ID.

Needed addition:
- `message_id`

This lets the frontend call:
- `POST /api/messages/{message_id}/recover`

without ambiguity.

## Gmail recovery semantics

### V1 label behavior

For Gmail-backed messages:
- add `INBOX` if it is not already present
- remove known Fynish labels
- do not remove `UNREAD`
- do not use Gmail Trash operations
- do not attempt permanent delete undo logic beyond label restoration

This keeps recovery aligned with the current safe-label mutation model.

## Frontend plan

### API

Add:
- `recoverProcessedMessage(messageId: number)`

### Processed Mail UI

In the expanded panel:
- show `Recover` only if the processed row has a valid underlying `message_id`
- disable while busy
- refresh:
  - processed messages
  - review queue
  - top summary counts

## Testing plan

### Backend tests

Add tests for:
- processed mail payload includes `message_id`
- recovering a mock/local processed message returns it to queue state
- recovery logs an audit event
- recovery audit rows do not appear in `Processed Mail`
- recovered messages stay in queue even when later unread sync does not include them
- Gmail no-op recovery does not fail when there are no label changes to send

### Frontend tests / validation

Validate:
- `Recover` button appears in expanded processed rows
- clicking it refreshes the processed list and queue
- success notice is shown
- failure state is shown when needed

## V1 success criteria

This feature is successful when:
- a processed message can be recovered from `Processed Mail`
- it returns to the queue as `needs_review`
- Gmail-backed recovery restores inbox-oriented state without touching rules
- the audit trail remains intact
- recovered messages stay visible in Fynish until they are explicitly reprocessed
