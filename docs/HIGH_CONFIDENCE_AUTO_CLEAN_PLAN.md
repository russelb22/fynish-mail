# High-Confidence Auto-Clean Plan

Status: initial backend implementation in progress; disabled by default.

## Purpose

Fynish already classifies unread Inbox messages during sync. This feature lets Fynish automatically move very high-confidence Bulk and Junk messages out of the Gmail Inbox before they appear in the Review Queue.

The goal is to make the Inbox quieter while keeping the behavior conservative, transparent, and reversible.

## Product Behavior

When enabled, sync can auto-clean a message only when all of these are true:

- the account is a real Gmail account
- Gmail modify scope is available
- live Gmail writes are enabled
- the classifier category is `bulk_mail` or `junk_review`
- classifier confidence is at or above the configured threshold
- the message is not protected
- the message has not already been preserved by a manual keep or rule auto-process decision

Auto-clean does not delete messages. It applies the normal Fynish Gmail labels and removes `INBOX` while preserving `UNREAD`.

Current label behavior:

- `bulk_mail`: add `Fynish/Bulk Mail`, remove `INBOX`
- `junk_review`: add `Fynish/Junk Review`, remove `INBOX`

Auto-cleaned messages are logged through the same action log path used by manual and live Gmail actions, so they can appear in Processed Mail and be recovered.

## Configuration

The first implementation is intentionally off by default.

Environment variables:

- `FYNISH_AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED`
  - default: `false`
  - when true, sync evaluates high-confidence auto-clean candidates
- `FYNISH_AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD`
  - default: `0.85`
  - minimum classifier confidence required for Bulk/Junk auto-clean
- `FYNISH_ENABLE_GMAIL_WRITES`
  - must also be true for Gmail label changes to execute

## Implementation Notes

The feature hooks into `sync_unread_messages` after message import/classification and after rule auto-apply checks.

Rule auto-apply remains higher priority. If a message matches a user rule and that rule auto-processes the message, high-confidence auto-clean does not run separately for the same message.

If Gmail execution fails or is blocked, the message remains in the Review Queue and does not count as auto-applied.

## Initial Test Coverage

Added unit coverage for:

- high-confidence Bulk auto-clean when enabled
- below-threshold messages staying in the queue
- protected messages staying in the queue
- feature-disabled behavior

Existing related coverage still passes for:

- Gmail write execution
- Processed Mail recover
- user-scoped mutations

## Rollout Plan

1. Keep disabled in production while the implementation is reviewed.
2. Test locally with fake/synthetic Gmail-like messages.
3. Enable for one controlled account with a conservative threshold.
4. Confirm Processed Mail and Recover handle auto-cleaned messages correctly.
5. Decide whether the user-facing setting is global, per account, or both.
6. Add UI copy explaining that Fynish never deletes in this mode.

## Open Questions

- Should Bulk and Junk use separate thresholds?
- Should the first live trial start at `0.90` instead of `0.85`?
- Should account-level UI show an auto-clean enabled/disabled status?
- Should the Review Queue show a digest notice such as "Fynish auto-cleaned 12 high-confidence messages"?
- Should protected-sender/domain overrides be user-configurable before this becomes user-facing?
