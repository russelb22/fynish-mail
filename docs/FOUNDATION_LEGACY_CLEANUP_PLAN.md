# Foundation Legacy Cleanup Plan

## Purpose

This document prepares the project for eventual removal of the legacy Gmail-shaped schema elements and compatibility paths that were kept during the foundation refactor.

This is intentionally a planning document only.

No legacy column or table should be removed as part of this ticket.

## Why this cleanup is separate

The foundation refactor was done additively on purpose:

- new ownership-aware and provider-neutral tables/columns were introduced first
- backfills were added
- reads and writes were gradually moved over
- legacy structures were kept alive during stabilization

That reduced product risk while the live Gmail workflow stayed active.

The next step is not “delete old things immediately.” The next step is to define exactly what is safe to remove, what still has compatibility value, and what should remain longer because it supports Gmail-first product work.

## Current legacy structures still in play

### Legacy tables

These still exist and still participate in some current flows:

- `accounts`
- `gmail_account_connections`
- `notification_settings`

### Legacy message columns

These are still written and/or read in compatibility paths:

- `messages.gmail_message_id`
- `messages.gmail_thread_id`
- `messages.account_email`
- `messages.gmail_labels_json`

### Legacy action-log columns

These are still written for compatibility:

- `actions_log.gmail_message_id`
- `actions_log.account_email`
- `actions_log.gmail_labels_added_json`
- `actions_log.gmail_labels_removed_json`

### Legacy joins and lookup patterns

These still appear in parts of the codebase:

- `account_email` joins instead of `mail_account_id`
- `gmail_message_id` joins instead of `provider_message_id`
- direct reads from `accounts` / `gmail_account_connections`
- fallback reads from `notification_settings`

## Structures that should remain authoritative

These are now the long-term targets and should remain the primary model:

- `users`
- `mail_accounts`
- `provider_connections`
- `messages.mail_account_id`
- `messages.provider_message_id`
- `messages.provider_thread_id`
- `messages.provider_labels_json`
- `rules.user_id`
- `rules.mail_account_id`
- `rules.created_from_mail_account_id`
- `actions_log.message_id`
- `actions_log.mail_account_id`
- `actions_log.provider_message_id`
- `actions_log.provider_labels_added_json`
- `actions_log.provider_labels_removed_json`
- `notification_settings_by_user`

## What can likely be removed later

These are good candidates for a later dedicated cleanup pass, once the readiness checklist below is satisfied.

### First-tier removal candidates

These are the cleanest removals once the code no longer depends on them:

- direct reads from `notification_settings`
- direct reads from `gmail_account_connections`
- direct reads from legacy-only `accounts` rows where matching `mail_accounts` already exist

### Second-tier removal candidates

These need stronger confidence because they still touch message identity and audit history:

- `messages.gmail_message_id`
- `messages.gmail_thread_id`
- `messages.account_email`
- `messages.gmail_labels_json`
- `actions_log.gmail_message_id`
- `actions_log.account_email`
- `actions_log.gmail_labels_added_json`
- `actions_log.gmail_labels_removed_json`

### Final removal candidates

These should be removed only after all reads/writes and migration/recovery tooling are fully cut over:

- `accounts`
- `gmail_account_connections`
- `notification_settings`

## What should probably stay longer

Some legacy-looking concepts may still deserve a temporary life even after most cleanup is done.

### Gmail-specific provider details

Because the product is Gmail-first for now, it is reasonable to keep Gmail-aware business logic where it expresses real product behavior, for example:

- Gmail modify-scope handling
- Gmail label semantics
- Gmail read-only/live-write validation scripts

These should move behind provider adapters and provider-neutral models, but they do not need to disappear just because their names are Gmail-specific.

### Dev/test recovery helpers

The live-account rehydration helper is not part of the future hosted product model, but it is useful in the current local-development era. It can stay until local-reset flows are redesigned.

## Readiness checklist before cleanup

The following should be true before any destructive cleanup ticket starts.

### Schema and data readiness

- `messages.mail_account_id` is populated for all active rows
- `messages.provider_message_id` is populated for all active rows
- `actions_log.message_id` is populated for all current action rows
- `actions_log.mail_account_id` is populated for all current action rows
- `notification_settings_by_user` is the only settings store used by the running app

### Codepath readiness

- account reads no longer require `accounts` as a primary source
- provider connection reads no longer require `gmail_account_connections` as a primary source
- review queue reads no longer require `account_email` joins as a normal path
- processed mail reads no longer require legacy action-log joins as a normal path
- action logging no longer requires Gmail-specific audit columns as a normal path
- reminder generation no longer depends on legacy account tables

### Validation readiness

- `make foundation-check` passes
- `make foundation-validate` passes
- live Gmail read-only validation passes
- live Gmail dry-run validation passes
- regression coverage includes processed mail and notification settings behavior

### Product readiness

- current UI behavior is unchanged after legacy-path feature flags are disabled in staging/local testing
- no user-visible workflow depends on legacy-only account rows
- no recovery/documented dev flow depends on old tables without an explicit replacement

## Suggested cleanup order

When the team chooses to do the cleanup, this is the recommended order.

1. Remove legacy singleton notification settings reads
2. Remove legacy read fallbacks from account/service layers where `mail_accounts` and `provider_connections` are authoritative
3. Remove legacy join fallbacks in processed mail and queue history paths
4. Stop writing legacy Gmail-shaped action-log columns
5. Stop writing legacy Gmail-shaped message columns
6. Drop unused legacy columns after a migration validation pass
7. Remove `gmail_account_connections`
8. Remove `accounts`
9. Remove `notification_settings`

## Rollback posture

Any future cleanup ticket should preserve rollback safety:

- remove one layer at a time
- re-run `make foundation-check` after each layer
- avoid dropping columns/tables in the same step as broad service rewrites
- keep a backup/export path for the local SQLite DB before destructive migration work

## Recommendation

Do not rush legacy cleanup.

The current codebase is now in a good hybrid state:

- provider-aware foundations are in place
- current Gmail product behavior still works
- validation coverage is strong

The right next move after this plan is to wait until either:

- more service paths are fully provider-neutral, or
- a hosted/multi-user milestone makes the legacy structures actively costly

Until then, this cleanup plan should be used as the gate for any destructive schema simplification work.
