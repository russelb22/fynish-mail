# Foundation Refactor Implementation Tickets

## Purpose

This document breaks the foundation refactor into concrete implementation tickets.

It is meant to bridge the gap between:

- [docs/FUTURE_PLATFORM_ROADMAP.md](docs/FUTURE_PLATFORM_ROADMAP.md)
- [docs/FOUNDATION_REFACTOR_SPEC.md](docs/FOUNDATION_REFACTOR_SPEC.md)
- [docs/FOUNDATION_SCHEMA_MIGRATION_PLAN.md](docs/FOUNDATION_SCHEMA_MIGRATION_PLAN.md)

The goal is to create a practical build order for the first refactor.

## Planning assumptions

These tickets assume:

- SQLite remains active for this phase
- Gmail remains the only real provider for now
- the near-term product is intentionally Gmail-first even though the internal architecture should remain provider-aware
- current UI behavior should remain largely stable
- mock testing and live Gmail testing must continue to work during the transition

Additional product-direction assumption:

- future Gmail-client capabilities such as full message read, reply, reply-all, forward, and limited label/folder views should be possible without another schema rewrite

## Workstream summary

The work naturally breaks into five streams:

1. target schema introduction
2. migration and validation tooling
3. backend read-path refactor
4. backend write-path refactor
5. stabilization and cleanup

## Ticket list

### Ticket 1: Define target additive schema

**Goal**

Add the new ownership-aware and provider-neutral schema elements without breaking the current app.

**Primary files**

- [backend/app/db/schema.sql](backend/app/db/schema.sql)

**Deliverables**

- add `users`
- add `mail_accounts`
- add `provider_connections`
- add provider-neutral columns to `messages`
- add ownership/provider-neutral columns to `rules`
- add ownership/provider-neutral columns to `actions_log`
- add user-scoped notification settings structure
- reserve room for future Gmail-client features by keeping message/thread/provider metadata rich enough for:
  - full message read
  - thread-aware reply/reply-all
  - forward
  - limited label/folder-style navigation

**Acceptance criteria**

- app can still boot with the additive schema
- old tables still exist
- no existing startup path breaks

**Dependencies**

- none

---

### Ticket 2: Create migration utility script

**Goal**

Create a one-command migration utility that backfills the new schema from the current data model.

**Primary files**

- `scripts/migrate_foundation_schema.py` (new)
- `backend/app/db/` support utilities as needed

**Deliverables**

- additive schema application
- default local owner user creation
- `accounts` -> `mail_accounts` backfill
- `gmail_account_connections` -> `provider_connections` backfill
- `messages` backfill
- `rules` backfill
- `actions_log` backfill
- `notification_settings` backfill
- printed migration summary

**Acceptance criteria**

- script can run on a populated local database
- script can be rerun safely or detects prior completion clearly
- migration summary includes row counts and ownership mapping stats

**Dependencies**

- Ticket 1

---

### Ticket 3: Create migration validation script

**Goal**

Add a validation utility that proves the migration completed correctly.

**Primary files**

- `scripts/validate_foundation_migration.py` (new)

**Deliverables**

- row count validation
- foreign key validation
- duplicate/uniqueness validation
- queue compatibility validation
- rule compatibility validation
- actions log compatibility validation

**Acceptance criteria**

- validation script produces pass/fail output
- script catches missing `mail_account_id`, `user_id`, and `provider_message_id` backfills
- script can be included in the existing validation workflow later

**Dependencies**

- Ticket 2

---

### Ticket 4: Add migration-focused test fixtures

**Goal**

Protect the migration with repeatable test data and expected outcomes.

**Primary files**

- `backend/tests/fixtures/` additions
- `backend/tests/unit/` and/or `backend/tests/integration/` additions

**Deliverables**

- seeded pre-migration SQLite fixture or fixture builder
- expected post-migration shape assertions
- representative data for:
  - mock accounts
  - real Gmail accounts
  - rules
  - action logs
  - notification settings

**Acceptance criteria**

- migration tests can run without live Gmail
- fixture includes at least one modify-capable Gmail account scenario

**Dependencies**

- Ticket 1

---

### Ticket 5: Add automated migration tests

**Goal**

Add backend tests that verify the migration/backfill logic works and preserves behavior.

**Primary files**

- `backend/tests/integration/test_foundation_migration.py` (new)

**Deliverables**

- one default local user is created
- all accounts become `mail_accounts`
- all messages gain `mail_account_id`
- all rules gain `user_id`
- all action logs gain provider-neutral identifiers
- notification settings become user-owned

**Acceptance criteria**

- tests pass repeatedly on fixture data
- tests fail meaningfully on missing backfills

**Dependencies**

- Ticket 2
- Ticket 3
- Ticket 4

---

### Ticket 6: Introduce provider-neutral Python data/service models

**Goal**

Start decoupling backend logic from Gmail-shaped naming even before every service is rewritten.

**Primary files**

- `backend/app/services/`
- optional new model/helper modules

**Deliverables**

- provider-neutral account/message helper structures
- central mapping helpers for:
  - `account_email` -> `mail_account_id`
  - `gmail_message_id` -> `provider_message_id`
  - Gmail labels -> provider labels
- service/model boundaries that still let Gmail expose richer capabilities first, such as:
  - full message/thread fetch
  - draft/send paths later
  - label-centric mailbox views later

**Acceptance criteria**

- new helpers are used by subsequent service refactors
- no product behavior change yet

**Dependencies**

- Ticket 2

---

### Ticket 7: Refactor accounts service to `mail_accounts`

**Goal**

Make account-oriented backend code read primarily from `mail_accounts` and `provider_connections`.

**Primary files**

- [backend/app/services/accounts.py](backend/app/services/accounts.py)

**Deliverables**

- account list/read paths use `mail_accounts`
- Gmail connection metadata uses `provider_connections`
- compatibility response still exposes fields the frontend expects

**Acceptance criteria**

- Accounts page still works
- mock and real Gmail accounts still appear correctly
- modify-capable labeling still works

**Dependencies**

- Ticket 2
- Ticket 6

---

### Ticket 8: Refactor rules service to user/account ownership

**Goal**

Move rules off email-based structural scoping and onto ownership-aware ids.

**Primary files**

- [backend/app/services/rules.py](backend/app/services/rules.py)

**Deliverables**

- rules read/write through `user_id`
- optional `mail_account_id` support
- duplicate-rule reuse/re-enable behavior preserved
- match count and last matched behavior preserved

**Acceptance criteria**

- current Rules page behavior is preserved
- exact duplicate prevention still works
- auto-applied rule matches still work during sync

**Dependencies**

- Ticket 2
- Ticket 6

---

### Ticket 9: Refactor review queue reads to `mail_account_id`

**Goal**

Move queue generation and reconciliation away from `account_email` joins.

**Primary files**

- [backend/app/services/review_queue.py](backend/app/services/review_queue.py)

**Deliverables**

- queue reads use `mail_account_id`
- message uniqueness uses `(mail_account_id, provider_message_id)`
- queue grouping still returns familiar account-facing payloads
- reconciliation still works for real Gmail accounts

**Acceptance criteria**

- visible queue matches pre-refactor behavior
- stale-message reconciliation still works
- rule auto-processing still works

**Dependencies**

- Ticket 2
- Ticket 6
- Ticket 7
- Ticket 8

---

### Ticket 10: Introduce provider adapter interface and Gmail adapter

**Goal**

Create the first real provider abstraction boundary while keeping Gmail as the only implementation.

**Primary files**

- [backend/app/services/gmail_readonly.py](backend/app/services/gmail_readonly.py)
- [backend/app/services/gmail_write_planner.py](backend/app/services/gmail_write_planner.py)
- [backend/app/services/gmail_write_executor.py](backend/app/services/gmail_write_executor.py)

**Deliverables**

- `MailProviderAdapter` interface
- `GmailProviderAdapter` implementation
- Gmail read paths routed through adapter
- Gmail write planning/execution routed through adapter
- adapter contract designed so Gmail can later add richer client operations without another major abstraction change, for example:
  - fetch full message/thread
  - create draft
  - send reply/reply-all
  - forward message
  - list mailbox/label views

**Acceptance criteria**

- no regression in Gmail read-only validation
- no regression in Gmail write dry-run/live validation

**Dependencies**

- Ticket 6

---

### Ticket 11: Refactor sync/import write path

**Goal**

Make sync/import write new rows and updates using provider-neutral and ownership-aware fields.

**Primary files**

- [backend/app/services/review_queue.py](backend/app/services/review_queue.py)
- Gmail/provider adapter code as needed

**Deliverables**

- message import writes `mail_account_id`
- message import writes provider-neutral ids/labels
- sync no longer depends primarily on `account_email`
- imported message storage remains compatible with future Gmail full-read views, not only triage previews

**Acceptance criteria**

- unread Gmail import still works
- repeat sync still avoids duplicates
- mock inject and live insert tests still work

**Dependencies**

- Ticket 9
- Ticket 10

---

### Ticket 12: Refactor action log write path

**Goal**

Write audit rows using the new ownership-aware and provider-neutral fields.

**Primary files**

- [backend/app/services/review_queue.py](backend/app/services/review_queue.py)
- Gmail/provider adapter code as needed

**Deliverables**

- `mail_account_id`
- `provider_message_id`
- `provider_labels_added_json`
- `provider_labels_removed_json`
- `message_id` when resolvable

**Acceptance criteria**

- action audit remains readable
- live Gmail write tests still pass

**Dependencies**

- Ticket 2
- Ticket 10
- Ticket 11

---

### Ticket 13: Refactor notification settings ownership

**Goal**

Move notification settings from singleton storage to user-owned storage without changing visible behavior.

**Primary files**

- [backend/app/services/notification_settings.py](backend/app/services/notification_settings.py)

**Deliverables**

- settings read/write through default owner user
- compatibility API behavior preserved

**Acceptance criteria**

- Settings page still works
- reminder summary still works

**Dependencies**

- Ticket 2

---

### Ticket 14: Full regression pass on existing validation suite

**Goal**

Ensure the current product still behaves the same after the refactor.

**Primary files**

- existing test suite
- existing scripts under `scripts/`

**Deliverables**

- backend unit/integration tests updated as needed
- validation scripts updated as needed
- live Gmail validation rerun
- confirm the new foundation does not block later Gmail-client work on:
  - thread reads
  - richer compose/send scopes
  - label/folder-style navigation

**Acceptance criteria**

- existing `make test` passes
- existing validation scripts pass
- Gmail read-only validation passes
- Gmail write dry-run/live validation passes

**Dependencies**

- Tickets 7 through 13

---

### Ticket 15: Legacy-path cleanup plan

**Goal**

Prepare the project for removal of legacy Gmail-shaped schema elements after stabilization.

**Primary files**

- docs only at first

**Deliverables**

- list of removable legacy columns/tables
- cutover readiness checklist
- rollback note

**Acceptance criteria**

- no legacy column is removed in this ticket
- cleanup plan is ready for a later dedicated pass

**Deliverable status**

- captured in [docs/FOUNDATION_LEGACY_CLEANUP_PLAN.md](docs/FOUNDATION_LEGACY_CLEANUP_PLAN.md)

**Dependencies**

- Ticket 14

## Recommended execution order

Recommended build order:

1. Ticket 1
2. Ticket 2
3. Ticket 3
4. Ticket 4
5. Ticket 5
6. Ticket 6
7. Ticket 7
8. Ticket 8
9. Ticket 9
10. Ticket 10
11. Ticket 11
12. Ticket 12
13. Ticket 13
14. Ticket 14
15. Ticket 15

## Recommended first implementation slice

If we want to start coding this refactor in a safe, high-value way, the best first slice is:

1. Ticket 1: define target additive schema
2. Ticket 2: create migration utility script
3. Ticket 3: create migration validation script
4. Ticket 5: add automated migration tests

That gives us a safe foundation before touching live Gmail execution paths.

## Decision summary

The first refactor should begin with schema and migration safety work, not service rewrites.

That sequence gives us:

- a reversible migration path
- testable ownership foundations
- less risk to the currently working Gmail product
- a provider-aware internal model that still allows the product to go deeper on Gmail before broadening to other providers
