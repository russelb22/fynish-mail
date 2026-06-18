from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.core.config import ENABLE_GMAIL_WRITES, GMAIL_MODIFY_SCOPE
from app.db.runtime import execute_sql, fetch_one, get_connection
from app.services.action_logging import insert_action_log
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.gmail_token_store import GmailTokenReference
from app.services.mail_provider_adapter import get_mail_provider_adapter
from app.services.gmail_write_planner import GmailActionPlan, plan_message_action
from app.services.runtime_accounts import fetch_runtime_account_connection
from app.services.runtime_user import require_explicit_user_id_in_cloud


logger = logging.getLogger(__name__)


@dataclass
class GmailExecutionResult:
    message_id: int
    gmail_message_id: str
    account_email: str
    selected_action: str
    status: str
    executed: bool
    allowed: bool
    live_writes_enabled: bool
    oauth_scope_ready: bool
    labels_added: list[str]
    labels_removed: list[str]
    response_label_ids: list[str]
    notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_row_for_account(account_email: str):
    with get_connection() as conn:
        return fetch_runtime_account_connection(conn, account_email, provider="gmail_readonly")


def _failed_execution_result(
    plan: GmailActionPlan,
    error: Exception,
    allow_live_writes: bool,
) -> GmailExecutionResult:
    notes = list(plan.safety_notes)
    notes.append(str(error))
    return GmailExecutionResult(
        message_id=plan.message_id,
        gmail_message_id=plan.gmail_message_id,
        account_email=plan.account_email,
        selected_action=plan.selected_action,
        status="failed",
        executed=False,
        allowed=plan.allowed,
        live_writes_enabled=allow_live_writes,
        oauth_scope_ready=False,
        labels_added=plan.labels_to_add,
        labels_removed=plan.labels_to_remove,
        response_label_ids=[],
        notes=notes,
    )


def _missing_execution_result(item: dict, allow_live_writes: bool) -> GmailExecutionResult:
    return GmailExecutionResult(
        message_id=int(item["message_id"]),
        gmail_message_id="",
        account_email="",
        selected_action=str(item["action"]),
        status="failed",
        executed=False,
        allowed=False,
        live_writes_enabled=allow_live_writes,
        oauth_scope_ready=False,
        labels_added=[],
        labels_removed=[],
        response_label_ids=[],
        notes=["Message is no longer available."],
    )


def execute_gmail_action_plan(
    plan: GmailActionPlan,
    *,
    allow_live_writes: bool = False,
    require_feature_flag: bool = True,
) -> GmailExecutionResult:
    notes = list(plan.safety_notes)
    connection = _connection_row_for_account(plan.account_email)

    if not plan.will_modify_gmail:
        notes.append("No Gmail label mutation is required for this action")
        return GmailExecutionResult(
            message_id=plan.message_id,
            gmail_message_id=plan.gmail_message_id,
            account_email=plan.account_email,
            selected_action=plan.selected_action,
            status="executed",
            executed=True,
            allowed=plan.allowed,
            live_writes_enabled=allow_live_writes,
            oauth_scope_ready=True,
            labels_added=plan.labels_to_add,
            labels_removed=plan.labels_to_remove,
            response_label_ids=plan.current_labels,
            notes=notes,
        )

    if not plan.allowed:
        notes.append("Planner blocked this action before any Gmail call could be attempted")
        return GmailExecutionResult(
            message_id=plan.message_id,
            gmail_message_id=plan.gmail_message_id,
            account_email=plan.account_email,
            selected_action=plan.selected_action,
            status="blocked",
            executed=False,
            allowed=False,
            live_writes_enabled=False,
            oauth_scope_ready=False,
            labels_added=plan.labels_to_add,
            labels_removed=plan.labels_to_remove,
            response_label_ids=[],
            notes=notes,
        )

    token_reference = GmailTokenReference.from_row(connection) if connection is not None else None

    if (
        connection is None
        or connection["provider"] != "gmail_readonly"
        or token_reference is None
        or (
            token_reference.token_path is None
            and token_reference.provider_connection_id is None
            and token_reference.token_json() is None
        )
    ):
        notes.append("No Gmail OAuth connection is available for this account")
        return GmailExecutionResult(
            message_id=plan.message_id,
            gmail_message_id=plan.gmail_message_id,
            account_email=plan.account_email,
            selected_action=plan.selected_action,
            status="blocked",
            executed=False,
            allowed=True,
            live_writes_enabled=False,
            oauth_scope_ready=False,
            labels_added=plan.labels_to_add,
            labels_removed=plan.labels_to_remove,
            response_label_ids=[],
            notes=notes,
        )

    configured_scopes = json.loads(connection["scopes_json"] or "[]")
    oauth_scope_ready = GMAIL_MODIFY_SCOPE in configured_scopes
    feature_enabled = allow_live_writes and (ENABLE_GMAIL_WRITES or not require_feature_flag)

    if not oauth_scope_ready:
        notes.append("Connected Gmail token does not include gmail.modify")
    if not feature_enabled:
        notes.append("Live Gmail writes are disabled unless explicitly enabled")

    if not oauth_scope_ready or not feature_enabled:
        return GmailExecutionResult(
            message_id=plan.message_id,
            gmail_message_id=plan.gmail_message_id,
            account_email=plan.account_email,
            selected_action=plan.selected_action,
            status="blocked",
            executed=False,
            allowed=True,
            live_writes_enabled=feature_enabled,
            oauth_scope_ready=oauth_scope_ready,
            labels_added=plan.labels_to_add,
            labels_removed=plan.labels_to_remove,
            response_label_ids=[],
            notes=notes,
        )

    adapter = get_mail_provider_adapter(connection["provider"])
    if adapter is None:
        notes.append("No provider adapter is available for this account")
        return GmailExecutionResult(
            message_id=plan.message_id,
            gmail_message_id=plan.gmail_message_id,
            account_email=plan.account_email,
            selected_action=plan.selected_action,
            status="blocked",
            executed=False,
            allowed=True,
            live_writes_enabled=feature_enabled,
            oauth_scope_ready=oauth_scope_ready,
            labels_added=plan.labels_to_add,
            labels_removed=plan.labels_to_remove,
            response_label_ids=[],
            notes=notes,
        )

    response_label_ids = adapter.modify_message_labels(
        token_reference=token_reference,
        provider_message_id=plan.gmail_message_id,
        labels_to_add=plan.labels_to_add,
        labels_to_remove=plan.labels_to_remove,
    )

    notes.append("Gmail label modify call executed successfully")
    return GmailExecutionResult(
        message_id=plan.message_id,
        gmail_message_id=plan.gmail_message_id,
        account_email=plan.account_email,
        selected_action=plan.selected_action,
        status="executed",
        executed=True,
        allowed=True,
        live_writes_enabled=True,
        oauth_scope_ready=True,
        labels_added=plan.labels_to_add,
        labels_removed=plan.labels_to_remove,
        response_label_ids=response_label_ids,
        notes=notes,
    )


def execute_message_action(
    message_id: int,
    action: str,
    *,
    allow_live_writes: bool = False,
    require_feature_flag: bool = True,
    conn=None,
    user_id: int | None = None,
) -> GmailExecutionResult | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="execute_message_action",
    )
    plan = plan_message_action(message_id, action, conn=conn, user_id=user_id)
    if plan is None:
        return None
    return execute_gmail_action_plan(
        plan,
        allow_live_writes=allow_live_writes,
        require_feature_flag=require_feature_flag,
    )


def execute_selected_message_actions(
    items: list[dict],
    *,
    allow_live_writes: bool = False,
    require_feature_flag: bool = True,
    user_id: int | None = None,
) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="execute_selected_message_actions",
    )
    results = []
    for item in items:
        plan = plan_message_action(
            int(item["message_id"]),
            item["action"],
            user_id=user_id,
        )
        if plan is None:
            results.append(_missing_execution_result(item, allow_live_writes).to_dict())
            continue
        try:
            result = execute_gmail_action_plan(
                plan,
                allow_live_writes=allow_live_writes,
                require_feature_flag=require_feature_flag,
            )
        except GmailReadonlySyncError as error:
            logger.warning(
                "Gmail live bulk action failed for message_id=%s account_email=%s: %s",
                plan.message_id,
                plan.account_email,
                error,
            )
            result = _failed_execution_result(plan, error, allow_live_writes)
        if result.executed:
            log_executed_message_action(result)
        results.append(result.to_dict())

    executed = sum(1 for result in results if result["executed"])
    failed = sum(1 for result in results if result["status"] == "failed")
    blocked = len(results) - executed - failed
    return {
        "results": results,
        "executed": executed,
        "blocked": blocked,
        "failed": failed,
    }


def log_executed_message_action(
    result: GmailExecutionResult,
    conn=None,
    *,
    action_source: str = "manual",
) -> None:
    if not result.executed:
        return

    now = _now_iso()
    if conn is None:
        with get_connection() as owned_conn:
            log_executed_message_action(result, conn=owned_conn, action_source=action_source)
        return

    message = fetch_one(
        conn,
        "SELECT * FROM messages WHERE id = :message_id",
        {"message_id": result.message_id},
    )
    if message is None:
        raise GmailReadonlySyncError(
            f"Cannot log executed Gmail action for missing message id {result.message_id}"
        )
    insert_action_log(
        conn,
        message_row=message,
        selected_action=result.selected_action,
        recommended_action=message["current_category"],
        labels_added=result.labels_added,
        labels_removed=result.labels_removed,
        created_at=now,
        action_source=action_source,
    )
    execute_sql(
        conn,
        """
        UPDATE messages
        SET reviewed = 1, updated_at = :updated_at, current_category = :selected_action
        WHERE id = :message_id
        """,
        {
            "updated_at": now,
            "selected_action": result.selected_action,
            "message_id": result.message_id,
        },
    )
