# Foundation Refactor Engineering Specification

## Purpose

This document defines the first major refactor for Fynish after the current local-first Gmail prototype.

The goal of this refactor is to create the structural foundation needed for:

- always-on hosted deployment
- true multi-user ownership
- support for providers beyond Gmail

This spec intentionally does **not** cover GitHub publication work in detail. That can happen later. The focus here is the first engineering refactor that changes the codebase shape.

The next concrete implementation follow-up to this spec is documented in [docs/FOUNDATION_SCHEMA_MIGRATION_PLAN.md](docs/FOUNDATION_SCHEMA_MIGRATION_PLAN.md).

## Why this refactor comes first

The current product works well as a single-operator Gmail-focused application, but several important parts are still tightly coupled to that assumption:

- account ownership is implicit rather than modeled
- email addresses are used as join keys
- Gmail-specific names appear in the schema and service layer
- rules are effectively global
- provider connection storage is Gmail-specific

If we move to hosted deployment or multi-user support without changing those foundations first, we will create expensive migration rework.

## Refactor objective

Deliver a provider-neutral, ownership-aware backend foundation while preserving current product behavior for the single current operator.

In practical terms, this means:

- no visible regression in the current local workflow
- real Gmail read/write support continues to work
- mock testing harness continues to work
- data model becomes ready for hosted auth and additional users later
- services become ready for additional mail providers later

## Scope

### In scope

- introduce explicit user ownership in the schema
- introduce explicit mail account ownership in the schema
- replace email-address joins with id-based foreign keys
- rename or abstract Gmail-specific schema concepts into provider-neutral concepts
- create a provider connection model that can support Gmail now and other providers later
- refactor core backend services to use the new ids and abstractions
- preserve current UI behavior through compatibility-oriented API responses
- add migration/backfill logic from the current SQLite schema
- extend tests to protect the migration and compatibility path

### Out of scope

- hosted deployment to Google Cloud
- PostgreSQL cutover
- hosted user authentication
- public signup or admin account management
- second mail provider implementation
- full frontend redesign

## Non-goals

This refactor is not intended to:

- fully solve multi-tenancy
- redesign every endpoint
- change product policy for `Soft Trash`, `Junk Review`, or `Keep`
- remove the mock harness
- remove Gmail-specific live-write functionality

## Current-state constraints

Today the key schema limitations are:

- `accounts.email_address` is globally unique
- `messages.account_email` is denormalized
- `messages.gmail_message_id` and `messages.gmail_thread_id` are Gmail-specific
- `messages.gmail_labels_json` is Gmail-specific
- `rules.account_email` uses email scoping instead of account ids
- `actions_log.gmail_message_id` and `actions_log.account_email` are Gmail-specific
- `gmail_account_connections` is provider-specific

These limitations directly affect cloud readiness, multi-user safety, and provider extensibility.

## Design principles

### 1. Preserve current behavior first

The refactor should preserve current operator behavior unless there is a strong safety reason to change it.

### 2. Add ownership before auth

We do not need hosted login yet, but we do need first-class ownership entities so auth can be added later without rewriting the data layer again.

### 3. Normalize provider concepts internally

Gmail should become one provider implementation, not the application model.

### 4. Prefer additive migration first

Where possible, add new columns/tables first, backfill them, and only then move reads/writes to the new model. This reduces breakage risk.

### 5. Keep the API stable where reasonable

Frontend disruption should be minimized during this refactor. The backend can translate new storage structures back into familiar response shapes until later UI changes are worthwhile.

### 6. Scale lightly but intentionally

This refactor should assume that Fynish may grow to dozens of users without special drama.

That means:

- avoid local-only storage assumptions
- prefer bounded, indexed query patterns
- preserve room for retention policies on message history and logs
- keep sync/account operations idempotent and account-scoped

## Target architecture after this refactor

After this work, the backend should conceptually look like:

```text
User
  owns MailAccount
MailAccount
  has ProviderConnection
MailAccount
  owns Message
User and/or MailAccount
  own Rule
Message
  has ClassificationResult
Message
  can produce ActionLog
MailProviderAdapter
  lists unread inbox messages
  fetches messages
  plans provider actions
  executes provider actions
```

## Target schema direction

### New core entities

#### `users`

Represents the application owner identity, even before hosted auth exists.

Suggested fields:

```text
id
email
display_name
status
created_at
updated_at
```

Initial behavior:

- one seeded local owner user is created during migration
- all current accounts, rules, messages, and settings are associated with that user

#### `mail_accounts`

Replaces the current `accounts` table as the long-term ownership model.

Suggested fields:

```text
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

Notes:

- `external_account_email` replaces `email_address` as descriptive external identity
- uniqueness should become `(user_id, provider, external_account_email)`

#### `provider_connections`

Replaces `gmail_account_connections`.

Suggested fields:

```text
id
mail_account_id
provider
connection_type
credentials_ref
token_path nullable for local-only phase
scopes_json
metadata_json
created_at
updated_at
```

Notes:

- in the local phase, `token_path` can remain for compatibility
- later cloud phases can replace local token paths with secret references

### Existing entities to reshape

#### `messages`

Target direction:

```text
id
mail_account_id
provider_message_id
provider_thread_id
sender
sender_domain
reply_to
recipient_to
recipient_cc
subject
received_at
snippet
body_preview
provider_labels_json
headers_json
has_attachments
current_category
confidence
protected
reviewed
created_at
updated_at
```

Migration mapping:

- `gmail_message_id` -> `provider_message_id`
- `gmail_thread_id` -> `provider_thread_id`
- `gmail_labels_json` -> `provider_labels_json`
- `account_email` -> `mail_account_id`

Target uniqueness:

- `UNIQUE(mail_account_id, provider_message_id)`

#### `rules`

Target direction:

```text
id
user_id
mail_account_id nullable
scope
rule_type
pattern
action
enabled
created_from_mail_account_id nullable
created_from_message_id nullable
match_count
last_matched_at
created_at
updated_at
```

Notes:

- default rule scope should become user-scoped
- account-scoped rules remain possible
- exact duplicate prevention should survive the refactor

#### `actions_log`

Target direction:

```text
id
message_id nullable
mail_account_id
provider_message_id
selected_action
recommended_action
user_overrode
provider_labels_added_json
provider_labels_removed_json
created_rule_id
created_at
```

Notes:

- the log should remain human-auditable
- provider-neutral field names matter here because this table will become more important in hosted mode

#### `notification_settings`

Target direction:

- move from singleton row to user-scoped settings

Suggested fields:

```text
id
user_id
enabled
recipient_email
timezone
morning_enabled
morning_time
evening_enabled
evening_time
send_only_if_queue_nonempty
created_at
updated_at
```

## User model for this phase

This refactor should introduce a local placeholder user model now, before hosted auth exists.

Recommended behavior:

- create one local owner record during migration
- mark it as the default application owner
- attach all current accounts and rules to that user
- structure services as if authenticated user context exists, even if the current app still uses one default user internally

This avoids a second disruptive refactor later when hosted auth is added.

## Provider abstraction for this phase

The refactor should introduce a provider interface without adding a second provider yet.

### Target interface

```text
MailProviderAdapter
  connect()
  refresh_credentials()
  list_unread_inbox_messages()
  fetch_message()
  plan_action()
  execute_action()
```

### First implementation

- `GmailProviderAdapter`

### What should move behind the adapter

- unread inbox listing
- message fetch
- HTML/plain-text extraction handoff inputs
- live write execution
- label/state reconciliation
- insert/send test helper support where practical

### What should stay outside the adapter

- classifier logic
- rule matching logic
- review queue grouping/sorting logic
- general reminder summary generation

## Service refactor requirements

### Review queue service

Must stop depending on:

- `account_email`
- Gmail-specific message ids

Must start depending on:

- `mail_account_id`
- provider adapter interface
- provider-neutral label field names

### Rules service

Must:

- operate on user-scoped and optional account-scoped rules
- preserve duplicate-rule prevention
- preserve disabled-rule re-enable behavior
- preserve match count updates

### Gmail live write planner/executor

Should be refactored toward:

- provider-neutral planning interface
- Gmail-specific translation within the Gmail adapter

Important:

- existing Gmail safety invariants must remain intact
- `UNREAD` preservation remains required
- no Gmail Trash in current product behavior
- no permanent delete

### Accounts service

Must evolve toward:

- user-owned `mail_accounts`
- provider-neutral connection metadata
- compatibility with current mock and Gmail accounts

## Migration strategy

Recommended approach: additive migration with staged cutover.

### Stage 1: Additive schema

Add:

- `users`
- `mail_accounts`
- `provider_connections`
- new provider-neutral columns/tables as needed

Do not remove old columns yet.

### Stage 2: Backfill

Backfill:

- default local owner user
- `mail_accounts` from `accounts`
- `provider_connections` from `gmail_account_connections`
- `messages.mail_account_id`
- provider-neutral message id/thread id/labels fields
- user/account ownership on rules and settings

### Stage 3: Dual-read / compatibility phase

Refactor services to prefer the new schema while still tolerating existing local data during the transition.

### Stage 4: Cutover

Switch all writes to the new structures.

### Stage 5: Cleanup

Once tests pass and the app is stable:

- deprecate old Gmail-named columns/tables
- optionally keep compatibility views/helpers during a short transition window

## API compatibility strategy

During this refactor, keep current frontend contracts as stable as practical.

Examples:

- account responses can still expose `email_address` while backend storage uses `external_account_email`
- message responses can still expose existing fields while internally reading provider-neutral columns

This is intentionally a backend-first refactor.

## Testing requirements

This refactor should add or extend tests for:

### Migration tests

- current SQLite schema migrates to the new schema correctly
- one default local user is created
- existing accounts are attached to that user
- existing rules are preserved with correct scope
- existing messages remain reachable and deduped

### Service compatibility tests

- review queue still groups correctly
- Gmail sync still imports correctly
- Gmail reconciliation still removes stale unread-Inbox mismatches
- explicit rules still auto-process during sync
- duplicate-rule prevention still works

### Live Gmail safety tests

- modify-capable Gmail accounts still preserve `UNREAD`
- no Gmail Trash
- no delete
- `Soft Trash` still means `Fynish/Trash` + remove `INBOX`

### Mock harness tests

- mock accounts still sync
- synthetic inject tools still work
- queue and rule tests still work without live Gmail

### Early scaling sanity checks

This refactor does not need full load testing, but it should preserve:

- bounded sync per account
- stable uniqueness constraints for imported messages
- efficient lookups for queue and processed-message views
- compatibility with future retention policies

## Acceptance criteria

This refactor is complete when:

1. a local placeholder `user` exists and owns all current resources
2. every current account is represented as a `mail_account`
3. messages are keyed by `mail_account_id` and provider-neutral message ids
4. rules are no longer structurally global-only
5. provider connections are no longer Gmail-table-specific
6. the current UI still works without major behavior regression
7. real Gmail read/write flows still pass validation
8. current testing infrastructure passes against the refactored model
9. the codebase is structurally ready for hosted auth and second-provider work

## Proposed implementation phases

### Phase 1: Schema introduction

Deliver:

- new tables
- migration utilities
- backfill script or startup migration path

### Phase 2: Read-path refactor

Deliver:

- accounts service on `mail_accounts`
- review queue reads on `mail_account_id`
- rules reads on user/account scope

### Phase 3: Provider abstraction

Deliver:

- adapter interface
- Gmail adapter
- planner/executor integration through adapter

### Phase 4: Write-path cutover

Deliver:

- sync writes use new keys
- action logs use new keys
- quick rules and bulk rules use new scope model

### Phase 5: Cleanup and stabilization

Deliver:

- legacy-path removal where safe
- documentation refresh
- migration and validation scripts

## Key risks

### Risk 1: Silent data migration bugs

Mitigation:

- migration tests
- snapshot comparisons before/after
- explicit row-count and uniqueness checks

### Risk 2: Breaking live Gmail flows

Mitigation:

- keep Gmail adapter behavior covered by current validation scripts
- run live read-only and controlled live-write checks after each cutover step

### Risk 3: Frontend breakage from schema-driven API changes

Mitigation:

- preserve response compatibility during the backend-first phase
- defer UI contract cleanup until after stability

### Risk 4: Over-refactoring too early

Mitigation:

- do not implement second provider in this phase
- do not implement hosted auth in this phase
- keep scope tightly focused on foundations

### Risk 5: Ignoring normal growth too long

Mitigation:

- design for dozens of users now
- avoid storing more message content than the product really needs
- keep audit/history tables queryable and retention-friendly

## Recommended immediate next deliverables

The best first implementation steps are:

1. write a concrete schema migration plan from current tables to `users`, `mail_accounts`, and `provider_connections`
2. introduce provider-neutral message/account models in Python
3. refactor rules and review queue reads to use ids instead of email strings
4. add migration-focused test coverage before touching live Gmail execution paths

## Decision summary

This first refactor should be treated as a backend foundation project.

It should preserve the existing product while changing the system from:

- single-operator
- Gmail-shaped
- email-string-joined

into:

- ownership-aware
- provider-ready
- id-based and migration-friendly

That is the right foundation for the later Google Cloud, multi-user, and non-Gmail phases.
