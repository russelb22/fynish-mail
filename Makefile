PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
PIP := .venv/bin/pip

.PHONY: help install-test test test-e2e validate check reset-db seed-mock-data inject-test-mail smoke-api run-backend-postgres postgres-up postgres-smoke postgres-schema-apply google-oauth-config validate-gmail-db-tokens dedupe-provider-connections queue-snapshot compare-snapshot safety rules-flow reminders gmail-readonly gmail-write-dry-run restart-dev foundation-migrate foundation-check

help:
	@echo "Fynish project commands"
	@echo "  make install-test      Install backend test dependencies"
	@echo "  make test              Run backend pytest suite"
	@echo "  make test-e2e          Run Playwright UI smoke tests"
	@echo "  make validate          Run core V1 validation script"
	@echo "  make check             Run the main local regression bundle"
	@echo "  make reset-db          Reset the dev database to a clean seeded state"
	@echo "  make seed-mock-data    Sync mock messages into the current database"
	@echo "  make inject-test-mail  Inject synthetic test emails into a mock account"
	@echo "  make smoke-api         Run HTTP smoke tests against a running backend"
	@echo "  make run-backend-postgres  Run the backend against local PostgreSQL defaults"
	@echo "  make postgres-up       Start and bootstrap a local PostgreSQL instance for Fynish"
	@echo "  make postgres-smoke    Validate a running backend against local PostgreSQL"
	@echo "  make postgres-schema-apply  Apply the PostgreSQL bootstrap schema"
	@echo "  make google-oauth-config  Validate Google OAuth client config shape"
	@echo "  make validate-gmail-db-tokens  Validate Gmail access using DB-backed token blobs"
	@echo "  make dedupe-provider-connections  Collapse duplicate provider_connections rows"
	@echo "  make queue-snapshot    Print a readable queue snapshot"
	@echo "  make compare-snapshot  Compare current queue behavior to expected fixtures"
	@echo "  make safety            Validate V1 safety invariants"
	@echo "  make rules-flow        Validate quick-rule workflow"
	@echo "  make reminders         Validate reminder summary generation"
	@echo "  make gmail-readonly    Validate the Gmail read-only integration"
	@echo "  make gmail-write-dry-run  Print safe Gmail write plans without executing them"
	@echo "  make foundation-check  Run the broader foundation regression bundle"
	@echo "  make restart-dev       Restart backend and frontend dev servers"
	@echo "  make foundation-migrate  Backfill the ownership/provider-neutral schema"

install-test:
	$(PIP) install -r backend/requirements-dev.txt

test:
	$(PYTEST) backend/tests

test-e2e:
	cd frontend && npm run test:e2e

validate:
	$(PYTHON) scripts/validate_v1.py

check:
	$(PYTEST) backend/tests
	$(PYTHON) scripts/validate_v1.py
	$(PYTHON) scripts/validate_safety_invariants.py
	$(PYTHON) scripts/validate_rules_flow.py
	$(PYTHON) scripts/validate_reminder_summary.py
	$(PYTHON) scripts/compare_queue_snapshot.py

reset-db:
	$(PYTHON) scripts/reset_dev_db.py

seed-mock-data:
	$(PYTHON) scripts/seed_mock_data.py

inject-test-mail:
	$(PYTHON) scripts/inject_test_messages.py

smoke-api:
	$(PYTHON) scripts/smoke_test_api.py

run-backend-postgres:
	bash scripts/run_backend_postgres.sh

postgres-up:
	bash scripts/bootstrap_local_postgres.sh

postgres-smoke:
	$(PYTHON) scripts/validate_local_postgres.py

postgres-schema-apply:
	$(PYTHON) scripts/apply_postgres_schema.py

google-oauth-config:
	$(PYTHON) scripts/validate_google_oauth_config.py

validate-gmail-db-tokens:
	FYNISH_GMAIL_TOKEN_STORAGE_MODE=database $(PYTHON) scripts/validate_gmail_db_token_store.py

dedupe-provider-connections:
	$(PYTHON) scripts/deduplicate_provider_connections.py

queue-snapshot:
	$(PYTHON) scripts/print_queue_snapshot.py

compare-snapshot:
	$(PYTHON) scripts/compare_queue_snapshot.py

safety:
	$(PYTHON) scripts/validate_safety_invariants.py

rules-flow:
	$(PYTHON) scripts/validate_rules_flow.py

reminders:
	$(PYTHON) scripts/validate_reminder_summary.py

gmail-readonly:
	$(PYTHON) scripts/validate_gmail_readonly.py

gmail-write-dry-run:
	$(PYTHON) scripts/validate_gmail_write_dry_run.py

foundation-migrate:
	$(PYTHON) scripts/migrate_foundation_schema.py

foundation-check:
	$(PYTHON) scripts/validate_foundation_regression.py

restart-dev:
	bash scripts/restart_dev_servers.sh
