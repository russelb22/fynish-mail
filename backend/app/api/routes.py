import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core import config
from app.core.errors import http_exception_for_error
from app.api.dependencies import CurrentUser, require_current_user
from app.schemas.api import (
    AIDigestAttentionNoteCreateRequest,
    AIDigestAttentionNoteUpdateRequest,
    AutoResponseDraftRequest,
    AutoResponseSendPreviewRequest,
    AutoResponseSendRequest,
    BulkApplyRequest,
    MessageActionRequest,
    NotificationSettingsUpdateRequest,
    RuleCreateRequest,
    RuleUpdateRequest,
    StagedActionsCommitRequest,
    WritingStyleCardCreateRequest,
    WritingStyleCardUpdateRequest,
)
from app.services.auto_sync import scheduled_sync_service
from app.services.digests import build_processed_digest_payload
from app.services.digests import scheduled_digest_service
from app.services.notification_settings import (
    get_notification_settings,
    update_notification_settings,
)
from app.services.ai_digest_attention_notes import (
    create_ai_digest_attention_note,
    delete_ai_digest_attention_note,
    list_ai_digest_attention_notes,
    update_ai_digest_attention_note,
)
from app.services.auto_response_draft import (
    AutoResponseDraftError,
    AutoResponseDraftNotConfiguredError,
    auto_response_drafts_allowed_for_email,
    generate_auto_response_draft,
)
from app.services.auto_response_send import (
    AutoResponseSendError,
    AutoResponseSendNotConfiguredError,
    AutoResponseSendValidationError,
    auto_response_send_allowed_for_email,
    preview_auto_response_send,
    send_auto_response,
)
from app.services.writing_style_cards import (
    WritingStyleCardSamplingError,
    WritingStyleCardValidationError,
    approve_writing_style_card,
    disable_writing_style_card,
    list_writing_style_cards,
    sample_sent_mail_writing_style_card,
    update_writing_style_card,
    writing_style_cards_allowed_for_email,
)
from app.services.processed_mail import list_processed_messages
from app.services.accounts import (
    connect_gmail_modify_account,
    connect_gmail_readonly_account,
    connect_gmail_account_from_web_oauth,
    connect_next_mock_account,
    disable_account,
    enable_account,
    list_accounts,
)
from app.services.message_recovery import recover_processed_message
from app.services.gmail_readonly import (
    GmailReadonlyNotConfiguredError,
    GmailReadonlySyncError,
)
from app.services.gmail_web_oauth import (
    GmailWebOAuthNotConfiguredError,
    GmailWebOAuthStateError,
    complete_gmail_web_oauth,
    start_gmail_web_oauth,
)
from app.services.digest_sender import (
    digest_sender_admin_allowed_for_email,
    get_gmail_digest_sender,
    persist_gmail_digest_sender,
    validate_gmail_digest_sender,
)
from app.services.gmail_write_executor import (
    execute_message_action,
    execute_selected_message_actions,
    log_executed_message_action,
)
from app.services.gmail_write_planner import plan_message_action
from app.services.reminders import get_reminder_summary
from app.services.review_queue import (
    apply_message_action,
    apply_selected_actions,
    get_review_queue,
    reclassify_pending_messages,
    sync_unread_messages,
)
from app.services.spam_rescue import get_spam_rescue_queue
from app.services.rules import create_rule, delete_rule, list_rules, update_rule
from app.services.staged_commit import (
    StagedCommitAction,
    StagedCommitRule,
    commit_staged_actions,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/health")
def healthcheck():
    return {"status": "ok"}


@router.get("/features")
def feature_flags(current_user: CurrentUser = Depends(require_current_user)):
    return {
        "features": {
            "auto_response_drafts": auto_response_drafts_allowed_for_email(current_user.email),
            "auto_response_send": auto_response_send_allowed_for_email(current_user.email),
            "writing_style_cards": writing_style_cards_allowed_for_email(current_user.email),
            "spam_rescue": config.SPAM_RESCUE_ENABLED,
        }
    }


@router.get("/accounts")
def get_accounts(current_user: CurrentUser = Depends(require_current_user)):
    return {"accounts": list_accounts(user_id=current_user.id)}


@router.post("/accounts/connect")
def connect_account(current_user: CurrentUser = Depends(require_current_user)):
    account = connect_next_mock_account(user_id=current_user.id)
    if account is None:
        raise HTTPException(status_code=409, detail="No more mock accounts available")
    return {"account": account}


@router.post("/accounts/connect-gmail")
def connect_gmail_account(current_user: CurrentUser = Depends(require_current_user)):
    try:
        account = connect_gmail_readonly_account(user_id=current_user.id)
    except ValueError as error:
        raise http_exception_for_error(error, status_code=409) from error
    except GmailReadonlyNotConfiguredError as error:
        raise http_exception_for_error(error) from error
    return {"account": account}


@router.get("/accounts/connect-gmail/start")
def connect_gmail_account_start(
    mode: str = Query(default="readonly"),
    login_hint: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        result = start_gmail_web_oauth(
            user_id=current_user.id,
            scope_mode=mode,
            login_hint=login_hint,
        )
    except ValueError as error:
        raise http_exception_for_error(error) from error
    except GmailWebOAuthNotConfiguredError as error:
        raise http_exception_for_error(error) from error
    return {
        "authorization_url": result.authorization_url,
        "state": result.oauth_state,
        "session_id": result.session_id,
    }


@router.get("/settings/digest-sender")
def digest_sender_status(current_user: CurrentUser = Depends(require_current_user)):
    can_manage = digest_sender_admin_allowed_for_email(current_user.email)
    return {
        "sender": validate_gmail_digest_sender() if can_manage else None,
        "configured_email": config.GMAIL_SENDER_EMAIL or None,
        "can_manage": can_manage,
    }


@router.get("/settings/digest-sender/connect-gmail/start")
def digest_sender_connect_gmail_start(
    login_hint: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_current_user),
):
    if not digest_sender_admin_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Digest sender setup is restricted to the Fynish admin.")
    try:
        result = start_gmail_web_oauth(
            user_id=current_user.id,
            scope_mode="send",
            login_hint=login_hint or config.GMAIL_SENDER_EMAIL or None,
        )
    except GmailWebOAuthNotConfiguredError as error:
        raise http_exception_for_error(error) from error
    return {
        "authorization_url": result.authorization_url,
        "state": result.oauth_state,
        "session_id": result.session_id,
    }


@router.get("/accounts/connect-gmail/callback")
def connect_gmail_account_callback(
    state: str = Query(default=""),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        result = complete_gmail_web_oauth(
            oauth_state=state,
            authorization_code=code,
            oauth_error=error,
            expected_user_id=current_user.id,
        )
        if result.scope_mode == "send":
            sender = persist_gmail_digest_sender(
                email_address=result.email_address,
                scopes=result.scopes,
                token_json=result.token_json,
            )
            return {
                "redirect_url": result.redirect_url,
                "digest_sender": sender,
            }
        account = connect_gmail_account_from_web_oauth(
            email_address=result.email_address,
            scopes=result.scopes,
            token_json=result.token_json,
            user_id=result.user_id,
        )
    except (GmailWebOAuthNotConfiguredError, GmailWebOAuthStateError, ValueError) as error:
        raise http_exception_for_error(error) from error
    return {
        "redirect_url": result.redirect_url,
        "account": account,
    }


@router.post("/accounts/connect-gmail-modify")
def connect_gmail_modify(current_user: CurrentUser = Depends(require_current_user)):
    try:
        account = connect_gmail_modify_account(user_id=current_user.id)
    except ValueError as error:
        raise http_exception_for_error(error, status_code=409) from error
    except GmailReadonlyNotConfiguredError as error:
        raise http_exception_for_error(error) from error
    return {"account": account}


@router.post("/accounts/{account_id}/disable")
def disable_account_route(account_id: int, current_user: CurrentUser = Depends(require_current_user)):
    account = disable_account(account_id, user_id=current_user.id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account": account}


@router.post("/accounts/{account_id}/enable")
def enable_account_route(account_id: int, current_user: CurrentUser = Depends(require_current_user)):
    account = enable_account(account_id, user_id=current_user.id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account": account}


@router.post("/sync/unread")
def sync_unread(current_user: CurrentUser = Depends(require_current_user)):
    try:
        return sync_unread_messages(user_id=current_user.id)
    except GmailReadonlySyncError as error:
        raise http_exception_for_error(error) from error


@router.post("/tasks/sync-unread")
def scheduled_sync_unread():
    try:
        return scheduled_sync_service.run_once()
    except GmailReadonlySyncError as error:
        raise http_exception_for_error(error) from error


@router.post("/tasks/send-digests")
def scheduled_send_digests():
    try:
        return scheduled_digest_service.run_once()
    except Exception as error:
        logger.exception("Scheduled digest delivery failed")
        return {
            "status": "failed",
            "reason": "Scheduled digest delivery failed.",
            "users_considered": 0,
            "users_due": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 1,
            "user_summaries": [],
        }


@router.get("/review-queue")
def review_queue(current_user: CurrentUser = Depends(require_current_user)):
    return get_review_queue(user_id=current_user.id)


@router.get("/spam-rescue")
def spam_rescue_queue(current_user: CurrentUser = Depends(require_current_user)):
    if not config.SPAM_RESCUE_ENABLED:
        raise HTTPException(status_code=404, detail="Spam Rescue is not enabled.")
    return get_spam_rescue_queue(user_id=current_user.id)


@router.post("/review-queue/staged-actions/commit")
def commit_staged_review_queue_actions(
    payload: StagedActionsCommitRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    return commit_staged_actions(
        [
            StagedCommitAction(
                client_action_id=item.client_action_id,
                message_id=item.message_id,
                action=item.action,
                expected_version=item.expected_version,
                rule=(
                    StagedCommitRule(
                        scope=item.rule.scope,
                        account_email=item.rule.account_email,
                        rule_type=item.rule.rule_type,
                        pattern=item.rule.pattern,
                        action=item.rule.action,
                    )
                    if item.rule is not None
                    else None
                ),
            )
            for item in payload.actions
        ],
        idempotency_key=payload.idempotency_key,
        user_id=current_user.id,
    )


@router.get("/messages/processed")
def processed_messages(
    limit: int = Query(default=200, ge=1, le=500),
    current_user: CurrentUser = Depends(require_current_user),
):
    return {"messages": list_processed_messages(limit=limit, user_id=current_user.id)}


@router.post("/messages/{message_id}/recover")
def recover_processed_message_route(
    message_id: int,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        result = recover_processed_message(message_id, user_id=current_user.id)
    except GmailReadonlySyncError as error:
        raise http_exception_for_error(error) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return result


@router.get("/reminders/summary")
def reminder_summary(current_user: CurrentUser = Depends(require_current_user)):
    return get_reminder_summary(user_id=current_user.id)


@router.get("/digests/processed/preview")
def processed_digest_preview(current_user: CurrentUser = Depends(require_current_user)):
    return {"digest": build_processed_digest_payload(user_id=current_user.id)}


@router.get("/settings/notifications")
def notification_settings(current_user: CurrentUser = Depends(require_current_user)):
    return {"settings": get_notification_settings(user_id=current_user.id)}


@router.patch("/settings/notifications")
def update_notification_settings_route(
    payload: NotificationSettingsUpdateRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        settings = update_notification_settings(
            payload.model_dump(exclude_unset=True),
            user_id=current_user.id,
        )
    except ValueError as error:
        raise http_exception_for_error(error) from error
    return {"settings": settings}


@router.get("/settings/ai-digest-attention-notes")
def ai_digest_attention_notes(current_user: CurrentUser = Depends(require_current_user)):
    return {"notes": list_ai_digest_attention_notes(user_id=current_user.id)}


@router.post("/settings/ai-digest-attention-notes")
def create_ai_digest_attention_note_route(
    payload: AIDigestAttentionNoteCreateRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        note = create_ai_digest_attention_note(
            payload.model_dump(),
            user_id=current_user.id,
        )
    except ValueError as error:
        raise http_exception_for_error(error) from error
    return {"note": note}


@router.patch("/settings/ai-digest-attention-notes/{note_id}")
def update_ai_digest_attention_note_route(
    note_id: int,
    payload: AIDigestAttentionNoteUpdateRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        note = update_ai_digest_attention_note(
            note_id,
            payload.model_dump(exclude_unset=True),
            user_id=current_user.id,
        )
    except ValueError as error:
        raise http_exception_for_error(error) from error
    if note is None:
        raise HTTPException(status_code=404, detail="Attention note not found")
    return {"note": note}


@router.delete("/settings/ai-digest-attention-notes/{note_id}")
def delete_ai_digest_attention_note_route(
    note_id: int,
    current_user: CurrentUser = Depends(require_current_user),
):
    deleted = delete_ai_digest_attention_note(note_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Attention note not found")
    return {"deleted": True}


@router.get("/settings/writing-style-cards")
def writing_style_cards(current_user: CurrentUser = Depends(require_current_user)):
    if not writing_style_cards_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Writing style cards are not enabled for this user.")
    return {"cards": list_writing_style_cards(user_id=current_user.id)}


@router.post("/settings/writing-style-cards")
def create_writing_style_card_route(
    payload: WritingStyleCardCreateRequest | None = None,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not writing_style_cards_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Writing style cards are not enabled for this user.")
    try:
        card = sample_sent_mail_writing_style_card(
            user_id=current_user.id,
            account_email=current_user.email,
        )
    except WritingStyleCardSamplingError as error:
        raise http_exception_for_error(error, status_code=409) from error
    except WritingStyleCardValidationError as error:
        raise http_exception_for_error(error, status_code=409) from error
    return {"card": card}


@router.patch("/settings/writing-style-cards/{card_id}")
def update_writing_style_card_route(
    card_id: int,
    payload: WritingStyleCardUpdateRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not writing_style_cards_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Writing style cards are not enabled for this user.")
    try:
        card = update_writing_style_card(
            card_id,
            payload.model_dump(),
            user_id=current_user.id,
        )
    except WritingStyleCardValidationError as error:
        raise http_exception_for_error(error) from error
    if card is None:
        raise HTTPException(status_code=404, detail="Writing style card not found")
    return {"card": card}


@router.post("/settings/writing-style-cards/{card_id}/approve")
def approve_writing_style_card_route(
    card_id: int,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not writing_style_cards_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Writing style cards are not enabled for this user.")
    try:
        card = approve_writing_style_card(card_id, user_id=current_user.id)
    except WritingStyleCardValidationError as error:
        raise http_exception_for_error(error) from error
    if card is None:
        raise HTTPException(status_code=404, detail="Writing style card not found")
    return {"card": card}


@router.post("/settings/writing-style-cards/{card_id}/disable")
def disable_writing_style_card_route(
    card_id: int,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not writing_style_cards_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Writing style cards are not enabled for this user.")
    card = disable_writing_style_card(card_id, user_id=current_user.id)
    if card is None:
        raise HTTPException(status_code=404, detail="Writing style card not found")
    return {"card": card}


@router.post("/messages/{message_id}/action")
def message_action(
    message_id: int,
    payload: MessageActionRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        result = apply_message_action(message_id, payload.action, user_id=current_user.id)
    except ValueError as error:
        raise http_exception_for_error(error) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return result


@router.post("/messages/{message_id}/auto-response-draft")
def auto_response_draft_route(
    message_id: int,
    payload: AutoResponseDraftRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not auto_response_drafts_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Auto-Respond is not enabled for this user.")

    try:
        result = generate_auto_response_draft(
            message_id,
            user_id=current_user.id,
            user_email=current_user.email,
            user_guidance=payload.user_guidance or "",
        )
    except AutoResponseDraftNotConfiguredError as error:
        raise http_exception_for_error(error, status_code=503) from error
    except AutoResponseDraftError as error:
        raise http_exception_for_error(error, status_code=502) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"draft": result}


@router.post("/messages/{message_id}/auto-response-send-preview")
def auto_response_send_preview_route(
    message_id: int,
    payload: AutoResponseSendPreviewRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not auto_response_send_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Auto-Respond send is not enabled for this user.")

    try:
        result = preview_auto_response_send(
            message_id,
            user_id=current_user.id,
            draft_body=payload.draft_body,
            to_email_override=payload.to_email_override,
        )
    except AutoResponseSendValidationError as error:
        raise http_exception_for_error(error, status_code=422) from error
    except AutoResponseSendNotConfiguredError as error:
        raise http_exception_for_error(error, status_code=503) from error
    except AutoResponseSendError as error:
        raise http_exception_for_error(error, status_code=502) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"preview": result.to_dict()}


@router.post("/messages/{message_id}/auto-response-send")
def auto_response_send_route(
    message_id: int,
    payload: AutoResponseSendRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    if not auto_response_send_allowed_for_email(current_user.email):
        raise HTTPException(status_code=403, detail="Auto-Respond send is not enabled for this user.")

    try:
        result = send_auto_response(
            message_id,
            user_id=current_user.id,
            idempotency_key=payload.idempotency_key,
            draft_body=payload.draft_body,
            confirmed=payload.confirmed,
            to_email_override=payload.to_email_override,
            cc=payload.cc,
            bcc=payload.bcc,
            include_context=payload.include_context,
        )
    except AutoResponseSendValidationError as error:
        raise http_exception_for_error(error, status_code=422) from error
    except AutoResponseSendNotConfiguredError as error:
        raise http_exception_for_error(error, status_code=503) from error
    except AutoResponseSendError as error:
        raise http_exception_for_error(error, status_code=502) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"send": result.to_dict()}


@router.post("/messages/{message_id}/live-plan")
def live_message_plan(
    message_id: int,
    payload: MessageActionRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    plan = plan_message_action(message_id, payload.action, user_id=current_user.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"plan": plan.to_dict()}


@router.post("/messages/{message_id}/live-execute")
def live_message_execute(
    message_id: int,
    payload: MessageActionRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        result = execute_message_action(
            message_id,
            payload.action,
            allow_live_writes=True,
            require_feature_flag=True,
            user_id=current_user.id,
        )
    except GmailReadonlySyncError as error:
        raise http_exception_for_error(error) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if result.executed:
        log_executed_message_action(result)
    return {"result": result.to_dict()}


@router.post("/messages/apply-selected")
def bulk_action(
    payload: BulkApplyRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    return apply_selected_actions(
        [item.model_dump() for item in payload.items],
        user_id=current_user.id,
    )


@router.post("/messages/apply-selected-live")
def bulk_live_action(
    payload: BulkApplyRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        return execute_selected_message_actions(
            [item.model_dump() for item in payload.items],
            allow_live_writes=True,
            require_feature_flag=True,
            user_id=current_user.id,
        )
    except GmailReadonlySyncError as error:
        raise http_exception_for_error(error) from error


@router.get("/rules")
def get_rules(current_user: CurrentUser = Depends(require_current_user)):
    return {"rules": list_rules(user_id=current_user.id)}


@router.post("/rules")
def create_rule_route(
    payload: RuleCreateRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    body = payload.model_dump()
    try:
        rule = create_rule(body, user_id=current_user.id)
    except ValueError as error:
        raise http_exception_for_error(error) from error
    reclassified = reclassify_pending_messages(user_id=current_user.id)
    applied = None
    apply_error = None
    if body.get("apply_to_source") and body.get("source_message_id") is not None:
        try:
            applied = apply_message_action(
                body["source_message_id"],
                body["action"],
                user_id=current_user.id,
            )
            if applied is None:
                apply_error = "Source message is no longer available."
        except (GmailReadonlySyncError, ValueError) as error:
            logger.warning(
                "Rule %s created but source message apply failed for source_message_id=%s user_id=%s: %s",
                rule["id"],
                body["source_message_id"],
                current_user.id,
                error,
            )
            apply_error = str(error) or "Source message could not be applied."
    return {"rule": rule, "applied": applied, "apply_error": apply_error, **reclassified}


@router.patch("/rules/{rule_id}")
def update_rule_route(
    rule_id: int,
    payload: RuleUpdateRequest,
    current_user: CurrentUser = Depends(require_current_user),
):
    rule = update_rule(rule_id, payload.model_dump(), user_id=current_user.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"rule": rule}


@router.delete("/rules/{rule_id}")
def delete_rule_route(rule_id: int, current_user: CurrentUser = Depends(require_current_user)):
    deleted = delete_rule(rule_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": True}
