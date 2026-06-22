# Fynish Mail

![Fynish Mail masthead](docs/assets/fynish-mail-masthead-v2.png)

Fynish Mail is an open Gmail triage app in active V1 development, with an explainable queue, reusable rules, reversible actions, processed-mail history, and optional AI-assisted digest features.

It is an active V1 project: useful, real, and still evolving.

## What It Does

- Imports unread Inbox messages from connected Gmail accounts.
- Classifies messages into `Keep`, `Bulk`, `Junk`, `Trash`, or `Needs Review`.
- Lets the user review messages quickly from the Fynish Queue.
- Turns repeated decisions into sender, domain, or list rules.
- Keeps an audit trail in Processed Mail.
- Supports local development with mock data and synthetic test messages.
- Supports real Gmail OAuth when the developer supplies their own Google credentials.

## Project Status

Fynish is not a packaged SaaS product. It is a self-run prototype for technically comfortable users and contributors.

The safest first path is local development with mock data. Real Gmail use requires your own Google OAuth setup and local environment configuration.

## Stack

- Frontend: React, Vite, TypeScript
- Backend: FastAPI
- Local database: SQLite
- Optional database path: PostgreSQL
- Mail integration: Gmail API

## Quick Start

For the full setup path, start with:

- [docs/QUICKSTART_LOCAL.md](docs/QUICKSTART_LOCAL.md)
- [docs/FYNISH_FUNCTIONAL_GUIDE.md](docs/FYNISH_FUNCTIONAL_GUIDE.md)

Short version:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
uvicorn app.main:app --app-dir backend --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Backend runs at [http://127.0.0.1:8000](http://127.0.0.1:8000).
Frontend runs at [http://127.0.0.1:5173](http://127.0.0.1:5173).

## Development Commands

```bash
make install-test
make test
make validate
make check
make reset-db
make seed-mock-data
make inject-test-mail
make queue-snapshot
make compare-snapshot
```

Common meanings:

- `make test` runs the backend pytest suite.
- `make validate` runs the main V1 validation script.
- `make check` runs the main local regression bundle.
- `make reset-db` resets the local development database.
- `make inject-test-mail` injects synthetic messages into a mock account.
- `make compare-snapshot` compares mocked queue behavior against expected fixtures.

Frontend:

```bash
cd frontend
npm run build
node --test auth.test.mjs
```

## Working With Coding Agents

Fynish was developed with an agentic coding workflow in mind. The repo includes implementation specs, feature notes, focused tests, and local validation commands so a tool like Codex, Cursor, Claude Code, or another coding agent can orient itself quickly.

Coding agents should start with [AGENTS.md](AGENTS.md). For collaboration workflow, see [docs/AGENT_COLLABORATION_GUIDE.md](docs/AGENT_COLLABORATION_GUIDE.md).

Good starting prompts for an agent:

- "Read `README.md`, `docs/FYNISH_FUNCTIONAL_GUIDE.md`, and `docs/testing/TESTING_STRATEGY.md`, then summarize the current architecture."
- "Run the backend tests and frontend build, then tell me what fails."
- "Review `docs/ERROR_HANDLING_STRATEGY.md` and suggest the next safe implementation slice."
- "Use `docs/REVIEW_QUEUE_STAGED_COMMIT_IMPLEMENTATION_SPEC.md` to explain how staged queue commits work."

Recommended agent workflow:

1. Read the functional guide and relevant spec before editing.
2. Keep changes small and test-backed.
3. Run `make test` and `npm run build` from `frontend` before proposing a merge.
4. Never invent or commit real OAuth credentials, Gmail tokens, local databases, or `.env` files.

## Real Gmail Setup

Real Gmail use requires developer-owned OAuth credentials. Do not commit credential files or token files.

Expected local credential path:

```text
backend/google-credentials.json
```

Local secrets and runtime data are intentionally ignored by Git:

- `backend/.env`
- `backend/google-credentials.json`
- `backend/data/`
- Gmail token files
- local databases
- logs and build output

## Important Files

- Backend entry: [backend/app/main.py](backend/app/main.py)
- API routes: [backend/app/api/routes.py](backend/app/api/routes.py)
- Review queue service: [backend/app/services/review_queue.py](backend/app/services/review_queue.py)
- Classifier: [backend/app/services/classifier.py](backend/app/services/classifier.py)
- Processed mail service: [backend/app/services/processed_mail.py](backend/app/services/processed_mail.py)
- Mock data: [backend/app/data/mock_messages.py](backend/app/data/mock_messages.py)
- Frontend app: [frontend/src/App.tsx](frontend/src/App.tsx)
- Frontend styling: [frontend/src/App.css](frontend/src/App.css)

## Documentation

Good starting points:

- [docs/FYNISH_FUNCTIONAL_GUIDE.md](docs/FYNISH_FUNCTIONAL_GUIDE.md)
- [docs/AGENT_COLLABORATION_GUIDE.md](docs/AGENT_COLLABORATION_GUIDE.md)
- [docs/ACCOUNT_AUTHORIZATION_USE_CASES.md](docs/ACCOUNT_AUTHORIZATION_USE_CASES.md)
- [docs/REVIEW_QUEUE_STAGED_COMMIT_IMPLEMENTATION_SPEC.md](docs/REVIEW_QUEUE_STAGED_COMMIT_IMPLEMENTATION_SPEC.md)
- [docs/AUTO_KEEP_QUEUE_VISIBILITY_IMPLEMENTATION_SPEC.md](docs/AUTO_KEEP_QUEUE_VISIBILITY_IMPLEMENTATION_SPEC.md)
- [docs/SPAM_RESCUE_IMPLEMENTATION_SPEC.md](docs/SPAM_RESCUE_IMPLEMENTATION_SPEC.md)
- [docs/ERROR_HANDLING_STRATEGY.md](docs/ERROR_HANDLING_STRATEGY.md)
- [docs/testing/TESTING_STRATEGY.md](docs/testing/TESTING_STRATEGY.md)

## Security Notes

- Never commit `.env` files.
- Never commit Google OAuth credential JSON files.
- Never commit Gmail token files.
- Never commit local database files or backups.
- Use mock data first when exploring the app.

## License

MIT. See [LICENSE](LICENSE).
