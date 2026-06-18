# Multi-User Readiness Implementation Plan

## Purpose

This document defines the concrete implementation plan required to move Fynish from its current **single-user hosted workspace** model to a **true multi-user** application model.

Today, Fynish has important pieces of the foundation in place:

- hosted frontend auth exists
- hosted backend and scheduler exist
- `users`, `mail_accounts`, and `provider_connections` exist in the schema

But the active runtime still behaves like a single shared workspace. The main goal of this plan is to finish the runtime and operational refactor needed before inviting multiple real users.

## Current Assessment

Fynish is now **much closer to multi-user readiness** than when this plan was first written.

Completed so far:

- backend current-user plumbing is in place
- user-scoped reads are in place
- user-scoped writes and ownership checks are in place
- hosted runtime no longer silently depends on the default shared local owner
- the main hosted runtime paths now prefer `mail_accounts` and `provider_connections`
- hosted scheduled sync now runs in per-user mode instead of the old global sweep

What still remains before a true invited-user beta:

- finish the manual side of the Phase 7 isolation proof
- continue the small two-login pretend-friend beta with separate real Gmail-connected user workspaces
- only after that, invite one or two real outside users

So the current state is best described as:

- backend/runtime foundation: largely ready
- automated multi-user isolation coverage: in place
- hosted second-user Gmail connection path: working
- hosted second-user live Gmail write path: working
- real-world multi-user beta confidence: not yet complete

## Goal

Deliver a multi-user-safe backend and hosted runtime where:

- every signed-in user resolves to a first-class backend user
- every visible account, message, rule, setting, and action is ownership-scoped
- scheduler-driven sync and reminders operate per user
- users cannot see or mutate each other’s data
- existing single-user behavior remains stable during the transition

## Non-Goals

This plan does not attempt to solve:

- public self-serve signup
- billing, plans, or organizations
- role-based admin tooling
- team/shared inbox collaboration
- support for multiple mail providers beyond current Gmail-oriented flows

## Phase 1: Backend Current-User Plumbing

### Objective

Establish a real backend notion of the signed-in user and pass it through all API requests.

### Why this comes first

Without backend user context, the current hosted login only gates entry to the app. It does not make the API multi-user-safe.

### Work

1. Define a backend request user model.
2. Add a backend dependency/helper that resolves the current signed-in user from trusted request headers or a verified session signal from the frontend proxy.
3. Decide the contract between hosted frontend and backend:
   - likely user email plus a trusted service-to-service assertion from the frontend proxy
4. Create a helper such as:
   - `get_current_user()`
   - `get_current_user_id()`
5. Ensure local development still works with a safe fallback strategy:
   - local-only default user may remain for dev mode only
   - hosted mode must not silently fall back to the default shared user

### Deliverables

- backend current-user resolution in hosted mode
- explicit dev-mode fallback policy
- tests for authenticated and unauthenticated API access

### Exit Criteria

- hosted API requests resolve to a real backend user
- hosted requests cannot silently use the default local owner

## Phase 2: Scope All Reads by User

### Objective

Make all user-visible reads ownership-aware.

### Target Areas

- accounts
- review queue
- processed mail
- rules
- reminder summary
- notification settings

### Work

1. Update service functions to accept `user_id` or a current-user object.
2. Filter account queries by user ownership through `mail_accounts.user_id`.
3. Filter message queries through owned `mail_account_id`.
4. Filter rules by `rules.user_id` and, where relevant, `mail_account_id`.
5. Filter processed mail and action history by owned messages/accounts.
6. Filter reminder summaries by owned accounts only.
7. Ensure notification settings always read from `notification_settings_by_user` for the current user.

### Deliverables

- scoped read paths across all major views
- no global “show me everything” queries in user-facing runtime paths

### Exit Criteria

- one user can only see their own accounts, queue, rules, processed mail, and settings

## Phase 3: Scope All Writes and Mutations by Ownership

### Objective

Ensure every action only affects resources owned by the current user.

### Target Areas

- connect/disable account
- refresh/sync unread
- apply queue action
- live Gmail action execution
- bulk apply
- recover processed message
- create/update/delete rule
- update notification settings

### Work

1. Require ownership checks before every message mutation.
2. Require ownership checks before account mutations.
3. Require ownership checks before rule updates/deletes.
4. Ensure message lookup by `message_id` alone is not enough; it must also verify the message belongs to one of the current user’s accounts.
5. Ensure bulk actions validate ownership for every item in the request.
6. Add safe 403/404 behavior for foreign-resource access attempts.

### Deliverables

- ownership-safe mutation layer
- consistent authorization failure behavior

### Exit Criteria

- user A cannot act on, recover, disable, or modify anything owned by user B

## Phase 4: Remove Runtime Dependence on the Default Shared User

### Objective

Stop treating the seeded default user as the normal hosted runtime path.

### Why this matters

The default local owner should remain a migration/dev compatibility tool, not the active hosted application model.

### Work

1. Audit all calls to `_ensure_default_user()` and similar default-user helpers.
2. Split dev/bootstrap behavior from hosted runtime behavior.
3. Keep default-user seeding only for:
   - local dev
   - migration/backfill
   - explicit fallback test fixtures
4. Prevent hosted requests from implicitly creating or using the shared default owner.

### Deliverables

- clear separation between local bootstrap logic and hosted user runtime logic

### Exit Criteria

- hosted multi-user operation no longer depends on `DEFAULT_LOCAL_OWNER_EMAIL`

## Phase 5: Finish Runtime Migration Off Legacy Global Account Paths

### Objective

Move active runtime behavior off legacy tables and email-based joins wherever possible.

### Legacy Areas Still Active

- `accounts`
- `gmail_account_connections`
- `messages.account_email` as a join key
- `rules.account_email`
- global account lookups by email address

### Work

1. Make `mail_accounts` and `provider_connections` the primary runtime source of truth.
2. Prefer `mail_account_id` over `account_email` in message/rule/action paths.
3. Prefer `provider_connections` over `gmail_account_connections` in runtime provider access.
4. Leave legacy columns/tables in place temporarily if needed for compatibility, but stop relying on them for hosted behavior.
5. Update recovery, reminders, sync, and processed mail to use normalized ownership-aware joins.

### Deliverables

- active hosted runtime primarily uses normalized ownership-aware tables

### Exit Criteria

- runtime is no longer meaningfully coupled to legacy global account structures

## Phase 6: User-Scoped Scheduler and Background Work

### Objective

Ensure always-on hosted behavior runs per user, not as a global workspace sweep.

### Target Areas

- scheduled Gmail sync
- reminder summary generation
- future reminders/notifications

### Work

1. Update scheduled sync to iterate through enabled accounts grouped by owning user.
2. Make sync summary and logs user-aware.
3. Ensure reminder summary reads only the current user’s accounts in user-facing API paths.
4. Design future scheduled reminders so they send per-user, not globally.

### Deliverables

- scheduler-safe multi-user background processing

### Exit Criteria

- background work does not merge or expose cross-user state

## Phase 7: Multi-User Test Matrix

### Objective

Prove isolation rather than assuming it.

### Required Tests

1. User A and user B each have at least one separate mail account.
2. User A cannot see user B’s accounts.
3. User A cannot see user B’s review queue.
4. User A cannot see user B’s processed mail.
5. User A cannot modify user B’s messages.
6. User A cannot recover user B’s messages.
7. Rules created by user A do not affect user B.
8. Notification settings remain isolated per user.
9. Scheduled sync only updates messages for the accounts it is supposed to process.
10. Hosted auth path maps the right signed-in user to the right backend user record.

### Deliverables

- integration coverage for cross-user isolation
- at least one hosted validation script or manual validation checklist

### Current implementation status

Automated coverage now exists for:

1. user-scoped backend current-user resolution
2. user-scoped reads across:
   - accounts
   - queue
   - processed mail
   - rules
   - reminders
   - notification settings
3. user-scoped mutations across:
   - message actions
   - recovery
   - rule updates/deletes
   - account disable
   - notification settings updates
4. user-local rule behavior during sync
5. scheduler-style per-user sync aggregation and queue isolation

Hosted manual progress now exists for:

1. separate hosted sign-in as a second user
2. hosted Gmail web OAuth connection for that second user
3. modify-capable Gmail account ownership under the second user
4. hosted unread Inbox sync into the second user’s review queue
5. hosted live Gmail write execution for the second user

Manual validation still recommended before an invited beta:

1. sign in as the primary user and confirm only the primary user’s accounts and queue are visible
2. sign in as a second Google account and connect only that user’s Gmail account
3. confirm neither user can see the other user’s queue, rules, processed mail, or settings
4. confirm scheduled sync updates both users independently without cross-user leakage
5. confirm one user’s rule creation does not alter the other user’s queue behavior

Recommended next milestone after this phase:

- continue a short operator-led “pretend friend” beta using two separate sign-ins and real Gmail-backed activity
- then move to a tiny real friend beta

Manual beta checklists are intentionally kept outside the public repository because they are operator-facing working notes.

### Exit Criteria

- the multi-user risk is proven down through tests, not just by inspection

## Phase 8: Limited Friend Beta

### Objective

Validate multi-user behavior with a small number of trusted real users before wider sharing.

### Work

1. Invite one or two close friends with separate Gmail accounts.
2. Test onboarding, sign-in, account connect, sync, rule creation, and live actions.
3. Watch for:
   - data leakage
   - wrong-account operations
   - confusing account/rule scope behavior
   - scheduler issues
4. Tighten logs and incident visibility during this phase.

### Deliverables

- real-user validation before broader exposure

### Exit Criteria

- trusted-user beta completes without cross-user data issues

## Recommended Implementation Order

1. Phase 1: Backend current-user plumbing
2. Phase 2: Scope all reads by user
3. Phase 3: Scope all writes by ownership
4. Phase 4: Remove runtime dependence on the default shared user
5. Phase 5: Finish runtime migration off legacy global account paths
6. Phase 6: User-scoped scheduler and background work
7. Phase 7: Multi-user test matrix
8. Phase 8: Limited friend beta

## Risks

### 1. Partial scoping is worse than obvious single-user behavior

If only some services are user-scoped, the app may appear correct while still leaking data in edge paths.

### 2. Legacy compatibility code may hide dangerous joins

Even after core services are fixed, older compatibility joins may still reintroduce cross-user behavior.

### 3. Scheduler behavior can quietly reintroduce shared state

Background work needs the same ownership rigor as interactive API flows.

### 4. Frontend auth is not enough by itself

The hosted login gate is valuable, but backend ownership enforcement is the real safety boundary.

## Success Criteria

Fynish is ready for multi-user use when:

- each signed-in user resolves to a real backend user
- every major read and write path is ownership-scoped
- scheduler operations are user-safe
- cross-user isolation is covered by integration tests
- at least a small trusted-user beta has succeeded without leakage or ownership bugs

## Suggested Immediate Next Step

Start with **Phase 1: Backend Current-User Plumbing**.

That phase creates the contract the rest of the system can build on. Without it, the other phases become harder to implement cleanly and easier to get subtly wrong.
