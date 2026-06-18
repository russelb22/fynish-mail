# Auto-Keep Queue Visibility Implementation Spec

Status: drafted for implementation.

## Purpose

Fynish should keep high-confidence or rule-backed `Keep` messages visible in the Fynish Queue even when Fynish is confident that the message belongs in the Gmail Inbox.

This refinement moves Fynish closer to being an Inbox operating surface rather than only a suspicious-mail triage queue. A message can be safe to keep in Gmail while still being useful to view, reply to, rule-train, or override inside Fynish.

## Current Behavior

The current queue boundary is mostly:

- `messages.reviewed = 0`: message is visible in the Fynish Queue.
- `messages.reviewed = 1`: message is no longer visible in the Fynish Queue and appears in Processed Mail through `actions_log`.

During `sync_unread_messages`, each unread Inbox message is imported and classified. If the classification matches a user rule and the category is not `needs_review`, the rule is auto-applied:

- `backend/app/services/review_queue.py`
  - `_should_auto_apply_rule_match`
  - `_auto_apply_rule_match`
  - `apply_message_action`
  - `execute_message_action`

For `keep`, this means a matching Keep rule can mark the message reviewed and log it as processed even though Gmail Inbox membership does not materially change. The user then loses the ability to do follow-up Queue operations such as Trash, Junk, Bulk, Auto-Respond, or creating a more specific rule from that row.

High-confidence auto-clean is separate and currently only applies to:

- `bulk_mail`
- `junk_review`

That path moves messages out of the Gmail Inbox, logs an action, and keeps the operation visible in Processed Mail.

## Product Decision

`Keep` should be treated differently from Bulk/Junk/Trash automation.

Recommended definition:

> Auto-Keep means Fynish believes the message belongs in the Gmail Inbox, so it leaves Gmail alone, but the message remains reviewable in the Fynish Queue until the user explicitly commits an action.

This should apply to:

- Keep rules that match during sync.
- Future classifier-driven high-confidence Keep automation, if we decide to expose it.

This should not change:

- Bulk/Junk high-confidence auto-clean behavior.
- Trash/Bulk/Junk rule auto-apply behavior.
- staged commit semantics.
- Gmail labels for uncommitted Auto-Keep messages.

## User-Facing Behavior

When a message is Auto-Keep:

- It remains in Gmail Inbox.
- It remains unread if it was unread before.
- It appears in the Fynish Queue under `Keep in Inbox`.
- The Queue row shows a visible source marker, such as `Auto-Keep` or `Rule Keep`.
- The default selected action remains `Keep`.
- The user can still:
  - Keep it
  - Trash it
  - move it to Bulk
  - move it to Junk
  - create an Always Keep/Junk rule
  - generate or send an Auto-Response

When the user commits `Keep`:

- The message becomes reviewed in Fynish.
- The action is logged.
- Gmail should remain in Inbox.
- The action source should be `staged_commit`, unless a more specific source is intentionally added later.

When the user commits a different action:

- The override should behave exactly like any other Queue message commit.
- Gmail label changes should execute if live Gmail writes and modify scope are available.
- The action log should record the selected action and the original recommended action.

## Mental Model

Avoid showing an Auto-Keep item as already processed.

The best mental model is:

- `Auto-Keep`: Fynish recommendation/provenance for an unreviewed Queue message.
- `Processed Keep`: user confirmed Keep and Fynish logged the final action.

This keeps Processed Mail and digest counts meaningful. Processed Mail should represent actual processed actions, not messages Fynish merely recommended keeping.

## Recommended Data Model

### V1: Minimal Schema Change Preferred

The current schema already has:

- `messages.current_category`
- `messages.confidence`
- `messages.reviewed`
- `classification_results.reasons_json`
- `classification_results.protection_reasons_json`
- `classification_results.created_at`
- rule match data through classification results and rule match recording

However, the frontend needs a stable way to distinguish an ordinary classifier `keep` from a rule-backed Auto-Keep.

Recommended V1 addition:

Add nullable provenance fields to `messages`:

- `queue_source TEXT NOT NULL DEFAULT 'classifier'`
- `queue_source_detail TEXT`

Suggested source values:

- `classifier`
- `rule_keep`
- `recovered`
- future: `high_confidence_keep`

Why message-level provenance is useful:

- It is cheap to query with the existing Queue payload.
- It survives page reloads.
- It avoids parsing classification reasons to infer UI badges.
- It gives future Queue features a consistent place for row provenance.

Alternative without schema change:

- Infer Auto-Keep from `classification_results.reasons_json` or matched rules.
- This is less reliable and couples UI state to human-readable classifier reasons.

Recommendation: use the minimal schema addition.

## Backend Behavior

### Rule Auto-Apply Decision

Current behavior:

```python
def _should_auto_apply_rule_match(classification, preserve_reviewed):
    return (
        bool(classification.matched_rule_ids)
        and classification.category != "needs_review"
        and not preserve_reviewed
    )
```

Recommended behavior:

- Continue auto-applying matched rules for:
  - `bulk_mail`
  - `junk_review`
  - `trash`
- Do not auto-apply matched rules for:
  - `keep`
  - `needs_review`

For matched Keep rules:

- keep `messages.reviewed = 0`
- keep `messages.current_category = 'keep'`
- set `messages.queue_source = 'rule_keep'`
- set `messages.queue_source_detail` to a compact description, probably the matched rule IDs as JSON or a simple string
- record rule matches as currently done
- do not insert an `actions_log` row
- do not call Gmail write execution
- do not increment `auto_applied_count`

Suggested helper:

```python
def _should_keep_rule_match_in_queue(classification, preserve_reviewed) -> bool:
    return (
        bool(classification.matched_rule_ids)
        and classification.category == "keep"
        and not preserve_reviewed
    )
```

This helper should run before `_should_auto_apply_rule_match`.

### Queue Source Reset

When a message is upserted/classified:

- default `queue_source` to `classifier`
- set `queue_source = 'rule_keep'` only for Keep rule matches that remain visible
- preserve recovery-specific source if recovery logic uses or later adds it

If the message later stops matching the Keep rule:

- `queue_source` should revert to `classifier`
- `current_category` should reflect the latest classifier/rule result

### Preserve Reviewed Interactions

The current sync code preserves some reviewed messages:

- manual Keep preservation
- rule auto-process preservation

Auto-Keep should respect these protections.

If `preserve_reviewed` is true:

- do not pull a previously reviewed message back into Queue simply because it matches a Keep rule
- do not change `queue_source` in a way that makes processed history ambiguous

### Reconciliation

Gmail reconciliation currently removes local queue visibility for messages that leave unread Inbox outside Fynish.

Auto-Keep should follow the same rule:

- if the message remains unread in Gmail Inbox, it remains eligible for Queue visibility
- if it leaves unread Inbox outside Fynish, reconciliation can mark it reviewed/stale as today

This keeps Auto-Keep from becoming a separate persistent task system in V1.

## Queue API Changes

`GET /api/review-queue` should include provenance fields per message:

```json
{
  "queue_source": "rule_keep",
  "queue_source_label": "Auto-Keep",
  "queue_source_detail": "Matched Always Keep rule"
}
```

Recommended label mapping:

- `classifier` -> omit label or `Classifier`
- `rule_keep` -> `Auto-Keep`
- `high_confidence_keep` -> `Auto-Keep`
- `recovered` -> `Recovered`

For V1, display only non-default labels. Classifier-labeled rows do not need additional UI noise.

## Frontend Behavior

The current Queue row already supports the required operations:

- This Message actions: Keep, Bulk, Junk, Trash
- Auto-Respond
- Teach Fynish rule buttons
- Preview expansion
- staged commit

Frontend work should be small:

1. Extend Queue message type with:
   - `queue_source`
   - `queue_source_label`
   - `queue_source_detail`
2. Render a small badge near the classification pill when `queue_source_label` is present.
3. For `rule_keep`, the badge text should be `Auto-Keep`.
4. Keep the message in the `Keep in Inbox` group.
5. Do not add new buttons in V1.

Suggested row copy:

- Badge: `Auto-Keep`
- Tooltip/title: `Matched a Keep rule. Left in Gmail Inbox and kept here for review.`

Avoid text-heavy explanatory copy inside the row. The badge should be enough.

## Processed Mail Behavior

Uncommitted Auto-Keep messages should not appear in Processed Mail.

Processed Mail should only show the message after the user commits an action.

If user commits Keep:

- selected action: `keep`
- recommended action: `keep`
- action source: `staged_commit`

If user commits Trash/Bulk/Junk:

- selected action: user action
- recommended action: likely `keep`
- user override: true, if existing action-log behavior derives or stores that
- action source: `staged_commit`

## Digest Behavior

Daily digest processed counts should not count uncommitted Auto-Keep items as processed.

Queue count should include Auto-Keep messages because they are still reviewable.

Optional V1 digest enhancement:

- Add a `current_auto_keep_queue_count` to the queue summary.

Recommendation:

- Defer digest-specific changes unless the Queue count becomes confusing.
- The normal Queue count is enough for the first implementation.

## Auto-Response Behavior

Auto-Response should work unchanged because the message remains a normal Queue row.

Important validation:

- Auto-Response draft generation can read the Auto-Keep message.
- Auto-Response send can still use the monitored account's Gmail send permission.
- Sending a response should not automatically mark the message reviewed unless existing Auto-Response send behavior already does so.

## Rule Creation Behavior

If a user creates an Always Keep Domain rule from an Auto-Keep message:

- rule creation should still be allowed
- duplicate prevention should avoid creating exact duplicate rules
- the source message should remain staged/committed according to current staged rule behavior

If a user creates Always Junk Domain from an Auto-Keep message:

- the created rule should be `junk_review`
- the source message action should be staged as `junk_review`
- committing should override the Auto-Keep recommendation

## Testing Plan

### Unit Tests

Add or update `backend/tests/unit/test_review_queue.py`:

1. Keep rule match remains in queue
   - seed Gmail account
   - create Keep rule matching a message
   - run `sync_unread_messages`
   - assert message has `reviewed = 0`
   - assert `current_category = 'keep'`
   - assert no `actions_log` row was inserted
   - assert Queue includes the message under Keep
   - assert `queue_source = 'rule_keep'`

2. Bulk/Junk rule matches still auto-apply
   - existing coverage may already prove this
   - add regression assertion if needed

3. Keep rule does not increment `auto_applied_count`
   - sync result should not count visible Auto-Keep as auto-applied

4. Keep rule does not execute Gmail write
   - monkeypatch Gmail write executor or assert labels are unchanged

5. Keep rule source resets when rule no longer matches
   - optional, but useful if implementation is simple

### Integration Tests

Add or update Queue API tests:

1. `GET /api/review-queue` includes `queue_source` fields.
2. Auto-Keep row appears in `Keep in Inbox`.
3. Staged commit of Auto-Keep as `keep` succeeds.
4. Staged commit of Auto-Keep as `trash` succeeds and logs override.
5. Stale-version checks still apply.

### Frontend Build/Smoke

At minimum:

- `npm run build`

If a Playwright smoke exists or is practical:

- load Queue with a seeded Auto-Keep item
- assert `Auto-Keep` badge renders
- stage a non-Keep action from the row
- assert staged panel works as usual

## Implementation Slices

### Slice 1: Backend Provenance Schema

Scope:

- Add `queue_source` and `queue_source_detail` columns to SQLite and Postgres schema/migration path.
- Ensure local schema bootstrap adds defaults for existing databases.
- Update database schema tests.

Good enough when:

- New columns exist on fresh and migrated databases.
- Existing messages default to `classifier`.
- Tests pass for schema bootstrap.

### Slice 2: Keep Rule Stays In Queue

Scope:

- Change rule auto-apply decision so `keep` rule matches remain unreviewed.
- Set `queue_source = 'rule_keep'` for Keep rule matches.
- Keep Bulk/Junk/Trash rule auto-apply unchanged.
- Ensure no action log is created for uncommitted Auto-Keep.

Good enough when:

- Unit tests prove Keep rule match remains in Queue.
- Existing auto-apply tests for Bulk/Junk/Trash still pass.
- Sync result counts remain sensible.

### Slice 3: Queue API Provenance Fields

Scope:

- Return `queue_source`, `queue_source_label`, and `queue_source_detail` from `get_review_queue`.
- Add tests for API payload.

Good enough when:

- Auto-Keep item has `queue_source = 'rule_keep'`.
- Auto-Keep item has `queue_source_label = 'Auto-Keep'`.
- Ordinary classifier items either omit the label or return a non-noisy default.

### Slice 4: Frontend Badge

Scope:

- Extend frontend types.
- Render `Auto-Keep` badge near classification/source metadata.
- Keep visual style restrained and consistent with existing pills.

Good enough when:

- `npm run build` passes.
- Auto-Keep rows are visually distinct.
- No new row actions are added.
- Existing Queue controls still fit on desktop/mobile.

### Slice 5: Staged Commit Regression Coverage

Scope:

- Add tests that commit Auto-Keep rows as Keep and as another action.
- Confirm processed logs are created only at commit time.
- Confirm Processed Mail does not show uncommitted Auto-Keep.

Good enough when:

- Auto-Keep can be committed normally.
- Override action records recommended `keep` and selected override.
- stale-version checks still protect the row.

### Slice 6: Documentation and Manual Test Checklist

Scope:

- Update functional/user docs to define Auto-Keep.
- Add manual test checklist for:
  - Always Keep rule
  - Queue badge
  - Keep commit
  - Trash override
  - Auto-Respond access

Good enough when:

- The behavior is documented in user-facing language.
- Implementation notes explain the difference between Auto-Keep and auto-clean.

## Deployment Plan

Recommended rollout:

1. Implement Slices 1-3 locally.
2. Run backend tests.
3. Implement Slice 4 locally.
4. Run frontend build.
5. Implement Slice 5 locally.
6. Deploy all slices together to the VM.
7. Validate with one controlled Keep rule on Russel's account.
8. Confirm Kim's account still sees normal Queue behavior.

## Manual Validation Checklist

1. Create or identify an Always Keep rule for a safe sender/domain.
2. Send or recover a matching unread Inbox message.
3. Refresh mail accounts.
4. Confirm:
   - message remains in Gmail Inbox
   - message appears in Fynish Queue
   - message is in `Keep in Inbox`
   - row shows `Auto-Keep`
   - row can open preview
   - Auto-Respond is available
5. Stage Keep and commit.
6. Confirm:
   - message leaves Queue
   - Processed Mail shows Keep
   - Gmail Inbox still contains the message
7. Repeat with another matching message and stage Trash.
8. Confirm:
   - message leaves Queue after commit
   - Gmail labels reflect Trash action
   - Processed Mail shows selected Trash and recommended Keep

## Open Questions

1. Should the visible badge say `Auto-Keep`, `Rule Keep`, or `Kept by Rule`?
   - Recommendation: `Auto-Keep`.

2. Should classifier-only high-confidence Keep also get the `Auto-Keep` badge?
   - Recommendation: not in the first implementation. Start with rule-backed Keep because it is authoritative and easier to explain.

3. Should there be a Queue filter to hide Auto-Keep?
   - Recommendation: defer. Add only if the Keep group gets noisy.

4. Should there be a bulk action such as `Commit all Auto-Keep`?
   - Recommendation: defer. This is useful later, but it changes the interaction model and should follow real usage.

5. Should Auto-Keep count appear in the daily digest?
   - Recommendation: defer unless users ask why Queue counts are higher.

## Non-Goals

- Do not render full email HTML in the Queue.
- Do not create a second Inbox database state.
- Do not auto-commit Keep messages.
- Do not change Bulk/Junk high-confidence auto-clean.
- Do not change Gmail read/unread status.
- Do not add a new Queue action button in V1.

