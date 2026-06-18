from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from app.db.runtime import fetch_all, fetch_one, get_connection
from app.services.ownership import fetch_owned_message
from app.services.runtime_accounts import fetch_runtime_message_with_provider
from app.services.runtime_user import require_explicit_user_id_in_cloud


ACTION_TO_LABELS = {
    "keep": {"add": [], "remove": []},
    "bulk_mail": {"add": ["Fynish/Bulk Mail"], "remove": ["INBOX"]},
    "junk_review": {"add": ["Fynish/Junk Review"], "remove": ["INBOX"]},
    "trash": {"add": ["Fynish/Trash"], "remove": ["INBOX"]},
    "needs_review": {"add": ["Fynish/Needs Review"], "remove": []},
}


@dataclass
class GmailActionPlan:
    message_id: int
    gmail_message_id: str
    account_email: str
    provider: str
    subject: str
    selected_action: str
    recommended_action: str
    current_labels: list[str]
    labels_to_add: list[str]
    labels_to_remove: list[str]
    labels_to_preserve: list[str]
    will_modify_gmail: bool
    will_use_trash: bool
    will_delete_permanently: bool
    preserves_unread: bool
    protected: bool
    allowed: bool
    safety_notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def validate_gmail_action_plan(plan: GmailActionPlan) -> GmailActionPlan:
    notes = list(plan.safety_notes)
    allowed = plan.allowed

    if "UNREAD" in plan.labels_to_remove:
        allowed = False
        notes.append("UNREAD label removal is not allowed")
    else:
        notes.append("UNREAD label will be preserved")

    if plan.will_use_trash:
        allowed = False
        notes.append("Gmail Trash operations are not allowed in V1")
    else:
        notes.append("No Gmail Trash operation is planned")

    if plan.will_delete_permanently:
        allowed = False
        notes.append("Permanent delete is not allowed in V1")
    else:
        notes.append("No permanent delete is planned")

    plan.allowed = allowed
    plan.safety_notes = notes
    plan.preserves_unread = "UNREAD" not in plan.labels_to_remove
    return plan


def plan_action_for_message_row(message_row, action: str) -> GmailActionPlan:
    labels = ACTION_TO_LABELS[action]
    current_labels = json.loads(message_row["gmail_labels_json"] or "[]")
    provider = message_row["provider"] or "unknown"

    plan = GmailActionPlan(
        message_id=int(message_row["id"]),
        gmail_message_id=message_row["gmail_message_id"],
        account_email=message_row["account_email"],
        provider=provider,
        subject=message_row["subject"] or "(No subject)",
        selected_action=action,
        recommended_action=message_row["current_category"],
        current_labels=current_labels,
        labels_to_add=list(labels["add"]),
        labels_to_remove=list(labels["remove"]),
        labels_to_preserve=["UNREAD"] if "UNREAD" in current_labels else [],
        will_modify_gmail=bool(labels["add"] or labels["remove"]),
        will_use_trash=False,
        will_delete_permanently=False,
        preserves_unread=True,
        protected=bool(message_row["protected"]),
        allowed=True,
        safety_notes=[],
    )
    return validate_gmail_action_plan(plan)


def plan_message_action(
    message_id: int,
    action: str,
    conn=None,
    user_id: int | None = None,
) -> GmailActionPlan | None:
    if user_id is None:
        require_explicit_user_id_in_cloud(
            user_id,
            operation="plan_message_action",
        )
    if conn is None:
        with get_connection() as owned_conn:
            return plan_message_action(message_id, action, conn=owned_conn, user_id=user_id)

    if user_id is not None and fetch_owned_message(conn, message_id, user_id) is None:
        return None

    row = fetch_runtime_message_with_provider(conn, message_id)
    if row is None:
        return None
    return plan_action_for_message_row(row, action)


def plan_selected_actions(items: list[dict]) -> dict:
    plans = []
    for item in items:
        plan = plan_message_action(item["message_id"], item["action"])
        if plan is not None:
            plans.append(plan.to_dict())
    return {"plans": plans}


def plan_gmail_readonly_account_actions(
    account_email: str | None = None,
    only_unreviewed: bool = True,
) -> dict:
    query = """
        SELECT
            m.*,
            COALESCE(ma.provider, a.provider, 'unknown') AS provider
        FROM messages m
        LEFT JOIN mail_accounts ma
          ON ma.id = m.mail_account_id
        LEFT JOIN accounts a
          ON a.email_address = m.account_email
         AND (ma.id IS NULL OR a.provider = ma.provider)
        WHERE COALESCE(ma.provider, a.provider) = 'gmail_readonly'
    """
    params: dict[str, object] = {}

    if only_unreviewed:
        query += " AND m.reviewed = 0"
    if account_email is not None:
        query += " AND m.account_email = :account_email"
        params["account_email"] = account_email

    query += " ORDER BY m.account_email ASC, m.received_at DESC"

    with get_connection() as conn:
        rows = fetch_all(conn, query, params)

    plans = [
        plan_action_for_message_row(row, row["current_category"]).to_dict()
        for row in rows
    ]
    return {"plans": plans}
