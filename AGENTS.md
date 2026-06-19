# AGENTS.md

This file gives coding agents a shared operating guide for working in the public Fynish Mail repository.

Fynish Mail is an open Gmail triage app in active V1 development. The product centers on an explainable review queue, reusable rules, staged and reversible Gmail actions, processed-mail history, and optional AI-assisted digest features.

## First Read

Before editing, read:

1. `README.md`
2. `docs/FYNISH_FUNCTIONAL_GUIDE.md`
3. `docs/testing/TESTING_STRATEGY.md`

For feature-specific work, also read the relevant implementation spec in `docs/`.

## Public Repo Boundary

This is the public development repo. Keep it safe for public collaboration.

Do not add:

- real `.env` files
- Google OAuth credential JSON
- Gmail token files
- OpenAI API keys
- local database files or backups
- private account data
- private VM, billing, deployment, or live-operations details

If a task appears to require private operational context, stop and ask the maintainer to provide a sanitized public version or move the work to the private operations repo.

## Development Commands

Backend:

```bash
make install-test
make test
make validate
make check
```

Frontend:

```bash
cd frontend
npm install
npm run build
node --test auth.test.mjs
```

Use mock data first. Real Gmail validation requires developer-owned local OAuth setup and should not introduce secrets into the repo.

## Working Style

- Prefer small, reviewable changes.
- Read the existing service and test patterns before adding abstractions.
- Keep Gmail safety semantics intact: no permanent delete, no direct Gmail Trash, staged commits where applicable, and reversible/auditable actions.
- Add or update tests when behavior changes.
- Update docs when feature behavior, setup, or safety expectations change.
- Do not mix unrelated cleanup into feature work.

## Collaboration Through GitHub

Use GitHub issues and pull requests as the coordination layer between humans and agents.

For planning work:

- turn broad ideas into small issue drafts
- include scope, non-goals, acceptance criteria, and validation expectations
- keep private deployment details out of public issues

For implementation work:

- reference the issue or spec being implemented
- describe the slice completed
- list commands run and any test gaps
- avoid claiming live Gmail or VM validation unless it was actually performed by someone with appropriate credentials

## Future Platform Work

The next large direction is native platform planning, likely macOS first and iOS later. Start with architecture boundary work before implementation:

- what remains backend-owned
- what becomes shared API/client contract
- what is web-specific
- what is native macOS or iOS UI
- how OAuth, reconnect validation, and token ownership should work

Good first planning issue:

```text
Define native platform architecture boundary for Fynish
```

Suggested labels:

```text
platform, architecture, planning, security
```

