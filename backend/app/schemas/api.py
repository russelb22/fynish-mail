from typing import Literal

from pydantic import BaseModel, Field


Category = Literal["trash", "junk_review", "bulk_mail", "needs_review", "keep"]
SpamRescueAction = Literal["restore_to_inbox", "leave_in_spam"]


class AccountOut(BaseModel):
    id: int
    email_address: str
    enabled: bool
    provider: str
    last_sync_at: str | None


class MessageActionRequest(BaseModel):
    action: Category


class AutoResponseDraftRequest(BaseModel):
    user_guidance: str | None = Field(default=None, max_length=1200)


class AutoResponseSendRequest(BaseModel):
    idempotency_key: str = Field(min_length=1)
    draft_body: str = Field(min_length=1, max_length=8000)
    to_email_override: str | None = None
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    confirmed: bool = False
    include_context: bool = True


class AutoResponseSendPreviewRequest(BaseModel):
    draft_body: str = Field(min_length=1, max_length=8000)
    to_email_override: str | None = None


class WritingStyleCardCreateRequest(BaseModel):
    mail_account_id: int | None = Field(default=None, gt=0)


class WritingStyleCardUpdateRequest(BaseModel):
    style_card_markdown: str = Field(min_length=80, max_length=8000)


class BulkMessageActionItem(BaseModel):
    message_id: int
    action: Category


class BulkApplyRequest(BaseModel):
    items: list[BulkMessageActionItem] = Field(default_factory=list)


class StagedActionRulePayload(BaseModel):
    scope: str = "global"
    account_email: str | None = None
    rule_type: str
    pattern: str
    action: Category


class StagedActionCommitItem(BaseModel):
    client_action_id: str | None = None
    message_id: int = Field(gt=0)
    action: Category
    expected_version: str | None = None
    rule: StagedActionRulePayload | None = None


class StagedActionsCommitRequest(BaseModel):
    idempotency_key: str = Field(min_length=1)
    actions: list[StagedActionCommitItem] = Field(min_length=1)


class SpamRescueActionCommitItem(BaseModel):
    client_action_id: str | None = None
    account_email: str
    gmail_message_id: str
    action: SpamRescueAction
    expected_version: str | None = None


class SpamRescueActionsCommitRequest(BaseModel):
    idempotency_key: str = Field(min_length=1)
    actions: list[SpamRescueActionCommitItem] = Field(min_length=1)


class RuleCreateRequest(BaseModel):
    scope: str = "global"
    account_email: str | None = None
    rule_type: str
    pattern: str
    action: Category
    source_message_id: int | None = None
    apply_to_source: bool = False


class RuleUpdateRequest(BaseModel):
    enabled: bool | None = None
    action: Category | None = None


class ReminderCategorySummary(BaseModel):
    category: Category
    display_name: str
    count: int


class ReminderAccountSummary(BaseModel):
    account_email: str
    total_unprocessed: int
    categories: list[ReminderCategorySummary]


class ReminderSummaryResponse(BaseModel):
    generated_at: str
    localhost_url: str
    total_unprocessed: int
    accounts: list[ReminderAccountSummary]
    plain_text_preview: str


class ProcessedMessageOut(BaseModel):
    id: int
    message_id: int | None
    processed_at: str
    account_email: str
    sender: str
    sender_email: str
    sender_domain: str
    subject: str
    preview: str
    selected_action: Category
    recommended_action: Category
    user_overrode: bool
    action_source: str
    created_rule_id: int | None
    received_at: str | None


class NotificationSettingsResponse(BaseModel):
    enabled: bool
    recipient_email: str | None
    timezone: str
    morning_enabled: bool
    morning_time: str
    evening_enabled: bool
    evening_time: str
    send_only_if_queue_nonempty: bool
    digest_enabled: bool
    digest_time: str
    ai_digest_summary_enabled: bool
    created_at: str
    updated_at: str


class NotificationSettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    recipient_email: str | None = None
    timezone: str | None = None
    morning_enabled: bool | None = None
    morning_time: str | None = None
    evening_enabled: bool | None = None
    evening_time: str | None = None
    send_only_if_queue_nonempty: bool | None = None
    digest_enabled: bool | None = None
    digest_time: str | None = None
    ai_digest_summary_enabled: bool | None = None


class AIDigestAttentionNoteCreateRequest(BaseModel):
    domain: str
    label: str | None = None
    note: str
    enabled: bool = True


class AIDigestAttentionNoteUpdateRequest(BaseModel):
    domain: str | None = None
    label: str | None = None
    note: str | None = None
    enabled: bool | None = None
