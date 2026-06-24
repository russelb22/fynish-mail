import os
from pathlib import Path
from urllib.parse import quote_plus


BASE_DIR = Path(__file__).resolve().parents[2]


def _getenv_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _getenv_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw.strip())


def _getenv_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return Path(raw.strip()).expanduser()


def _getenv_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _default_gmail_token_storage_mode(app_env: str) -> str:
    if app_env == "cloud":
        return "database"
    return "auto"


def _build_database_url(default_sqlite_url: str) -> str:
    explicit_url = os.getenv("FYNISH_DATABASE_URL")
    if explicit_url and explicit_url.strip():
        return explicit_url.strip()

    db_mode = os.getenv("FYNISH_DB_MODE", "sqlite").strip().lower()
    if db_mode != "postgres":
        return default_sqlite_url

    user = os.getenv("FYNISH_POSTGRES_USER", "").strip()
    password = os.getenv("FYNISH_POSTGRES_PASSWORD", "").strip()
    database = os.getenv("FYNISH_POSTGRES_DATABASE", "").strip()
    cloudsql_instance = os.getenv("FYNISH_CLOUDSQL_INSTANCE_CONNECTION_NAME", "").strip()
    host = os.getenv("FYNISH_POSTGRES_HOST", "").strip()
    port = os.getenv("FYNISH_POSTGRES_PORT", "5432").strip()

    if not (user and password and database):
        return default_sqlite_url

    quoted_user = quote_plus(user)
    quoted_password = quote_plus(password)

    if cloudsql_instance:
        return (
            f"postgresql+psycopg://{quoted_user}:{quoted_password}@/"
            f"{database}?host=/cloudsql/{cloudsql_instance}"
        )

    if host:
        return (
            f"postgresql+psycopg://{quoted_user}:{quoted_password}@"
            f"{host}:{port}/{database}"
        )

    return default_sqlite_url


APP_ENV = os.getenv("FYNISH_APP_ENV", "local").strip().lower()
DATA_DIR = _getenv_path("FYNISH_DATA_DIR", BASE_DIR / "data")
DATABASE_PATH = _getenv_path("FYNISH_SQLITE_DATABASE_PATH", DATA_DIR / "fynish.sqlite3")
DB_MODE = os.getenv("FYNISH_DB_MODE", "sqlite").strip().lower()
DATABASE_URL = _build_database_url(f"sqlite:///{DATABASE_PATH}")
MAX_SYNC_MESSAGES_PER_ACCOUNT = 100
BODY_PREVIEW_LIMIT = 8000
FRONTEND_URL = os.getenv("FYNISH_FRONTEND_URL", "http://127.0.0.1:5173/").strip()
BACKEND_CORS_ORIGINS = _getenv_list(
    "FYNISH_BACKEND_CORS_ORIGINS",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
)
GOOGLE_CLIENT_SECRETS_PATH = _getenv_path(
    "FYNISH_GOOGLE_CLIENT_SECRETS_PATH",
    BASE_DIR / "google-credentials.json",
)
GOOGLE_WEB_CLIENT_SECRETS_PATH = _getenv_path(
    "FYNISH_GOOGLE_WEB_CLIENT_SECRETS_PATH",
    GOOGLE_CLIENT_SECRETS_PATH,
)
GOOGLE_WEB_OAUTH_CALLBACK_URL = os.getenv(
    "FYNISH_GOOGLE_WEB_OAUTH_CALLBACK_URL",
    "http://127.0.0.1:5173/auth/gmail/callback",
).strip()
GOOGLE_TOKEN_DIR = _getenv_path("FYNISH_GOOGLE_TOKEN_DIR", DATA_DIR / "google_tokens")
GMAIL_TOKEN_STORAGE_MODE = os.getenv(
    "FYNISH_GMAIL_TOKEN_STORAGE_MODE",
    _default_gmail_token_storage_mode(APP_ENV),
).strip().lower()
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
ENABLE_GMAIL_WRITES = _getenv_bool("FYNISH_ENABLE_GMAIL_WRITES", False)
AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED = _getenv_bool(
    "FYNISH_AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED",
    False,
)
AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD = _getenv_float(
    "FYNISH_AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD",
    0.85,
)
SPAM_RESCUE_ENABLED = _getenv_bool("FYNISH_SPAM_RESCUE_ENABLED", APP_ENV == "local")
AUTO_SYNC_ENABLED = _getenv_bool("FYNISH_AUTO_SYNC_ENABLED", True)
AUTO_SYNC_INTERVAL_SECONDS = _getenv_int("FYNISH_AUTO_SYNC_INTERVAL_SECONDS", 300)
SCHEDULED_SYNC_ENABLED = _getenv_bool("FYNISH_SCHEDULED_SYNC_ENABLED", False)
SCHEDULED_DIGESTS_ENABLED = _getenv_bool("FYNISH_SCHEDULED_DIGESTS_ENABLED", False)
DIGEST_SENDER_ADMIN_EMAILS = [
    email.strip().lower()
    for email in _getenv_list("FYNISH_DIGEST_SENDER_ADMIN_EMAILS", [])
]
AI_DIGEST_SUMMARIES_ENABLED = _getenv_bool(
    "FYNISH_AI_DIGEST_SUMMARIES_ENABLED",
    False,
)
AI_DIGEST_PROVIDER = os.getenv("FYNISH_AI_DIGEST_PROVIDER", "openai").strip().lower()
OPENAI_API_KEY = os.getenv("FYNISH_OPENAI_API_KEY", "").strip()
OPENAI_DIGEST_MODEL = os.getenv("FYNISH_OPENAI_DIGEST_MODEL", "gpt-5-mini").strip()
OPENAI_DIGEST_TIMEOUT_SECONDS = _getenv_int(
    "FYNISH_OPENAI_DIGEST_TIMEOUT_SECONDS",
    20,
)
OPENAI_DIGEST_MAX_OUTPUT_TOKENS = _getenv_int(
    "FYNISH_OPENAI_DIGEST_MAX_OUTPUT_TOKENS",
    3000,
)
OPENAI_DIGEST_REASONING_EFFORT = os.getenv(
    "FYNISH_OPENAI_DIGEST_REASONING_EFFORT",
    "minimal",
).strip().lower()
AUTO_RESPONSE_DRAFTS_ENABLED = _getenv_bool("FYNISH_AUTO_RESPONSE_DRAFTS_ENABLED", False)
AUTO_RESPONSE_DRAFT_ALLOWED_USER_EMAILS = [
    email.lower()
    for email in _getenv_list("FYNISH_AUTO_RESPONSE_DRAFT_ALLOWED_USER_EMAILS", [])
]
AUTO_RESPONSE_SEND_ENABLED = _getenv_bool("FYNISH_AUTO_RESPONSE_SEND_ENABLED", False)
AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS = [
    email.lower()
    for email in _getenv_list("FYNISH_AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS", [])
]
AUTO_RESPONSE_SEND_MAX_BODY_CHARS = _getenv_int(
    "FYNISH_AUTO_RESPONSE_SEND_MAX_BODY_CHARS",
    8000,
)
AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS = _getenv_int(
    "FYNISH_AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS",
    1800,
)
AUTO_RESPONSE_SEND_THREAD_HISTORY_MESSAGES = _getenv_int(
    "FYNISH_AUTO_RESPONSE_SEND_THREAD_HISTORY_MESSAGES",
    2,
)
AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS = _getenv_int(
    "FYNISH_AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS",
    3000,
)
WRITING_STYLE_CARDS_ENABLED = _getenv_bool("FYNISH_WRITING_STYLE_CARDS_ENABLED", False)
WRITING_STYLE_ALLOWED_USER_EMAILS = [
    email.lower()
    for email in _getenv_list("FYNISH_WRITING_STYLE_ALLOWED_USER_EMAILS", [])
]
OPENAI_AUTO_RESPONSE_MODEL = os.getenv(
    "FYNISH_OPENAI_AUTO_RESPONSE_MODEL",
    OPENAI_DIGEST_MODEL,
).strip()
OPENAI_AUTO_RESPONSE_TIMEOUT_SECONDS = _getenv_int(
    "FYNISH_OPENAI_AUTO_RESPONSE_TIMEOUT_SECONDS",
    30,
)
OPENAI_AUTO_RESPONSE_MAX_OUTPUT_TOKENS = _getenv_int(
    "FYNISH_OPENAI_AUTO_RESPONSE_MAX_OUTPUT_TOKENS",
    1200,
)
OPENAI_AUTO_RESPONSE_REASONING_EFFORT = os.getenv(
    "FYNISH_OPENAI_AUTO_RESPONSE_REASONING_EFFORT",
    "minimal",
).strip().lower()
OPENAI_DIGEST_MAX_INPUT_MESSAGES = _getenv_int(
    "FYNISH_OPENAI_DIGEST_MAX_INPUT_MESSAGES",
    50,
)
OPENAI_DIGEST_INCLUDE_SNIPPETS = _getenv_bool(
    "FYNISH_OPENAI_DIGEST_INCLUDE_SNIPPETS",
    True,
)
SEED_MOCK_ACCOUNTS = _getenv_bool("FYNISH_SEED_MOCK_ACCOUNTS", APP_ENV == "local")
MAIL_PROVIDER = os.getenv("FYNISH_MAIL_PROVIDER", "disabled").strip().lower()
MAIL_FROM_EMAIL = os.getenv("FYNISH_MAIL_FROM_EMAIL", "").strip()
MAIL_API_KEY = os.getenv("FYNISH_MAIL_API_KEY", "").strip()
GMAIL_SENDER_EMAIL = os.getenv("FYNISH_GMAIL_SENDER_EMAIL", "").strip().lower()

POSTGRES_HOST = os.getenv("FYNISH_POSTGRES_HOST", "").strip()
POSTGRES_PORT = os.getenv("FYNISH_POSTGRES_PORT", "5432").strip()
POSTGRES_DATABASE = os.getenv("FYNISH_POSTGRES_DATABASE", "").strip()
POSTGRES_USER = os.getenv("FYNISH_POSTGRES_USER", "").strip()
CLOUDSQL_INSTANCE_CONNECTION_NAME = os.getenv(
    "FYNISH_CLOUDSQL_INSTANCE_CONNECTION_NAME", ""
).strip()
