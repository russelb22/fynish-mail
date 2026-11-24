export type Category =
  | 'trash'
  | 'junk_review'
  | 'bulk_mail'
  | 'needs_review'
  | 'keep'

export type RuleAction = Category
export type SpamRescueAction = 'restore_to_inbox' | 'leave_in_spam'
export type ProcessedAction = Category | SpamRescueAction

export interface ReviewMessage {
  id: number
  gmail_message_id: string
  thread_id: string
  account_email: string
  sender: string
  sender_domain: string
  reply_to: string
  subject: string
  received_at: string
  snippet: string
  body_preview: string
  has_attachments: boolean
  state_version: string | null
  category: Category
  confidence: number
  recommended_action: Category
  queue_source: string
  queue_source_label: string | null
  queue_source_detail: string | null
  default_selected: boolean
  protected: boolean
  reasons: string[]
  protection_reasons: string[]
}

export interface ReviewGroup {
  category: Category
  display_name: string
  count: number
  messages: ReviewMessage[]
}

export interface ReviewAccount {
  account_email: string
  last_sync_at: string | null
  groups: ReviewGroup[]
}

export interface ReviewQueueResponse {
  accounts: ReviewAccount[]
}

export interface FeatureFlags {
  spam_rescue: boolean
}

export interface SpamRescueMessage {
  id: string
  gmail_message_id: string
  thread_id: string
  account_email: string
  sender: string
  sender_domain: string
  reply_to: string
  subject: string
  received_at: string
  snippet: string
  body_preview: string
  has_attachments: boolean
  source_label: 'spam'
  review_surface: 'spam_rescue'
  state_version: string | null
  confidence: number
  rescue_reasons: string[]
  protection_reasons: string[]
  matched_rule_ids: number[]
}

export interface SpamRescueAccount {
  account_email: string
  last_sync_at: string | null
  count: number
  messages: SpamRescueMessage[]
}

export interface SpamRescueQueueResponse {
  accounts: SpamRescueAccount[]
  count: number
  summary: {
    accounts_checked: number
    last_checked_at: string | null
    candidate_count: number
  }
}

export interface SpamRescueSyncResponse {
  synced_messages: number
  surfaced_candidates: number
  reconciled_candidates: number
  failed_accounts?: Array<{ account_email: string; provider: string; reason: string }>
}

export interface StagedSpamRescueCommitAction {
  client_action_id: string
  account_email: string
  gmail_message_id: string
  action: SpamRescueAction
  expected_version: string | null
}

export interface StagedSpamRescueCommitResult {
  client_action_id: string | null
  candidate_id: string
  account_email: string
  gmail_message_id: string
  action: SpamRescueAction
  status: 'committed' | 'failed' | 'stale' | 'blocked'
  code: string | null
  message: string
  executed: boolean
  labels_added: string[]
  labels_removed: string[]
}

export interface StagedSpamRescueCommitResponse {
  committed_count: number
  failed_count: number
  idempotent_replay?: boolean
  results: StagedSpamRescueCommitResult[]
}

export interface DigestSenderStatus {
  configured_email: string | null
  can_manage: boolean
  sender: {
    provider: string
    email_address: string
    has_send_scope: boolean
    has_token: boolean
    auth_status: string
    auth_status_reason: string | null
  } | null
}

export interface StagedQueueCommitAction {
  client_action_id: string
  message_id: number
  action: Category
  expected_version: string | null
  rule?: {
    scope: string
    account_email?: string | null
    rule_type: string
    pattern: string
    action: Category
  }
}

export interface StagedQueueCommitResult {
  client_action_id: string | null
  message_id: number
  action: Category
  status: 'committed' | 'failed' | 'stale' | 'blocked'
  code: string | null
  message: string
  executed: boolean
  labels_added: string[]
  labels_removed: string[]
  rule_id: number | null
  reclassified_messages: number
}

export interface StagedQueueCommitResponse {
  committed_count: number
  failed_count: number
  idempotent_replay?: boolean
  results: StagedQueueCommitResult[]
}

export interface Account {
  id: number
  email_address: string
  enabled: boolean
  provider: string
  last_sync_at: string | null
  oauth_scopes: string[]
  auth_status: string
  auth_status_label: string
  auth_status_reason: string | null
}

export interface Rule {
  id: number
  scope: string
  account_email: string | null
  rule_type: string
  pattern: string
  action: RuleAction
  enabled: boolean
  match_count: number
  last_matched_at: string | null
  created_at: string
}

export interface ReminderCategorySummary {
  category: Category
  display_name: string
  count: number
}

export interface ReminderAccountSummary {
  account_email: string
  total_unprocessed: number
  categories: ReminderCategorySummary[]
}

export interface ReminderSummary {
  generated_at: string
  localhost_url: string
  total_unprocessed: number
  accounts: ReminderAccountSummary[]
  plain_text_preview: string
}

export interface ProcessedMessage {
  id: number
  message_id: number | null
  processed_at: string
  account_email: string
  sender: string
  sender_email: string
  sender_domain: string
  subject: string
  preview: string
  selected_action: ProcessedAction
  selected_action_label: string
  recommended_action: Category | 'spam_rescue'
  user_overrode: boolean
  action_source: string
  action_source_label: string
  created_rule_id: number | null
  received_at: string | null
}

export interface NotificationSettings {
  enabled: boolean
  recipient_email: string | null
  timezone: string
  morning_enabled: boolean
  morning_time: string
  evening_enabled: boolean
  evening_time: string
  send_only_if_queue_nonempty: boolean
  digest_enabled: boolean
  digest_time: string
  created_at: string
  updated_at: string
}

export interface SpamRescueProtectedKeyword {
  id: number
  user_id: number
  keyword: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface DigestProcessedMessage {
  id: number
  processed_at: string
  account_email: string
  selected_action: Category
  selected_action_label: string
  action_source: string
  action_source_label: string
  sender_domain: string
  sender: string
  subject: string
  preview: string
  user_overrode: boolean
  created_rule_id: number | null
}

export interface DigestSenderDomainSummary {
  sender_domain: string
  message_count: number
  counts_by_action: Record<string, number>
  counts_by_source: Record<string, number>
  latest_processed_at: string
  sample_subjects: string[]
}

export interface ProcessedDigestPreview {
  generated_at: string
  digest_type: string
  timezone: string
  window_start: string
  window_end: string
  window_display: string
  recipient_email: string
  processed_count: number
  counts_by_action: Record<string, number>
  counts_by_source: Record<string, number>
  new_rules_count: number
  queue_count: number
  processed_messages: DigestProcessedMessage[]
  top_sender_domains: DigestSenderDomainSummary[]
  processed_overflow_count: number
  frontend_url: string
  digest_enabled: boolean
  digest_time: string
  plain_text_preview: string
  html_preview: string
}

export interface LiveActionPlan {
  message_id: number
  gmail_message_id: string
  account_email: string
  provider: string
  subject: string
  selected_action: Category
  recommended_action: Category
  current_labels: string[]
  labels_to_add: string[]
  labels_to_remove: string[]
  labels_to_preserve: string[]
  will_modify_gmail: boolean
  will_use_trash: boolean
  will_delete_permanently: boolean
  preserves_unread: boolean
  protected: boolean
  allowed: boolean
  safety_notes: string[]
}

export interface LiveExecutionResult {
  message_id: number
  gmail_message_id: string
  account_email: string
  selected_action: Category
  status: string
  executed: boolean
  allowed: boolean
  live_writes_enabled: boolean
  oauth_scope_ready: boolean
  labels_added: string[]
  labels_removed: string[]
  response_label_ids: string[]
  notes: string[]
}

export interface AuthenticatedUser {
  email: string
  name: string
  picture: string | null
}

export interface AuthStatus {
  auth_enabled: boolean
  user: AuthenticatedUser | null
}
