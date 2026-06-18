# Foundation Schema Migration Plan

## Purpose

This document turns the foundation refactor specification into a concrete schema migration plan.

It is written for the first major backend refactor only. The plan assumes:

- SQLite remains the active database during this phase
- Gmail is still the only real provider
- the near-term product remains Gmail-first even while the schema becomes provider-aware
- current local behavior should continue working during the migration

The goal is to migrate from the current operator-centric schema to an ownership-aware, provider-neutral schema with minimal product disruption.

Important direction:

- this schema should remain provider-neutral internally
- but it should also support deeper Gmail-specific product evolution later, including:
  - full message/thread read
  - reply and reply-all
  - forward
  - limited label/folder-style navigation

The ticketized implementation follow-up to this plan is documented in [docs/FOUNDATION_IMPLEMENTATION_TICKETS.md](docs/FOUNDATION_IMPLEMENTATION_TICKETS.md).

The legacy cleanup follow-up to this migration plan is documented in [docs/FOUNDATION_LEGACY_CLEANUP_PLAN.md](docs/FOUNDATION_LEGACY_CLEANUP_PLAN.md).

## Summary of the migration approach

Recommended strategy:

1. add new tables and new columns without removing old ones
2. seed a default local owner user
3. backfill new ownership and provider-neutral fields
4. move backend reads to the new schema gradually
5. move backend writes to the new schema
6. keep compatibility reads/writes for a short stabilization window
7. only later remove legacy Gmail-named columns and tables

This is intentionally an additive migration, not a destructive rewrite.

## Current schema snapshot

Current tables:

- `accounts`
- `messages`
- `classification_results`
- `rules`
- `actions_log`
- `gmail_account_connections`
- `notification_settings`

Current structural problems:

- no `users` table
- account ownership is implicit
- rules are structurally global
- message joins rely on `account_email`
- multiple fields use Gmail-specific names
- provider connection storage is Gmail-specific
- the schema is still optimized for triage, not for richer Gmail-client workflows

## Target schema snapshot for this phase

This phase should introduce or evolve toward:

- `users`
- `mail_accounts`
- `provider_connections`
- migrated `messages`
- migrated `rules`
- migrated `actions_log`
- migrated `notification_settings`

Legacy tables can remain temporarily during the cutover:

- `accounts`
- `gmail_account_connections`

## Table-by-table migration mapping

### 1. `accounts` -> `mail_accounts`

Current:

```text
accounts
  id
  email_address
  enabled
  provider
  last_sync_at
  created_at
  updated_at
```

Target:

```text
mail_accounts
  id
  user_id
  provider
  external_account_email
  display_name
  enabled
  status
  last_sync_at
  created_at
  updated_at
```

Backfill mapping:

- `external_account_email = accounts.email_address`
- `enabled = accounts.enabled`
- `provider = accounts.provider`
- `last_sync_at = accounts.last_sync_at`
- `display_name = accounts.email_address` initially
- `status = 'active'` if enabled else `'disabled'`
- `user_id = default local owner user`

### 2. `gmail_account_connections` -> `provider_connections`

Current:

```text
gmail_account_connections
  account_id
  token_path
  scopes_json
  created_at
  updated_at
```

Target:

```text
provider_connections
  id
  mail_account_id
  provider
  connection_type
  credentials_ref
  token_path
  scopes_json
  metadata_json
  created_at
  updated_at
```

Backfill mapping:

- `mail_account_id = mapped mail_accounts.id`
- `provider = mail_accounts.provider`
- `connection_type = 'oauth'`
- `credentials_ref = NULL` for now
- `token_path = existing token_path`
- `scopes_json = existing scopes_json`
- `metadata_json = '{}'`

Forward-looking note:

- `provider_connections` should be able to represent broader Gmail scopes later, including compose/send-related scopes, without another table redesign

### 3. `messages`

Current key columns:

```text
id
gmail_message_id
gmail_thread_id
account_email
gmail_labels_json
...
```

Target direction:

```text
id
mail_account_id
provider_message_id
provider_thread_id
provider_labels_json
...
```

Backfill mapping:

- `mail_account_id = lookup mail_accounts.id by account_email`
- `provider_message_id = gmail_message_id`
- `provider_thread_id = gmail_thread_id`
- `provider_labels_json = gmail_labels_json`

Forward-looking note:

- even if the current UI still uses triage previews, the message model should remain suitable for future Gmail full-read and thread-aware client features

Target uniqueness:

- `UNIQUE(mail_account_id, provider_message_id)`

### 4. `rules`

Current key columns:

```text
id
scope
account_email
rule_type
pattern
action
...
```

Target direction:

```text
id
user_id
mail_account_id nullable
scope
rule_type
pattern
action
...
```

Backfill mapping:

- `user_id = default local owner user`
- `mail_account_id = lookup by account_email when present`
- current `scope = 'global'` should become effectively user-scoped in meaning

Important compatibility note:

- in this phase, preserve current behavior by treating legacy global rules as rules belonging to the one default user

### 5. `actions_log`

Current key columns:

```text
gmail_message_id
account_email
gmail_labels_added_json
gmail_labels_removed_json
```

Target direction:

```text
message_id nullable
mail_account_id
provider_message_id
provider_labels_added_json
provider_labels_removed_json
```

Backfill mapping:

- `mail_account_id = lookup by account_email`
- `provider_message_id = gmail_message_id`
- `message_id = lookup messages.id by account + provider_message_id when possible`
- `provider_labels_added_json = gmail_labels_added_json`
- `provider_labels_removed_json = gmail_labels_removed_json`

Forward-looking note:

- `actions_log` should remain mailbox-action oriented; reply/forward/send activity, if added later, should likely use separate audit records or an expanded audit model rather than overloading this table incorrectly

### 6. `notification_settings`

Current:

- singleton table with one row

Target:

- user-scoped settings

Backfill mapping:

- one new settings row created for the default local owner user
- values copied from singleton row

## Proposed migration DDL phases

### Phase 1: Add new tables

Add:

- `users`
- `mail_accounts`
- `provider_connections`
- user-scoped `notification_settings_v2` or upgraded `notification_settings`

Recommended approach:

- prefer new tables rather than rewriting old ones in place
- this makes validation and rollback much safer

### Phase 2: Add new columns to existing tables

Add to `messages`:

- `mail_account_id`
- `provider_message_id`
- `provider_thread_id`
- `provider_labels_json`

Recommended optional additions if implemented cleanly in this phase:

- `provider_headers_json` as a future-neutral rename target for richer message/thread reads

Add to `rules`:

- `user_id`
- `mail_account_id`
- `created_from_mail_account_id`

Add to `actions_log`:

- `message_id`
- `mail_account_id`
- `provider_message_id`
- `provider_labels_added_json`
- `provider_labels_removed_json`

Do not drop the old Gmail-specific columns yet.

### Phase 3: Add new indexes and constraints

Add after backfill or with null-tolerant sequencing:

- index on `mail_accounts(user_id, provider, external_account_email)`
- index on `messages(mail_account_id, provider_message_id)`
- index on `rules(user_id, mail_account_id, enabled)`
- index on `actions_log(mail_account_id, provider_message_id)`

Do not add strict `NOT NULL` or uniqueness constraints until after backfill succeeds.

## Backfill plan

### Step 1: Create default local owner user

Insert one user row, for example:

- `email = 'local-owner@fynish.local'`
- `display_name = 'Local Owner'`
- `status = 'active'`

This record is the ownership anchor for all migrated data in this phase.

### Step 2: Backfill `mail_accounts`

For each row in `accounts`:

- create one `mail_accounts` row
- store a mapping from `accounts.id` and `accounts.email_address` to `mail_accounts.id`

This mapping should be explicit in the migration code because it will be reused several times.

### Step 3: Backfill `provider_connections`

For each row in `gmail_account_connections`:

- create one `provider_connections` row
- map `account_id` to the new `mail_account_id`

### Step 4: Backfill `messages`

For each row in `messages`:

- set `mail_account_id`
- copy Gmail ids/labels into provider-neutral columns

If additional provider-neutral metadata columns are added in this phase:

- backfill them from the existing Gmail-shaped source fields rather than leaving them empty

Validation after this step:

- every existing message row has a non-null `mail_account_id`
- every existing message row has non-null `provider_message_id`

### Step 5: Backfill `rules`

For each row in `rules`:

- set `user_id = default owner`
- set `mail_account_id` when `account_email` is present
- set `created_from_mail_account_id` when `created_from_account` is present

Validation after this step:

- every rule has a `user_id`
- no enabled exact duplicate rules are introduced by the migration

### Step 6: Backfill `actions_log`

For each row in `actions_log`:

- set `mail_account_id`
- set `provider_message_id`
- copy label fields into provider-neutral columns
- resolve `message_id` where possible

Validation after this step:

- every action row has `mail_account_id`
- every action row has `provider_message_id`

### Step 7: Backfill `notification_settings`

- copy the singleton settings row to a user-scoped row for the default owner

## Read cutover plan

Recommended order:

### Read cutover A: accounts

Refactor account-facing services to read from `mail_accounts` first.

Compatibility behavior:

- API can still return `email_address` derived from `external_account_email`

### Read cutover B: messages and queue

Refactor review queue and sync services to read:

- `mail_account_id`
- `provider_message_id`
- `provider_labels_json`

instead of:

- `account_email`
- `gmail_message_id`
- `gmail_labels_json`

Important design note:

- the read-path refactor should not assume “queue preview only”
- it should leave room for future Gmail full-read and thread views built on the same message storage

### Read cutover C: rules

Refactor rules service to treat rules as:

- user-owned
- optionally account-scoped

while still preserving current effective behavior for the default local user.

### Read cutover D: actions log and reminders

Refactor reminder and audit paths to resolve everything through:

- `mail_account_id`
- user ownership

## Write cutover plan

Recommended order:

### Write cutover A: new account/provider connections

When a Gmail account is connected:

- write `mail_accounts`
- write `provider_connections`
- optionally continue mirroring to legacy tables during a short stabilization window if needed

The new connection model should preserve whatever Gmail scopes were actually granted, so later Gmail-client features can detect capability differences cleanly.

### Write cutover B: sync/import

When messages are imported:

- write `mail_account_id`
- write provider-neutral columns
- stop relying on `account_email` for new rows

This write path should remain compatible with future richer Gmail reads, even if the current UI still uses only snippets/body previews.

### Write cutover C: rules

When rules are created:

- write `user_id`
- write `mail_account_id` when account-scoped
- preserve duplicate-rule reuse/re-enable logic

### Write cutover D: action logs

When Gmail actions are planned or executed:

- write provider-neutral log fields
- attach `message_id` when available

## Compatibility window

During stabilization, it is acceptable to keep:

- old columns populated
- old tables present
- compatibility reads for selective flows

But new code should increasingly prefer:

- `mail_account_id`
- `provider_message_id`
- `provider_connections`
- user-scoped rules/settings

## Legacy cleanup plan

Do not do this until the cutover is validated.

Cleanup candidates:

- `messages.gmail_message_id`
- `messages.gmail_thread_id`
- `messages.account_email`
- `messages.gmail_labels_json`
- `rules.account_email`
- `actions_log.gmail_message_id`
- `actions_log.account_email`
- `actions_log.gmail_labels_added_json`
- `actions_log.gmail_labels_removed_json`
- `accounts`
- `gmail_account_connections`

Recommended cleanup rule:

- remove legacy structures only after at least one full validation cycle passes with new-schema-only reads/writes

## Migration validation checklist

### Row-count validation

- number of `accounts` rows == number of `mail_accounts` rows for migrated data
- number of `gmail_account_connections` rows == number of `provider_connections` rows for Gmail data
- number of `messages` rows unchanged
- number of `rules` rows unchanged
- number of `actions_log` rows unchanged

### Referential validation

- every `mail_accounts.user_id` resolves to a `users.id`
- every `messages.mail_account_id` resolves to a `mail_accounts.id`
- every `provider_connections.mail_account_id` resolves to a `mail_accounts.id`
- every `rules.user_id` resolves to a `users.id`

### Behavioral validation

- review queue still shows the same visible messages before/after migration
- Gmail rule auto-processing still works
- Gmail reconciliation still removes stale local queue items
- live Gmail writes still preserve `UNREAD`
- `Soft Trash` still means `Fynish/Trash` + remove `INBOX`
- migrated message/account structures still preserve the thread/message relationships Gmail-client features will need later

### Snapshot validation

Before migration and after migration, compare:

- queue counts by account/category
- enabled rule counts
- duplicate-rule prevention behavior
- reminder summary totals

## Rollback plan

Because this is an additive migration, rollback should be practical if a cutover step fails.

Recommended rollback strategy:

1. stop new-schema write paths
2. switch reads back to legacy tables/columns
3. keep migrated data for debugging
4. fix migration/backfill issues
5. rerun migration on a reset database copy or controlled backup

Important:

- never delete legacy tables during the first cutover
- keep a database backup before the first migration run

## Migration tooling recommendation

The current app uses a simple schema bootstrap model, so this phase should add explicit migration utilities.

Recommended additions:

- `scripts/migrate_foundation_schema.py`
- `scripts/validate_foundation_migration.py`
- migration-specific test fixtures

Suggested script responsibilities:

### `scripts/migrate_foundation_schema.py`

- apply additive schema changes
- create default local owner user
- backfill data
- print migration summary

### `scripts/validate_foundation_migration.py`

- validate row counts
- validate foreign keys
- validate queue compatibility
- validate rules and logs

## Recommended implementation order

1. finalize new target schema definitions
2. implement migration script and validation script
3. add migration tests against seeded SQLite fixture data
4. switch read paths for accounts and queue
5. switch rule and log paths
6. switch sync/import and live-write paths
7. run full validation suite

Implementation attitude:

- optimize the product roadmap around Gmail first
- keep the storage and service boundaries provider-aware so the system does not become trapped in Gmail-only assumptions again

## Exit criteria

This migration plan is complete when:

1. current data is safely backfilled into user-owned and provider-neutral structures
2. current product behavior is preserved
3. new backend code no longer depends primarily on email-address joins
4. new backend code no longer depends primarily on Gmail-specific storage names
5. the codebase is ready for hosted auth and a second provider without another schema rewrite
