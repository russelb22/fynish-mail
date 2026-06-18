import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

from app.core.config import DATA_DIR, DATABASE_PATH, DB_MODE
from app.db.runtime import get_engine


ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("mail_account_id", "INTEGER"),
        ("provider_message_id", "TEXT"),
        ("provider_thread_id", "TEXT"),
        ("provider_labels_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("recovery_pending", "INTEGER NOT NULL DEFAULT 0"),
        ("queue_source", "TEXT NOT NULL DEFAULT 'classifier'"),
        ("queue_source_detail", "TEXT"),
    ],
    "rules": [
        ("user_id", "INTEGER"),
        ("mail_account_id", "INTEGER"),
        ("created_from_mail_account_id", "INTEGER"),
    ],
    "mail_accounts": [
        ("high_confidence_auto_clean_enabled", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "actions_log": [
        ("message_id", "INTEGER"),
        ("mail_account_id", "INTEGER"),
        ("provider_message_id", "TEXT"),
        ("provider_labels_added_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("provider_labels_removed_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("action_source", "TEXT NOT NULL DEFAULT 'manual'"),
    ],
    "notification_settings_by_user": [
        ("digest_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("digest_time", "TEXT NOT NULL DEFAULT '17:00'"),
        ("ai_digest_summary_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ],
}

POSTGRES_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("queue_source", "TEXT NOT NULL DEFAULT 'classifier'"),
        ("queue_source_detail", "TEXT"),
    ],
}

STAGED_COMMIT_REQUESTS_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS staged_commit_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES users(id)
)
"""

STAGED_COMMIT_REQUESTS_POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS staged_commit_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, idempotency_key)
)
"""

AI_DIGEST_ATTENTION_NOTES_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS ai_digest_domain_attention_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, domain),
    FOREIGN KEY(user_id) REFERENCES users(id)
)
"""

AI_DIGEST_ATTENTION_NOTES_POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS ai_digest_domain_attention_notes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    domain TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

AI_DIGEST_ATTENTION_NOTES_POSTGRES_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_digest_attention_notes_user_domain_lower
ON ai_digest_domain_attention_notes (user_id, lower(domain))
"""

WRITING_STYLE_CARDS_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS writing_style_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mail_account_id INTEGER,
    account_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    source_provider TEXT NOT NULL DEFAULT 'manual',
    sample_start_date TEXT,
    sample_end_date TEXT,
    sample_bucket_count INTEGER NOT NULL DEFAULT 0,
    sampled_message_count INTEGER NOT NULL DEFAULT 0,
    sampled_word_count INTEGER NOT NULL DEFAULT 0,
    style_card_markdown TEXT NOT NULL,
    style_card_json TEXT,
    user_edited INTEGER NOT NULL DEFAULT 0,
    edited_at TEXT,
    generator_model TEXT,
    generated_at TEXT NOT NULL,
    approved_at TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(mail_account_id) REFERENCES mail_accounts(id)
)
"""

WRITING_STYLE_CARDS_POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS writing_style_cards (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    mail_account_id BIGINT REFERENCES mail_accounts(id),
    account_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    source_provider TEXT NOT NULL DEFAULT 'manual',
    sample_start_date TEXT,
    sample_end_date TEXT,
    sample_bucket_count INTEGER NOT NULL DEFAULT 0,
    sampled_message_count INTEGER NOT NULL DEFAULT 0,
    sampled_word_count INTEGER NOT NULL DEFAULT 0,
    style_card_markdown TEXT NOT NULL,
    style_card_json JSONB,
    user_edited INTEGER NOT NULL DEFAULT 0,
    edited_at TEXT,
    generator_model TEXT,
    generated_at TEXT NOT NULL,
    approved_at TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

WRITING_STYLE_CARDS_POSTGRES_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_writing_style_cards_user_account_status
ON writing_style_cards (user_id, lower(account_email), status)
"""

AUTO_RESPONSE_SENDS_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS auto_response_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    mail_account_id INTEGER,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'gmail',
    account_email TEXT NOT NULL,
    to_email TEXT NOT NULL,
    cc_email TEXT,
    bcc_email TEXT,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    gmail_thread_id TEXT,
    gmail_sent_message_id TEXT,
    gmail_response_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(message_id) REFERENCES messages(id),
    FOREIGN KEY(mail_account_id) REFERENCES mail_accounts(id)
)
"""

AUTO_RESPONSE_SENDS_POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS auto_response_sends (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    mail_account_id BIGINT REFERENCES mail_accounts(id) ON DELETE SET NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'gmail',
    account_email TEXT NOT NULL,
    to_email TEXT NOT NULL,
    cc_email TEXT,
    bcc_email TEXT,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    gmail_thread_id TEXT,
    gmail_sent_message_id TEXT,
    gmail_response_json JSONB,
    error_message TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(user_id, idempotency_key)
)
"""


def _ensure_additive_columns(conn: sqlite3.Connection) -> None:
    for table_name, columns in ADDITIVE_COLUMNS.items():
        existing_columns = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, definition in columns:
            if column_name in existing_columns:
                continue
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )


def _ensure_postgres_additive_columns(conn) -> None:
    for table_name, columns in POSTGRES_ADDITIVE_COLUMNS.items():
        existing_columns = {
            row[0]
            for row in conn.exec_driver_sql(
                f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = '{table_name}'
                """
            )
        }
        for column_name, definition in columns:
            if column_name in existing_columns:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {definition}"
            )


def ensure_database() -> None:
    if DB_MODE == "postgres":
        with get_engine().begin() as conn:
            conn.execute(text("SELECT 1"))
            conn.exec_driver_sql(STAGED_COMMIT_REQUESTS_POSTGRES_DDL)
            conn.exec_driver_sql(AI_DIGEST_ATTENTION_NOTES_POSTGRES_DDL)
            conn.exec_driver_sql(AI_DIGEST_ATTENTION_NOTES_POSTGRES_INDEX_DDL)
            conn.exec_driver_sql(WRITING_STYLE_CARDS_POSTGRES_DDL)
            conn.exec_driver_sql(WRITING_STYLE_CARDS_POSTGRES_INDEX_DDL)
            conn.exec_driver_sql(AUTO_RESPONSE_SENDS_POSTGRES_DDL)
            _ensure_postgres_additive_columns(conn)
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).with_name("schema.sql")
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.executescript(schema_path.read_text())
        conn.execute(STAGED_COMMIT_REQUESTS_SQLITE_DDL)
        conn.execute(AI_DIGEST_ATTENTION_NOTES_SQLITE_DDL)
        conn.execute(WRITING_STYLE_CARDS_SQLITE_DDL)
        conn.execute(AUTO_RESPONSE_SENDS_SQLITE_DDL)
        _ensure_additive_columns(conn)
        conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
