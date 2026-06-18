# Local Quickstart

## Purpose

This guide is the fastest path to running Fynish on your own machine.

Recommended first-run path:

- backend with local SQLite
- frontend with Vite
- Gmail OAuth after the app is already running

If you only want to explore the UI first, local development still includes a mock-account harness. The normal product path starts with a real Gmail connection.

## Requirements

You should have:

- Python 3.11 or newer
- Node.js 20 or newer
- npm

Optional later:

- your own Google OAuth client credentials if you want real Gmail access

## 1. Clone the project

```bash
git clone <your-fynish-repo-url>
cd Fynish-Mail-Screening
```

## 2. Start the backend

From the project root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
uvicorn app.main:app --app-dir backend --reload
```

Backend default URL:

- [http://127.0.0.1:8000](http://127.0.0.1:8000)

Default local behavior from `backend/.env.example`:

- SQLite database in `backend/data/fynish.sqlite3`
- mock-account seeding available for local development
- Gmail writes disabled

## 3. Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL:

- [http://127.0.0.1:5173](http://127.0.0.1:5173)

## 4. Explore the app

At this point you can already use Fynish locally.

With the default local config:

- mock accounts are available through the local development harness
- no Gmail credentials are required
- no live Gmail writes will occur

This is useful for understanding the queue, rules, processed-mail history, and recover flow without touching real Gmail.

## 5. Connect a real Gmail account later

If you want real Gmail access after the local app is working, create your own Google OAuth client credentials and keep them local-only. The root README summarizes the expected local credential path and Git hygiene.

Recommended progression:

1. run locally and inspect the development harness if you want sample data
2. connect Gmail through the normal `Connect Gmail` path
3. use the queue, Rules, Processed Mail, and Recover flows on one message at a time

## Helpful local commands

Restart both dev servers:

```bash
make restart-dev
```

Run the backend tests:

```bash
make test
```

Run the main local validation bundle:

```bash
make validate
```

## What to read next

Product behavior:

- [docs/FYNISH_FUNCTIONAL_GUIDE.md](docs/FYNISH_FUNCTIONAL_GUIDE.md)

Agent-assisted exploration:

- Ask a coding agent to read the README, functional guide, and testing strategy, then summarize the current architecture before making changes.
