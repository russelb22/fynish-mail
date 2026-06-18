from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import config
from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.services.gmail_readonly import (
    GmailReadonlySyncError,
    build_service_from_token_reference,
    extract_headers_map,
)
from app.services.gmail_token_store import GmailTokenReference
from app.services.runtime_user import require_explicit_user_id_in_cloud
from app.services.writing_sample_export import (
    build_candidate_record,
    build_sample_buckets,
    choose_bucket_samples,
    clean_authored_text,
    default_start_date,
    extract_payload_text,
    sample_rejection_reason,
    utc_today,
)
from app.services.writing_style_profile import analyze_style


MAX_STYLE_CARD_LENGTH = 8000
MIN_STYLE_CARD_LENGTH = 80
SENT_SAMPLE_BUCKET_MODE = "year"
SENT_SAMPLE_PER_BUCKET = 8
SENT_SAMPLE_CANDIDATES_PER_BUCKET = 32
SENT_SAMPLE_MAX_TOTAL = 96


class WritingStyleCardValidationError(ValueError):
    pass


class WritingStyleCardSamplingError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def writing_style_cards_allowed_for_email(email_address: str) -> bool:
    if not config.WRITING_STYLE_CARDS_ENABLED:
        return False
    allowed_emails = set(config.WRITING_STYLE_ALLOWED_USER_EMAILS)
    if allowed_emails and email_address.strip().lower() not in allowed_emails:
        return False
    return True


def _clean_style_card(value: object) -> str:
    markdown = str(value or "").strip()
    if len(markdown) < MIN_STYLE_CARD_LENGTH:
        raise WritingStyleCardValidationError(
            f"style card must be at least {MIN_STYLE_CARD_LENGTH} characters"
        )
    if len(markdown) > MAX_STYLE_CARD_LENGTH:
        raise WritingStyleCardValidationError(
            f"style card must be {MAX_STYLE_CARD_LENGTH} characters or fewer"
        )
    return markdown


def _starter_style_card(account_email: str) -> str:
    return f"""# Writing Style Card

Private style guidance for {account_email}.

## How replies should sound

- Practical, conversational, and clear.
- Friendly without becoming overly formal.
- Direct when the answer is known.
- Careful about uncertainty; do not invent facts or commitments.
- Prefer short paragraphs that are easy to scan.

## How replies should be structured

- Start with a natural greeting when appropriate.
- Acknowledge the sender's request or question.
- Give the useful answer or next step.
- Ask for missing information only when needed.
- Close simply.

## Things to avoid

- Do not sound corporate or generic.
- Do not over-explain simple answers.
- Do not copy private source text or mention this style card.
""".strip()


def _serialize_row(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "mail_account_id": int(row["mail_account_id"]) if row["mail_account_id"] is not None else None,
        "account_email": row["account_email"],
        "status": row["status"],
        "source_provider": row["source_provider"],
        "sample_start_date": row["sample_start_date"],
        "sample_end_date": row["sample_end_date"],
        "sample_bucket_count": int(row["sample_bucket_count"] or 0),
        "sampled_message_count": int(row["sampled_message_count"] or 0),
        "sampled_word_count": int(row["sampled_word_count"] or 0),
        "style_card_markdown": row["style_card_markdown"],
        "user_edited": bool(row["user_edited"]),
        "edited_at": row["edited_at"],
        "generator_model": row["generator_model"],
        "generated_at": row["generated_at"],
        "approved_at": row["approved_at"],
        "disabled_at": row["disabled_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _fetch_owned_mail_account(conn, *, user_id: int, mail_account_id: int):
    return fetch_one(
        conn,
        """
        SELECT id, external_account_email
        FROM mail_accounts
        WHERE id = :mail_account_id AND user_id = :user_id
        """,
        {"mail_account_id": mail_account_id, "user_id": user_id},
    )


def _fetch_signed_in_gmail_token_reference(conn, *, user_id: int, account_email: str):
    return fetch_one(
        conn,
        """
        SELECT
            ma.id AS mail_account_id,
            ma.external_account_email AS account_email,
            pc.id AS provider_connection_id,
            pc.token_path,
            pc.metadata_json
        FROM mail_accounts ma
        LEFT JOIN provider_connections pc
          ON pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = ma.id
                  AND latest_pc.provider = ma.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
             )
        WHERE ma.user_id = :user_id
          AND ma.provider IN ('gmail', 'gmail_readonly')
          AND ma.enabled = 1
          AND lower(ma.external_account_email) = lower(:account_email)
        LIMIT 1
        """,
        {"user_id": user_id, "account_email": account_email},
    )


def _fetch_enabled_gmail_token_references(conn, *, user_id: int) -> list[Any]:
    return fetch_all(
        conn,
        """
        SELECT
            ma.id AS mail_account_id,
            ma.external_account_email AS account_email,
            pc.id AS provider_connection_id,
            pc.token_path,
            pc.metadata_json
        FROM mail_accounts ma
        LEFT JOIN provider_connections pc
          ON pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = ma.id
                  AND latest_pc.provider = ma.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
             )
        WHERE ma.user_id = :user_id
          AND ma.provider IN ('gmail', 'gmail_readonly')
          AND ma.enabled = 1
        ORDER BY ma.external_account_email ASC
        """,
        {"user_id": user_id},
    )


def _resolve_sent_mail_sample_source(conn, *, user_id: int, style_owner_email: str):
    exact = _fetch_signed_in_gmail_token_reference(
        conn,
        user_id=user_id,
        account_email=style_owner_email,
    )
    if exact is not None:
        return exact

    accounts = _fetch_enabled_gmail_token_references(conn, user_id=user_id)
    if len(accounts) == 1:
        return accounts[0]
    if not accounts:
        raise WritingStyleCardSamplingError(
            "Connect Gmail before sampling Sent mail."
        )
    raise WritingStyleCardSamplingError(
        "More than one Gmail account is connected. Sign in with the Gmail address to sample, or reconnect only the Gmail account to use for this style card."
    )


def _list_sent_message_refs(service: Any, *, query: str, max_results: int) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    request = service.users().messages().list(
        userId="me",
        q=query,
        labelIds=["SENT"],
        maxResults=min(max_results, 500),
    )
    while request is not None and len(refs) < max_results:
        response = request.execute()
        refs.extend(response.get("messages", []))
        if len(refs) >= max_results:
            break
        request = service.users().messages().list_next(request, response)
    return refs[:max_results]


def _fetch_gmail_message(service: Any, message_id: str) -> dict[str, Any]:
    return (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )


def _sample_sent_mail_records(
    *,
    service: Any,
    account_email: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    today = utc_today()
    start = default_start_date(today)
    end = today + timedelta(days=1)
    buckets = build_sample_buckets(start=start, end=end, mode=SENT_SAMPLE_BUCKET_MODE)
    records: list[dict[str, Any]] = []
    manifest_buckets: list[dict[str, Any]] = []

    for bucket in buckets:
        remaining_slots = SENT_SAMPLE_MAX_TOTAL - len(records)
        if remaining_slots <= 0:
            break
        keep_limit = min(SENT_SAMPLE_PER_BUCKET, remaining_slots)
        refs = _list_sent_message_refs(
            service,
            query=bucket.gmail_query,
            max_results=SENT_SAMPLE_CANDIDATES_PER_BUCKET,
        )
        bucket_candidates: list[dict[str, Any]] = []
        rejection_reasons: Counter[str] = Counter()

        for ref in refs:
            raw_message = _fetch_gmail_message(service, ref["id"])
            payload = raw_message.get("payload", {}) or {}
            headers = extract_headers_map(payload)
            cleaned_body = clean_authored_text(extract_payload_text(payload))
            if not cleaned_body:
                rejection_reasons["empty_after_cleaning"] += 1
                continue

            record = build_candidate_record(
                account_email=account_email,
                bucket=bucket,
                message=raw_message,
                headers=headers,
                cleaned_body=cleaned_body,
            )
            rejection_reason = sample_rejection_reason(record)
            if rejection_reason:
                rejection_reasons[rejection_reason] += 1
                continue
            bucket_candidates.append(record)

        bucket_records = choose_bucket_samples(bucket_candidates, limit=keep_limit)
        records.extend(bucket_records)
        manifest_buckets.append(
            {
                "bucket": bucket.label,
                "fetched_message_refs": len(refs),
                "usable_candidates": len(bucket_candidates),
                "kept_samples": len(bucket_records),
                "rejection_reasons": dict(sorted(rejection_reasons.items())),
            }
        )

    return records, manifest_buckets, start.isoformat(), end.isoformat()


def list_writing_style_cards(user_id: int | None = None) -> list[dict[str, Any]]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="list_writing_style_cards",
    )
    with get_connection() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT *
            FROM writing_style_cards
            WHERE user_id = :user_id
            ORDER BY lower(account_email), created_at DESC
            """,
            {"user_id": user_id},
        )
    return [_serialize_row(row) for row in rows]


def create_starter_writing_style_card(
    *,
    user_id: int | None,
    account_email: str | None = None,
    mail_account_id: int | None = None,
) -> dict[str, Any]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="create_starter_writing_style_card",
    )
    now = _now_iso()
    with get_connection() as conn:
        if mail_account_id is not None:
            account = _fetch_owned_mail_account(
                conn,
                user_id=int(user_id),
                mail_account_id=mail_account_id,
            )
            if account is None:
                raise WritingStyleCardValidationError("mail account not found")
            account_email = str(account["external_account_email"])
        else:
            account_email = str(account_email or "").strip()
            if not account_email:
                raise WritingStyleCardValidationError("account email is required")

        execute_sql(
            conn,
            """
            UPDATE writing_style_cards
            SET status = 'superseded', updated_at = :updated_at
            WHERE user_id = :user_id
              AND lower(account_email) = lower(:account_email)
              AND status IN ('draft', 'approved')
            """,
            {"updated_at": now, "user_id": user_id, "account_email": account_email},
        )
        card_id = insert_and_return_id(
            conn,
            """
            INSERT INTO writing_style_cards (
                user_id, mail_account_id, account_email, status, source_provider,
                style_card_markdown, user_edited, generated_at, created_at, updated_at
            ) VALUES (
                :user_id, :mail_account_id, :account_email, 'draft', 'manual_starter',
                :style_card_markdown, 0, :generated_at, :created_at, :updated_at
            )
            """,
            {
                "user_id": user_id,
                "mail_account_id": mail_account_id,
                "account_email": account_email,
                "style_card_markdown": _starter_style_card(account_email),
                "generated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
    return _serialize_row(row)


def sample_sent_mail_writing_style_card(
    *,
    user_id: int | None,
    account_email: str,
) -> dict[str, Any]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="sample_sent_mail_writing_style_card",
    )
    account_email = account_email.strip()
    if not account_email:
        raise WritingStyleCardValidationError("account email is required")

    with get_connection() as conn:
        account = _resolve_sent_mail_sample_source(
            conn,
            user_id=int(user_id),
            style_owner_email=account_email,
        )

    reference = GmailTokenReference.from_row(account)
    source_account_email = str(account["account_email"])
    try:
        service = build_service_from_token_reference(reference)
        records, manifest_buckets, sample_start, sample_end = _sample_sent_mail_records(
            service=service,
            account_email=source_account_email,
        )
    except GmailReadonlySyncError as error:
        raise WritingStyleCardSamplingError(str(error)) from error
    except Exception as error:  # pragma: no cover - Gmail API failures vary
        raise WritingStyleCardSamplingError("Unable to sample Gmail Sent mail.") from error

    if not records:
        raise WritingStyleCardSamplingError(
            "No usable sent-mail samples were found for this account."
        )

    profile = analyze_style(records, account_email=account_email)
    now = _now_iso()
    sampled_word_count = sum(int(record.get("word_count") or 0) for record in records)
    mail_account_id = int(account["mail_account_id"])

    with get_connection() as conn:
        execute_sql(
            conn,
            """
            UPDATE writing_style_cards
            SET status = 'superseded', updated_at = :updated_at
            WHERE user_id = :user_id
              AND lower(account_email) = lower(:account_email)
              AND status IN ('draft', 'approved')
            """,
            {"updated_at": now, "user_id": user_id, "account_email": account_email},
        )
        card_id = insert_and_return_id(
            conn,
            """
            INSERT INTO writing_style_cards (
                user_id, mail_account_id, account_email, status, source_provider,
                sample_start_date, sample_end_date, sample_bucket_count,
                sampled_message_count, sampled_word_count, style_card_markdown,
                user_edited, generator_model, generated_at, created_at, updated_at
            ) VALUES (
                :user_id, :mail_account_id, :account_email, 'draft', 'gmail_sent_sampler',
                :sample_start_date, :sample_end_date, :sample_bucket_count,
                :sampled_message_count, :sampled_word_count, :style_card_markdown,
                0, :generator_model, :generated_at, :created_at, :updated_at
            )
            """,
            {
                "user_id": user_id,
                "mail_account_id": mail_account_id,
                "account_email": account_email,
                "sample_start_date": sample_start,
                "sample_end_date": sample_end,
                "sample_bucket_count": len(manifest_buckets),
                "sampled_message_count": len(records),
                "sampled_word_count": sampled_word_count,
                "style_card_markdown": profile.markdown[:MAX_STYLE_CARD_LENGTH],
                "generator_model": "deterministic_sent_mail_profile_v1",
                "generated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
    return _serialize_row(row)


def update_writing_style_card(
    card_id: int,
    changes: dict[str, Any],
    *,
    user_id: int | None,
) -> dict[str, Any] | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="update_writing_style_card",
    )
    markdown = _clean_style_card(changes.get("style_card_markdown"))
    now = _now_iso()

    with get_connection() as conn:
        current = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
        if current is None:
            return None
        if current["status"] not in {"draft", "approved"}:
            raise WritingStyleCardValidationError("only draft or approved style cards can be edited")

        next_status = "draft" if current["status"] == "approved" else current["status"]
        execute_sql(
            conn,
            """
            UPDATE writing_style_cards
            SET style_card_markdown = :style_card_markdown,
                status = :status,
                user_edited = 1,
                edited_at = :edited_at,
                approved_at = CASE WHEN :status = 'draft' THEN NULL ELSE approved_at END,
                updated_at = :updated_at
            WHERE id = :id AND user_id = :user_id
            """,
            {
                "style_card_markdown": markdown,
                "status": next_status,
                "edited_at": now,
                "updated_at": now,
                "id": card_id,
                "user_id": user_id,
            },
        )
        row = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
    return _serialize_row(row)


def approve_writing_style_card(
    card_id: int,
    *,
    user_id: int | None,
) -> dict[str, Any] | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="approve_writing_style_card",
    )
    now = _now_iso()
    with get_connection() as conn:
        current = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
        if current is None:
            return None
        if current["status"] not in {"draft", "approved"}:
            raise WritingStyleCardValidationError("only draft style cards can be approved")
        _clean_style_card(current["style_card_markdown"])

        execute_sql(
            conn,
            """
            UPDATE writing_style_cards
            SET status = 'superseded', updated_at = :updated_at
            WHERE user_id = :user_id
              AND id != :id
              AND lower(account_email) = lower(:account_email)
              AND status = 'approved'
            """,
            {
                "updated_at": now,
                "user_id": user_id,
                "id": card_id,
                "account_email": current["account_email"],
            },
        )
        execute_sql(
            conn,
            """
            UPDATE writing_style_cards
            SET status = 'approved',
                approved_at = :approved_at,
                disabled_at = NULL,
                updated_at = :updated_at
            WHERE id = :id AND user_id = :user_id
            """,
            {"approved_at": now, "updated_at": now, "id": card_id, "user_id": user_id},
        )
        row = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
    return _serialize_row(row)


def disable_writing_style_card(
    card_id: int,
    *,
    user_id: int | None,
) -> dict[str, Any] | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="disable_writing_style_card",
    )
    now = _now_iso()
    with get_connection() as conn:
        current = fetch_one(
            conn,
            "SELECT id FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
        if current is None:
            return None
        execute_sql(
            conn,
            """
            UPDATE writing_style_cards
            SET status = 'disabled',
                disabled_at = :disabled_at,
                approved_at = NULL,
                updated_at = :updated_at
            WHERE id = :id AND user_id = :user_id
            """,
            {"disabled_at": now, "updated_at": now, "id": card_id, "user_id": user_id},
        )
        row = fetch_one(
            conn,
            "SELECT * FROM writing_style_cards WHERE id = :id AND user_id = :user_id",
            {"id": card_id, "user_id": user_id},
        )
    return _serialize_row(row)


def get_approved_writing_style_card(
    *,
    user_id: int,
    account_email: str,
    mail_account_id: int | None = None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "user_id": user_id,
        "account_email": account_email,
        "mail_account_id": mail_account_id,
    }
    if mail_account_id is not None:
        account_clause = "mail_account_id = :mail_account_id"
    else:
        account_clause = "lower(account_email) = lower(:account_email)"

    with get_connection() as conn:
        row = fetch_one(
            conn,
            f"""
            SELECT *
            FROM writing_style_cards
            WHERE user_id = :user_id
              AND status = 'approved'
              AND {account_clause}
            ORDER BY approved_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
    return _serialize_row(row) if row is not None else None
