from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.core import config
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME
from app.db.runtime import fetch_one, get_connection, insert_and_return_id


AUTHENTICATED_EMAIL_HEADER = "x-fynish-authenticated-email"
AUTHENTICATED_NAME_HEADER = "x-fynish-authenticated-name"
AUTHENTICATED_SUBJECT_HEADER = "x-fynish-authenticated-sub"


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    display_name: str
    subject: str | None
    auth_source: str


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_name(value: str | None, *, fallback_email: str) -> str:
    name = (value or "").strip()
    return name or fallback_email


def _ensure_user(conn, *, email: str, display_name: str) -> CurrentUser:
    row = fetch_one(
        conn,
        """
        SELECT id, email, display_name, status
        FROM users
        WHERE lower(email) = :email
        ORDER BY id DESC
        LIMIT 1
        """,
        {"email": email},
    )
    if row is None:
        user_id = insert_and_return_id(
            conn,
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES (:email, :display_name, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {
                "email": email,
                "display_name": display_name,
            },
        )
        return CurrentUser(
            id=user_id,
            email=email,
            display_name=display_name,
            subject=None,
            auth_source="header",
        )

    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="This user is not active.")

    current_display_name = (row["display_name"] or "").strip()
    if display_name and display_name != current_display_name:
        from app.db.runtime import execute_sql

        execute_sql(
            conn,
            """
            UPDATE users
            SET display_name = :display_name,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :user_id
            """,
            {
                "display_name": display_name,
                "user_id": row["id"],
            },
        )
        current_display_name = display_name

    return CurrentUser(
        id=int(row["id"]),
        email=str(row["email"]),
        display_name=current_display_name or email,
        subject=None,
        auth_source="header",
    )


def require_current_user(request: Request) -> CurrentUser:
    header_email = _normalize_email(request.headers.get(AUTHENTICATED_EMAIL_HEADER))
    header_name = request.headers.get(AUTHENTICATED_NAME_HEADER)
    header_subject = (request.headers.get(AUTHENTICATED_SUBJECT_HEADER) or "").strip() or None

    if header_email:
        display_name = _normalize_name(header_name, fallback_email=header_email)
        with get_connection() as conn:
            current_user = _ensure_user(
                conn,
                email=header_email,
                display_name=display_name,
            )
        return CurrentUser(
            id=current_user.id,
            email=current_user.email,
            display_name=current_user.display_name,
            subject=header_subject,
            auth_source="header",
        )

    if config.APP_ENV != "cloud":
        with get_connection() as conn:
            current_user = _ensure_user(
                conn,
                email=DEFAULT_LOCAL_OWNER_EMAIL,
                display_name=DEFAULT_LOCAL_OWNER_NAME,
            )
        return CurrentUser(
            id=current_user.id,
            email=current_user.email,
            display_name=current_user.display_name,
            subject=None,
            auth_source="local-default",
        )

    raise HTTPException(status_code=401, detail="Authenticated user context is required.")
