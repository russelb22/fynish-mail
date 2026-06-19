# Agent Collaboration Guide

This guide describes how people and coding agents should collaborate in the public Fynish Mail repository.

The goal is not to make agents autonomous owners of the project. The goal is to give agents enough shared context to produce smaller, safer, easier-to-review contributions.

## Collaboration Model

Use the public GitHub repository as the shared coordination surface:

- issues for planning and task boundaries
- pull requests for implementation review
- docs for durable decisions
- tests for behavioral confidence

Private live-instance operations should stay outside the public repo. Public issues and pull requests should discuss product behavior, architecture, local development, tests, and sanitized setup paths.

## Agent Onboarding Checklist

When an agent starts work, it should:

1. Read `AGENTS.md`.
2. Read `README.md`.
3. Read `docs/FYNISH_FUNCTIONAL_GUIDE.md`.
4. Read `docs/testing/TESTING_STRATEGY.md`.
5. Search `docs/` for the relevant implementation spec.
6. Inspect nearby code before proposing changes.
7. Run the smallest useful validation commands before reporting completion.

## Recommended Issue Shape

Good Fynish issues should be narrow enough for one focused implementation or planning pass.

Include:

- problem statement
- current behavior
- desired behavior
- non-goals
- files or docs likely involved
- acceptance criteria
- validation commands

For planning issues, the expected output is usually a `docs/` note, not code.

For implementation issues, the expected output should include tests or a clear explanation of why tests are not practical for that slice.

## Pull Request Expectations

Pull requests should include:

- a concise summary of the change
- the issue or spec being addressed
- commands run
- remaining risks or test gaps
- screenshots for meaningful UI changes

Avoid:

- unrelated formatting churn
- broad refactors hidden inside feature work
- adding new dependencies without explaining why
- changing Gmail action semantics without an explicit safety discussion

## Safety Rules

Fynish touches Gmail, so safety is part of the product design.

Agents should preserve these constraints unless a maintainer explicitly changes the product direction:

- no permanent Gmail delete
- no direct Gmail Trash behavior
- user-created rules should remain explainable
- staged queue changes should remain auditable and recoverable
- Gmail credential failures should be isolated to the affected account
- reconnect flows should reject the wrong Gmail address
- mock-data workflows should remain available for local development

## Public and Private Boundaries

Public repo work can include:

- product code
- local development setup
- generic OAuth setup guidance
- test strategy
- public implementation specs
- architecture notes
- issue planning

Public repo work should not include:

- real account identifiers beyond generic examples
- production database contents
- VM hostnames or private infrastructure details
- billing details
- private runbooks
- secrets, credentials, tokens, keys, or backups

When in doubt, write the public version as a generic pattern and ask the maintainer to keep operational specifics private.

## Suggested Native Platform Planning Sequence

For macOS and iOS planning, open issues in this order:

1. Define the native platform architecture boundary.
2. Define the first macOS product slice.
3. Define the iOS follow-on strategy.

The first issue should decide:

- backend-owned behavior
- shared API/client models
- web responsibilities
- macOS responsibilities
- iOS responsibilities
- OAuth and token ownership model
- reconnect and account-conflict validation
- API contract testing expectations

Avoid opening broad "build macOS app" or "build iOS app" issues before this boundary exists.

## Useful Starting Prompts

For repo orientation:

```text
Read AGENTS.md, README.md, docs/FYNISH_FUNCTIONAL_GUIDE.md, and docs/testing/TESTING_STRATEGY.md. Summarize the current product architecture, safety constraints, and likely next planning issue.
```

For issue drafting:

```text
Draft a small GitHub issue for the next Fynish platform planning slice. Include scope, non-goals, acceptance criteria, validation expectations, and public/private boundary notes.
```

For implementation:

```text
Read the relevant implementation spec, inspect the nearby code and tests, implement one focused slice, run the smallest useful validation commands, and report any remaining risks.
```

