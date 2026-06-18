# Database Abstraction Plan

## Purpose

Define the next engineering step after the PostgreSQL readiness review: how to move Fynish off a runtime contract that is hardwired to `sqlite3`.

Related public docs:

- [docs/FOUNDATION_REFACTOR_SPEC.md](docs/FOUNDATION_REFACTOR_SPEC.md)

## Problem statement

Today Fynish uses a single database access contract:

- [backend/app/db/database.py](backend/app/db/database.py)

That contract is tightly bound to:

- `sqlite3.connect(...)`
- `sqlite3.Row`
- file-path database configuration
- startup schema mutation with SQLite metadata introspection

This works well locally, but it blocks:

- PostgreSQL runtime support
- Cloud SQL deployment
- a clean migration tool story
- future pooling/session management

## Recommendation

Do **not** try to abstract the entire data layer with ad hoc wrappers around `sqlite3` alone.

Recommended direction:

1. introduce a database engine/session abstraction
2. move SQL execution onto SQLAlchemy Core
3. keep SQL text queries where practical at first
4. introduce migrations as a separate concern

This is the best balance because:

- Fynish already uses a lot of explicit SQL
- we do not need a full ORM rewrite
- SQLAlchemy Core can support both SQLite and PostgreSQL
- we can adopt it incrementally

## Target architecture

### Runtime DB layer

Introduce a DB runtime module that owns:

- engine creation
- connection lifecycle
- transaction scope
- SQLite vs PostgreSQL selection
- row access compatibility

Conceptually:

```text
config.py
  ->
db/runtime.py
  ->
SQLAlchemy engine / connection factory
  ->
service modules
```

### Migration layer

Separate schema migration concerns from runtime startup.

Conceptually:

```text
db/migrations/
  authoritative schema evolution

runtime startup
  no longer mutates schema in production
```

## What should stay the same initially

To keep risk low, the first abstraction phase should preserve:

- current service function signatures
- explicit SQL query style where practical
- row-like dict access patterns in services
- existing business logic

This should be an infrastructure refactor first, not a product-behavior rewrite.

## What should change first

### 1. Replace `sqlite3` connection ownership

Current pattern:
- services import `get_connection()` and receive raw SQLite connections

Target pattern:
- services import `get_connection()` or equivalent from a new runtime layer
- returned connection object should be SQLAlchemy-backed

Important goal:
- keep the usage shape familiar enough that service refactors are incremental

### 2. Replace `sqlite3.Row` assumptions

Current services assume:
- `row["column_name"]`

That is fine to preserve conceptually, but it should come from:
- SQLAlchemy row mappings
- or helper conversion to dict-like objects

### 3. Replace `lastrowid`

Current code relies heavily on:
- `cursor.lastrowid`

Target:
- explicit insert-and-return helpers
- `RETURNING id` on PostgreSQL
- compatible handling on SQLite while we transition

This should be centralized rather than scattered through service code.

### 4. Remove startup schema mutation from the runtime path

Current startup:
- `ensure_database()`
- applies schema script
- performs additive-column mutation

Target:
- local dev bootstrap can still initialize a DB
- hosted runtime should not perform ad hoc schema mutation at startup

## Proposed implementation phases

## Phase 1: Runtime abstraction scaffold

### Goal

Create a new DB runtime layer without changing business behavior yet.

### Deliverables

- new runtime module, likely:
  - `backend/app/db/runtime.py`
- engine initialization from config
- environment-driven backend DB mode:
  - SQLite locally
  - PostgreSQL later
- connection/transaction context manager using SQLAlchemy

### Acceptance criteria

- existing services can begin switching imports from `db.database` to the new runtime layer
- no product behavior change yet

## Phase 2: Insert helper abstraction

### Goal

Stop relying on raw `lastrowid`.

### Deliverables

- helper for insert-and-return-id behavior
- first services migrated:
  - accounts
  - rules
  - review queue write paths
  - action logging

### Acceptance criteria

- service code no longer reaches directly for cursor-specific identity semantics in the first migrated slices

## Phase 3: Metadata/bootstrap separation

### Goal

Separate runtime DB access from schema-management responsibilities.

### Deliverables

- runtime path no longer owns additive schema mutation for hosted scenarios
- local dev bootstrap path becomes explicit
- migration-managed schema direction becomes primary

### Acceptance criteria

- production-like startup can boot without trying to mutate schema automatically

## Phase 4: Service-by-service connection migration

### Goal

Move service modules from raw SQLite assumptions to the new DB layer.

### Recommended first migration order

1. `processed_mail`
2. `rules`
3. `notification_settings`
4. `accounts`
5. `review_queue`
6. `gmail_write_*`

Why this order:
- smaller read-oriented services first
- larger queue/write services later

## Recommended tool choice

### SQLAlchemy Core

Recommended for runtime DB abstraction because:

- supports both SQLite and PostgreSQL
- fits explicit SQL better than a forced ORM rewrite
- makes engine/transaction management much cleaner
- gives a sensible path to pooled cloud connections later

### Alembic

Recommended later for migration management because:

- common pairing with SQLAlchemy
- good fit once PostgreSQL becomes real

## What not to do

### Do not:

- rewrite the whole app into ORM models immediately
- convert every query to query-builder style before the runtime abstraction exists
- try to combine DB abstraction, PostgreSQL cutover, and token-storage redesign in one slice

That would add too much migration risk.

## Key compatibility requirements

The abstraction must preserve:

- current single-user local workflow
- current Gmail live-read/write behavior
- current tests where possible during transition
- current provider-aware foundation direction

## Immediate next implementation slice

Recommended next coding slice:

1. add a new DB runtime module
2. add environment-driven DB mode selection
3. create insert-return helpers
4. migrate one low-risk service to prove the pattern

Best first service to migrate:
- `processed_mail`

Why:
- read-oriented
- simpler query surface
- low product risk

## Success criteria for the abstraction milestone

We should consider the DB abstraction milestone successful when:

- at least one real service uses the new DB runtime
- insert-return handling is no longer directly `lastrowid`-dependent in that slice
- local SQLite still works
- the codebase has a clear path to PostgreSQL without runtime `sqlite3` lock-in
