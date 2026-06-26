import type {
  Account,
  AiDigestAttentionNote,
  AutoResponseDraft,
  AutoResponseSend,
  AutoResponseSendPreview,
  AuthStatus,
  Category,
  DigestSenderStatus,
  FeatureFlags,
  LiveActionPlan,
  LiveExecutionResult,
  NotificationSettings,
  ProcessedMessage,
  ProcessedDigestPreview,
  ReminderSummary,
  ReviewQueueResponse,
  Rule,
  SpamRescueQueueResponse,
  StagedQueueCommitAction,
  StagedQueueCommitResponse,
  StagedSpamRescueCommitAction,
  StagedSpamRescueCommitResponse,
  WritingStyleCard,
} from './types'

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.trim() ||
  (import.meta.env.PROD ? '/api' : 'http://127.0.0.1:8000/api')

export class ApiError extends Error {
  status: number
  detail: string
  code: string | null

  constructor(message: string, status: number, code?: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = message
    this.code = code ?? null
  }
}

function errorPayloadFromResponseBody(errorText: string) {
  try {
    const parsed = JSON.parse(errorText) as { detail?: unknown; code?: unknown }
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
      return {
        message: parsed.detail,
        code: typeof parsed.code === 'string' && parsed.code.trim() ? parsed.code : null,
      }
    }
    if (
      parsed.detail &&
      typeof parsed.detail === 'object' &&
      'message' in parsed.detail &&
      typeof parsed.detail.message === 'string' &&
      parsed.detail.message.trim()
    ) {
      return {
        message: parsed.detail.message,
        code:
          'code' in parsed.detail &&
          typeof parsed.detail.code === 'string' &&
          parsed.detail.code.trim()
            ? parsed.detail.code
            : null,
      }
    }
  } catch {
    return { message: errorText || 'Request failed', code: null }
  }
  return { message: errorText || 'Request failed', code: null }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  })

  if (!response.ok) {
    const errorText = await response.text()
    const errorPayload = errorPayloadFromResponseBody(errorText)
    throw new ApiError(errorPayload.message, response.status, errorPayload.code)
  }

  return (await response.json()) as T
}

async function requestFrontend<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  })

  if (!response.ok) {
    const errorText = await response.text()
    const errorPayload = errorPayloadFromResponseBody(errorText)
    throw new ApiError(errorPayload.message, response.status, errorPayload.code)
  }

  return (await response.json()) as T
}

export async function fetchCurrentUser() {
  if (import.meta.env.DEV) {
    return {
      auth_enabled: false,
      user: null,
    } satisfies AuthStatus
  }

  return requestFrontend<AuthStatus>('/auth/me')
}

export async function logoutCurrentUser() {
  if (import.meta.env.DEV) {
    return
  }

  await requestFrontend<{ logged_out: true }>('/auth/logout', { method: 'POST' })
}

export function fetchAccounts() {
  return request<{ accounts: Account[] }>('/accounts')
}

export function fetchFeatureFlags() {
  return request<{ features: FeatureFlags }>('/features')
}

export function fetchDigestSenderStatus() {
  return request<DigestSenderStatus>('/settings/digest-sender')
}

export function fetchWritingStyleCards() {
  return request<{ cards: WritingStyleCard[] }>('/settings/writing-style-cards')
}

export function createWritingStyleCard() {
  return request<{ card: WritingStyleCard }>('/settings/writing-style-cards', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function updateWritingStyleCard(cardId: number, payload: { style_card_markdown: string }) {
  return request<{ card: WritingStyleCard }>(`/settings/writing-style-cards/${cardId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function approveWritingStyleCard(cardId: number) {
  return request<{ card: WritingStyleCard }>(`/settings/writing-style-cards/${cardId}/approve`, {
    method: 'POST',
  })
}

export function disableWritingStyleCard(cardId: number) {
  return request<{ card: WritingStyleCard }>(`/settings/writing-style-cards/${cardId}/disable`, {
    method: 'POST',
  })
}

export function connectMockAccount() {
  return request<{ account: Account }>('/accounts/connect', { method: 'POST' })
}

export function connectGmailAccount() {
  return request<{ account: Account }>('/accounts/connect-gmail', { method: 'POST' })
}

export function connectGmailModifyAccount() {
  return request<{ account: Account }>('/accounts/connect-gmail-modify', { method: 'POST' })
}

export async function startHostedGmailConnect(mode: 'readonly' | 'modify' | 'send', loginHint?: string) {
  const params = new URLSearchParams({ mode })
  if (loginHint) {
    params.set('login_hint', loginHint)
  }
  const response = await request<{
    authorization_url: string
    state: string
    session_id: number
  }>(`/accounts/connect-gmail/start?${params.toString()}`)
  window.location.assign(response.authorization_url)
}

export async function startDigestSenderConnect() {
  const response = await request<{
    authorization_url: string
    state: string
    session_id: number
  }>('/settings/digest-sender/connect-gmail/start')
  window.location.assign(response.authorization_url)
}

export function disableAccount(id: number) {
  return request<{ account: Account }>(`/accounts/${id}/disable`, { method: 'POST' })
}

export function enableAccount(id: number) {
  return request<{ account: Account }>(`/accounts/${id}/enable`, { method: 'POST' })
}

export function syncUnread() {
  return request<{
    synced_messages: number
    failed_accounts?: Array<{ account_email: string; provider: string; reason: string }>
  }>('/sync/unread', { method: 'POST' })
}

export function syncSpamRescue() {
  return request<{
    synced_messages: number
    surfaced_candidates: number
    reconciled_candidates: number
    failed_accounts?: Array<{ account_email: string; provider: string; reason: string }>
  }>('/spam-rescue/sync', { method: 'POST' })
}

export function fetchReviewQueue() {
  return request<ReviewQueueResponse>('/review-queue')
}

export function fetchSpamRescueQueue() {
  return request<SpamRescueQueueResponse>('/spam-rescue')
}

export function commitStagedSpamRescueActions(payload: {
  idempotency_key: string
  actions: StagedSpamRescueCommitAction[]
}) {
  return request<StagedSpamRescueCommitResponse>('/spam-rescue/staged-actions/commit', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function commitStagedQueueActions(payload: {
  idempotency_key: string
  actions: StagedQueueCommitAction[]
}) {
  return request<StagedQueueCommitResponse>('/review-queue/staged-actions/commit', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchProcessedMessages(limit = 200) {
  return request<{ messages: ProcessedMessage[] }>(`/messages/processed?limit=${limit}`)
}

export function recoverProcessedMessage(messageId: number) {
  return request<{
    message_id: number
    selected_action: 'recover'
    labels_added: string[]
    labels_removed: string[]
    current_category: 'needs_review'
  }>(`/messages/${messageId}/recover`, {
    method: 'POST',
  })
}

export function fetchRules() {
  return request<{ rules: Rule[] }>('/rules')
}

export function fetchReminderSummary() {
  return request<ReminderSummary>('/reminders/summary')
}

export function fetchNotificationSettings() {
  return request<{ settings: NotificationSettings }>('/settings/notifications')
}

export function fetchAiDigestAttentionNotes() {
  return request<{ notes: AiDigestAttentionNote[] }>('/settings/ai-digest-attention-notes')
}

export function createAiDigestAttentionNote(
  payload: Pick<AiDigestAttentionNote, 'domain' | 'label' | 'note'> & {
    enabled?: boolean
  },
) {
  return request<{ note: AiDigestAttentionNote }>('/settings/ai-digest-attention-notes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateAiDigestAttentionNote(
  noteId: number,
  payload: Partial<Pick<AiDigestAttentionNote, 'domain' | 'label' | 'note' | 'enabled'>>,
) {
  return request<{ note: AiDigestAttentionNote }>(`/settings/ai-digest-attention-notes/${noteId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteAiDigestAttentionNote(noteId: number) {
  return request<{ deleted: boolean }>(`/settings/ai-digest-attention-notes/${noteId}`, {
    method: 'DELETE',
  })
}

export function fetchProcessedDigestPreview() {
  return request<{ digest: ProcessedDigestPreview }>('/digests/processed/preview')
}

export function updateNotificationSettings(
  payload: Partial<
    Pick<
      NotificationSettings,
      | 'enabled'
      | 'recipient_email'
      | 'timezone'
      | 'morning_enabled'
      | 'morning_time'
      | 'evening_enabled'
      | 'evening_time'
      | 'send_only_if_queue_nonempty'
      | 'digest_enabled'
      | 'digest_time'
      | 'ai_digest_summary_enabled'
    >
  >,
) {
  return request<{ settings: NotificationSettings }>('/settings/notifications', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function applySelected(items: Array<{ message_id: number; action: Category }>) {
  return request<{
    applied: Array<{ message_id: number }>
    failed?: Array<{ message_id: number; action: Category; reason: string }>
    applied_count?: number
    failed_count?: number
  }>('/messages/apply-selected', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
}

export function applySelectedLive(items: Array<{ message_id: number; action: Category }>) {
  return request<{
    results: LiveExecutionResult[]
    executed: number
    blocked: number
    failed: number
  }>('/messages/apply-selected-live', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
}

export function applyAction(messageId: number, action: Category) {
  return request(`/messages/${messageId}/action`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}

export function generateAutoResponseDraft(messageId: number, payload: { user_guidance?: string | null }) {
  return request<{ draft: AutoResponseDraft }>(`/messages/${messageId}/auto-response-draft`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function previewAutoResponseSend(messageId: number, payload: {
  draft_body: string
}) {
  return request<{ preview: AutoResponseSendPreview }>(`/messages/${messageId}/auto-response-send-preview`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendAutoResponse(messageId: number, payload: {
  idempotency_key: string
  draft_body: string
  confirmed: boolean
  include_context?: boolean
}) {
  return request<{ send: AutoResponseSend }>(`/messages/${messageId}/auto-response-send`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchLiveMessagePlan(messageId: number, action: Category) {
  return request<{ plan: LiveActionPlan }>(`/messages/${messageId}/live-plan`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}

export function executeLiveMessage(messageId: number, action: Category) {
  return request<{ result: LiveExecutionResult }>(`/messages/${messageId}/live-execute`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}

export function createRule(payload: {
  scope: string
  account_email?: string | null
  rule_type: string
  pattern: string
  action: Category
  source_message_id?: number
  apply_to_source?: boolean
}) {
  return request<{
    rule: Rule
    applied?: { message_id: number; selected_action: Category } | null
    apply_error?: string | null
    reclassified_messages: number
  }>('/rules', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateRule(id: number, payload: { enabled?: boolean; action?: Category }) {
  return request<{ rule: Rule }>(`/rules/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteRule(id: number) {
  return request<{ deleted: true }>(`/rules/${id}`, { method: 'DELETE' })
}
