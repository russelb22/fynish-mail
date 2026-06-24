import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import fynishMailLogo from './assets/fynish-mail-logo.svg'
import {
  ApiError,
  approveWritingStyleCard,
  commitStagedSpamRescueActions,
  commitStagedQueueActions,
  connectGmailModifyAccount,
  connectMockAccount,
  createWritingStyleCard,
  createAiDigestAttentionNote,
  deleteAiDigestAttentionNote,
  createRule,
  deleteRule,
  disableWritingStyleCard,
  disableAccount,
  enableAccount,
  fetchAiDigestAttentionNotes,
  fetchAccounts,
  fetchCurrentUser,
  fetchDigestSenderStatus,
  fetchFeatureFlags,
  fetchNotificationSettings,
  fetchProcessedMessages,
  fetchReviewQueue,
  fetchSpamRescueQueue,
  fetchWritingStyleCards,
  recoverProcessedMessage,
  fetchRules,
  generateAutoResponseDraft,
  logoutCurrentUser,
  previewAutoResponseSend,
  sendAutoResponse,
  startDigestSenderConnect,
  startHostedGmailConnect,
  updateAiDigestAttentionNote,
  syncUnread,
  updateNotificationSettings,
  updateWritingStyleCard,
  updateRule,
} from './api'
import type {
  Account,
  AiDigestAttentionNote,
  AuthStatus,
  AutoResponseDraft,
  AutoResponseSend,
  Category,
  DigestSenderStatus,
  FeatureFlags,
  NotificationSettings,
  ProcessedMessage,
  ReviewAccount,
  ReviewMessage,
  Rule,
  SpamRescueAction,
  SpamRescueAccount,
  SpamRescueMessage,
  WritingStyleCard,
} from './types'

type ViewName = 'queue' | 'spam_rescue' | 'processed' | 'rules' | 'accounts' | 'settings'

type ActionMap = Record<number, Category>
type SettingsFieldErrors = Partial<Record<'recipient_email' | 'digest_time' | 'timezone', string>>
type AttentionNoteDraft = {
  domain: string
  label: string
  note: string
}
type StagedQueueAction = {
  clientActionId: string
  messageId: number
  accountEmail: string
  sender: string
  senderDomain: string
  subject: string
  action: Category
  actionLabel: string
  expectedVersion: string | null
  stagedAt: string
  rule?: {
    scope: string
    accountEmail: string | null
    ruleType: string
    pattern: string
    action: Category
  }
}
type StagedSpamRescueAction = {
  clientActionId: string
  candidateId: string
  accountEmail: string
  gmailMessageId: string
  sender: string
  senderDomain: string
  subject: string
  action: SpamRescueAction
  actionLabel: string
  expectedVersion: string | null
  stagedAt: string
}
type FailedSyncAccount = {
  account_email: string
  provider: string
  reason: string
}

type SyncUnreadResult = {
  synced_messages: number
  failed_accounts?: FailedSyncAccount[]
}

const ACTION_LABELS: Record<Category, string> = {
  trash: 'Trash',
  junk_review: 'Junk',
  bulk_mail: 'Bulk',
  needs_review: 'Needs Review',
  keep: 'Keep',
}

const QUEUE_CLASSIFICATION_LABELS: Record<Category, string> = {
  trash: 'Trash',
  junk_review: 'Junk',
  bulk_mail: 'Bulk',
  needs_review: 'Review',
  keep: 'Keep',
}

const PROCESSED_ACTION_LABELS: Record<string, string> = {
  trash: 'Trash Msg',
  junk_review: 'Junk Rule',
  bulk_mail: 'Bulk Rule',
  needs_review: 'Needs Review',
  keep: 'Keep Msg',
  restore_to_inbox: 'Restored',
  leave_in_spam: 'Left in Spam',
}

const SPAM_RESCUE_ACTION_LABELS: Record<SpamRescueAction, string> = {
  restore_to_inbox: 'Restore to Inbox',
  leave_in_spam: 'Leave in Spam',
}

const ACTION_SOURCE_LABELS: Record<string, string> = {
  manual: 'Manual',
  rule_auto_apply: 'Rule auto',
  high_confidence_auto_clean: 'Auto-clean',
  recovery: 'Recovery',
  spam_rescue: 'Spam Rescue',
  legacy_unknown: 'Legacy',
}

const REVIEW_QUEUE_KEYBOARD_ACTIONS: Record<string, Category> = {
  '1': 'keep',
  '2': 'bulk_mail',
  '3': 'junk_review',
  '4': 'trash',
}
const SCROLL_TOP_VIEWS = new Set<ViewName>(['queue', 'spam_rescue', 'processed', 'rules'])
const SCROLL_TOP_SHOW_THRESHOLD = 360
const SCROLL_TOP_HIDE_THRESHOLD = 240
const DEFAULT_FEATURE_FLAGS: FeatureFlags = {
  auto_response_drafts: false,
  auto_response_send: false,
  writing_style_cards: false,
  spam_rescue: false,
}

function formatActionSource(source: string | null | undefined) {
  if (!source) {
    return ACTION_SOURCE_LABELS.manual
  }
  return ACTION_SOURCE_LABELS[source] ?? source.replaceAll('_', ' ')
}

function buildClientActionId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `staged-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function isEditableKeyboardTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  const tagName = target.tagName.toLowerCase()
  return (
    target.isContentEditable ||
    tagName === 'input' ||
    tagName === 'textarea' ||
    tagName === 'select'
  )
}

const SETTINGS_ITEMS = [
  {
    title: 'One Gmail connection path',
    description: 'Hosted Fynish now assumes the modify-capable Gmail path for real account use.',
    value: 'Modify-capable only',
  },
  {
    title: 'Live Gmail behavior',
    description: 'Modify-capable Gmail accounts act live by default without a separate live-mode toggle.',
    value: 'Always on for modify-capable accounts',
  },
  {
    title: 'Needs Review behavior',
    description: 'Messages stay in the Inbox by default when Fynish is uncertain.',
    value: 'Leave in Inbox',
  },
  {
    title: 'Preserve unread state',
    description: 'All Gmail-side actions are designed to keep the UNREAD label intact in V1.',
    value: 'Enabled',
  },
]

function formatRelativeDate(value: string | null) {
  if (!value) {
    return 'Not synced yet'
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatCompactDateTime(value: string | null) {
  if (!value) {
    return 'Unknown time'
  }

  const parts = new Intl.DateTimeFormat(undefined, {
    month: 'numeric',
    day: 'numeric',
    year: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(new Date(value))

  const lookup = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const month = lookup.month ?? ''
  const day = lookup.day ?? ''
  const year = lookup.year ?? ''
  const hour = lookup.hour ?? ''
  const minute = lookup.minute ?? ''
  const dayPeriod = (lookup.dayPeriod ?? '').toUpperCase()

  return `${month}/${day}/${year}, ${hour}:${minute}${dayPeriod}`
}

function formatConfidencePercent(confidence: number) {
  const normalized = Number.isFinite(confidence) ? confidence : 0
  const percent = Math.max(0, Math.min(100, Math.round(normalized * 100)))
  return `${percent}%`
}

function queueCategoryClassName(category: string) {
  switch (category) {
    case 'bulk_mail':
      return 'bulk'
    case 'junk_review':
      return 'junk'
    case 'needs_review':
    case 'restore_to_inbox':
    case 'leave_in_spam':
      return 'review'
    default:
      return category
  }
}

function createIdempotencyKey(prefix: string) {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function decodeHtmlEntities(value: string) {
  return value
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&amp;/g, '&')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
}

function cleanPreviewText(value: string) {
  const decoded = decodeHtmlEntities(value)
  return decoded
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\s*>\s*$/gm, '>')
    .replace(/(>\n){3,}/g, '>\n>\n')
    .trim()
}

function buildPreviewText(message: ReviewMessage) {
  const snippet = message.snippet?.trim()
  const bodyPreview = message.body_preview?.trim()

  if (snippet && bodyPreview && bodyPreview !== snippet) {
    return cleanPreviewText(`${snippet} ${bodyPreview}`.trim())
  }

  return cleanPreviewText(snippet || bodyPreview || 'No preview available.')
}

function buildSpamRescuePreviewText(message: SpamRescueMessage) {
  const snippet = message.snippet?.trim()
  const bodyPreview = message.body_preview?.trim()

  if (snippet && bodyPreview && bodyPreview !== snippet) {
    return cleanPreviewText(`${snippet} ${bodyPreview}`.trim())
  }

  return cleanPreviewText(snippet || bodyPreview || 'No preview available.')
}

function formatProvider(provider: string) {
  if (provider === 'gmail_readonly') {
    return 'Google Gmail'
  }
  if (provider === 'mock_gmail') {
    return 'Mock Gmail'
  }
  return provider
}

function formatSyncResultNotice(result: SyncUnreadResult) {
  const failedAccounts = result.failed_accounts ?? []
  const syncedText = `Synced ${result.synced_messages} unread inbox messages into the review queue.`
  if (failedAccounts.length === 0) {
    return syncedText
  }

  const failedDetails = failedAccounts
    .slice(0, 3)
    .map((account) => `${account.account_email}: ${account.reason}`)
    .join('; ')
  const moreFailures =
    failedAccounts.length > 3 ? `; and ${failedAccounts.length - 3} more` : ''
  const failedText =
    failedAccounts.length === 1
      ? `${failedAccounts[0].account_email} could not be refreshed: ${failedAccounts[0].reason}`
      : `${failedAccounts.length} accounts could not be refreshed: ${failedDetails}${moreFailures}`

  return result.synced_messages > 0 ? `${syncedText} ${failedText}.` : `${failedText}.`
}

function accountAccessLabel(account: Account) {
  if (account.provider !== 'gmail_readonly') {
    return 'Mock'
  }
  if (account.oauth_scopes.includes('https://www.googleapis.com/auth/gmail.modify')) {
    return 'Modify-capable'
  }
  return 'Read-only'
}

function accountAuthStatusLabel(account: Account) {
  if (account.provider !== 'gmail_readonly') {
    return null
  }
  return account.auth_status_label || 'Connected'
}

function accountAuthStatusClass(account: Account) {
  if (account.auth_status === 'reconnect_required') {
    return 'account-auth-pill account-auth-pill-warning'
  }
  return 'account-auth-pill'
}

function isMockAccount(account: Account | undefined) {
  return account?.provider === 'mock_gmail'
}

function isApiNotFound(error: unknown) {
  return error instanceof ApiError && error.status === 404
}

function isGmailReconnectRequired(error: unknown) {
  return error instanceof ApiError && error.code === 'gmail_reconnect_required'
}

function userFacingErrorMessage(error: unknown, fallback: string) {
  if (isGmailReconnectRequired(error)) {
    const message = error instanceof Error ? error.message : fallback
    return `${message} Use Reconnect Gmail on the affected account.`
  }
  return error instanceof Error ? error.message : fallback
}

function settingsFieldErrorsFromError(error: unknown): SettingsFieldErrors {
  const message = error instanceof Error ? error.message : ''
  if (message.startsWith('recipient_email ')) {
    return { recipient_email: message }
  }
  if (message.startsWith('digest_time ')) {
    return { digest_time: message }
  }
  if (message.startsWith('timezone ')) {
    return { timezone: message }
  }
  return {}
}

function attentionNoteDraftsFromNotes(notes: AiDigestAttentionNote[]) {
  return notes.reduce<Record<number, AttentionNoteDraft>>((drafts, note) => {
    drafts[note.id] = {
      domain: note.domain,
      label: note.label,
      note: note.note,
    }
    return drafts
  }, {})
}

function parseInitialUiState(): { view: ViewName | null; notice: string | null } {
  if (typeof window === 'undefined') {
    return { view: null as ViewName | null, notice: null as string | null }
  }

  const url = new URL(window.location.href)
  const rawView = url.searchParams.get('view')
  const connectStatus = url.searchParams.get('gmail_connect')
  const connectMessage = url.searchParams.get('gmail_message')
  const connectCode = url.searchParams.get('gmail_code')
  const hasOauthStatus = Boolean(connectStatus || connectMessage || connectCode)
  const view: ViewName | null =
    hasOauthStatus && (
      rawView === 'queue' ||
      rawView === 'spam_rescue' ||
      rawView === 'processed' ||
      rawView === 'rules' ||
      rawView === 'accounts' ||
      rawView === 'settings'
    )
      ? rawView
      : null

  let notice: string | null = null
  if (connectStatus === 'success' && connectMessage) {
    notice = connectMessage
  } else if (connectStatus === 'error' && connectMessage) {
    notice = connectMessage
  }

  if (rawView || connectStatus || connectMessage || connectCode) {
    if (view) {
      url.searchParams.set('view', view)
    } else {
      url.searchParams.delete('view')
    }
    url.searchParams.delete('gmail_connect')
    url.searchParams.delete('gmail_message')
    url.searchParams.delete('gmail_code')
    const nextUrl = `${url.pathname}${url.searchParams.toString() ? `?${url.searchParams.toString()}` : ''}${url.hash}`
    window.history.replaceState({}, '', nextUrl)
  }

  return { view, notice }
}

function App() {
  const initialUiState = useMemo(() => parseInitialUiState(), [])
  const [view, setView] = useState<ViewName>(initialUiState.view ?? 'queue')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [queue, setQueue] = useState<ReviewAccount[]>([])
  const [spamRescueQueue, setSpamRescueQueue] = useState<SpamRescueAccount[]>([])
  const [processedMessages, setProcessedMessages] = useState<ProcessedMessage[]>([])
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings | null>(null)
  const [digestSenderStatus, setDigestSenderStatus] = useState<DigestSenderStatus | null>(null)
  const [aiDigestAttentionNotes, setAiDigestAttentionNotes] = useState<AiDigestAttentionNote[]>([])
  const [attentionNoteDrafts, setAttentionNoteDrafts] = useState<Record<number, AttentionNoteDraft>>({})
  const [writingStyleCards, setWritingStyleCards] = useState<WritingStyleCard[]>([])
  const [writingStyleDrafts, setWritingStyleDrafts] = useState<Record<number, string>>({})
  const [newAttentionDomain, setNewAttentionDomain] = useState('')
  const [newAttentionLabel, setNewAttentionLabel] = useState('')
  const [newAttentionNote, setNewAttentionNote] = useState('')
  const [settingsErrors, setSettingsErrors] = useState<SettingsFieldErrors>({})
  const [expandedProcessedId, setExpandedProcessedId] = useState<number | null>(null)
  const [expandedQueuePreviewId, setExpandedQueuePreviewId] = useState<number | null>(null)
  const [autoResponseMessage, setAutoResponseMessage] = useState<ReviewMessage | null>(null)
  const [autoResponseGuidance, setAutoResponseGuidance] = useState('')
  const [autoResponseDraft, setAutoResponseDraft] = useState<AutoResponseDraft | null>(null)
  const [autoResponseDraftBody, setAutoResponseDraftBody] = useState('')
  const [autoResponseSendResult, setAutoResponseSendResult] = useState<AutoResponseSend | null>(null)
  const [autoResponseBusy, setAutoResponseBusy] = useState(false)
  const [autoResponseError, setAutoResponseError] = useState<string | null>(null)
  const [rules, setRules] = useState<Rule[]>([])
  const [authStatus, setAuthStatus] = useState<AuthStatus>({
    auth_enabled: false,
    user: null,
  })
  const [featureFlags, setFeatureFlags] = useState<FeatureFlags>(DEFAULT_FEATURE_FLAGS)
  const [actionMap, setActionMap] = useState<ActionMap>({})
  const [stagedActions, setStagedActions] = useState<Record<number, StagedQueueAction>>({})
  const [stagedOrder, setStagedOrder] = useState<number[]>([])
  const [stagedSpamRescueActions, setStagedSpamRescueActions] = useState<Record<string, StagedSpamRescueAction>>({})
  const [stagedSpamRescueOrder, setStagedSpamRescueOrder] = useState<string[]>([])
  const [commitBusy, setCommitBusy] = useState(false)
  const [commitErrors, setCommitErrors] = useState<Record<number, string>>({})
  const [spamRescueCommitErrors, setSpamRescueCommitErrors] = useState<Record<string, string>>({})
  const [showMockAccounts, setShowMockAccounts] = useState(false)
  const [showScrollTopButton, setShowScrollTopButton] = useState(false)
  const [newRulePattern, setNewRulePattern] = useState('')
  const [newRuleType, setNewRuleType] = useState('domain')
  const [newRuleAction, setNewRuleAction] = useState<Category>('keep')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState(
    initialUiState.notice ?? 'Accounts are ready. Refresh Gmail to load the current review queue.',
  )
  const pendingScrollRestoreRef = useRef<number | null>(null)
  const commitIdempotencyKeyRef = useRef<string | null>(null)

  async function loadAll(options?: { preserveCommitErrors?: boolean; preserveScroll?: boolean }) {
    if (options?.preserveScroll && typeof window !== 'undefined') {
      pendingScrollRestoreRef.current = window.scrollY
    }
    if (!options?.preserveCommitErrors) {
      setCommitErrors({})
      setSpamRescueCommitErrors({})
    }

    setLoading(true)
    try {
      const [
        processedData,
        accountData,
        queueData,
        ruleData,
        authData,
        settingsData,
        digestSenderData,
        attentionNotesData,
        featureData,
      ] = await Promise.all([
        fetchProcessedMessages(),
        fetchAccounts(),
        fetchReviewQueue(),
        fetchRules(),
        fetchCurrentUser(),
        fetchNotificationSettings(),
        fetchDigestSenderStatus(),
        fetchAiDigestAttentionNotes(),
        fetchFeatureFlags(),
      ])
      const styleCardsData = featureData.features.writing_style_cards
        ? await fetchWritingStyleCards()
        : { cards: [] }
      const spamRescueData = featureData.features.spam_rescue
        ? await fetchSpamRescueQueue()
        : { accounts: [], count: 0 }
      setProcessedMessages(processedData.messages)
      setExpandedProcessedId((current) =>
        current !== null && processedData.messages.some((message) => message.id === current)
          ? current
          : null,
      )
      setAccounts(accountData.accounts)
      setQueue(queueData.accounts)
      setRules(ruleData.rules)
      setAuthStatus(authData)
      setFeatureFlags(featureData.features)
      setSpamRescueQueue(spamRescueData.accounts)
      setNotificationSettings(settingsData.settings)
      setDigestSenderStatus(digestSenderData)
      setAiDigestAttentionNotes(attentionNotesData.notes)
      setAttentionNoteDrafts(attentionNoteDraftsFromNotes(attentionNotesData.notes))
      setWritingStyleCards(styleCardsData.cards)
      setWritingStyleDrafts(
        Object.fromEntries(
          styleCardsData.cards.map((card) => [card.id, card.style_card_markdown]),
        ),
      )
      const nextActions: ActionMap = {}

      queueData.accounts.forEach((account) => {
        account.groups.forEach((group) => {
          group.messages.forEach((message) => {
            nextActions[message.id] = message.recommended_action
          })
        })
      })

      setActionMap(nextActions)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void Promise.resolve().then(() => loadAll())
  }, [])

  useEffect(() => {
    if (loading || pendingScrollRestoreRef.current === null || typeof window === 'undefined') {
      return
    }

    const scrollTop = pendingScrollRestoreRef.current
    pendingScrollRestoreRef.current = null
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: scrollTop, behavior: 'auto' })
    })
  }, [loading, queue, spamRescueQueue])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    if (!SCROLL_TOP_VIEWS.has(view)) {
      window.requestAnimationFrame(() => {
        setShowScrollTopButton(false)
      })
      return
    }

    function updateScrollTopVisibility() {
      setShowScrollTopButton((current) => {
        if (current) {
          return window.scrollY >= SCROLL_TOP_HIDE_THRESHOLD
        }
        return window.scrollY >= SCROLL_TOP_SHOW_THRESHOLD
      })
    }

    updateScrollTopVisibility()
    window.addEventListener('scroll', updateScrollTopVisibility, { passive: true })
    return () => window.removeEventListener('scroll', updateScrollTopVisibility)
  }, [view])

  const accountMap = useMemo(
    () => Object.fromEntries(accounts.map((account) => [account.email_address, account])),
    [accounts],
  )

  const canUseDevelopmentHarness = import.meta.env.DEV

  const visibleAccounts = useMemo(
    () =>
      accounts.filter((account) => {
        if (!isMockAccount(account)) {
          return true
        }
        return canUseDevelopmentHarness && showMockAccounts
      }),
    [accounts, canUseDevelopmentHarness, showMockAccounts],
  )

  const signedInStyleEmail = authStatus.user?.email ?? 'the signed-in Fynish user'

  const signedInWritingStyleCards = useMemo(() => {
    const userEmail = authStatus.user?.email?.toLowerCase()
    const activeStatuses = new Set(['draft', 'approved'])
    if (!userEmail) {
      return writingStyleCards.filter((card) => activeStatuses.has(card.status))
    }
    return writingStyleCards.filter(
      (card) =>
        card.account_email.toLowerCase() === userEmail &&
        activeStatuses.has(card.status),
    )
  }, [authStatus.user?.email, writingStyleCards])

  const latestVisibleAccountSyncAt = useMemo(() => {
    const timestamps = visibleAccounts
      .map((account) => account.last_sync_at)
      .filter((value): value is string => Boolean(value))

    if (timestamps.length === 0) {
      return null
    }

    return timestamps.reduce((latest, current) =>
      new Date(current).getTime() > new Date(latest).getTime() ? current : latest,
    )
  }, [visibleAccounts])

  const visibleQueue = useMemo(
    () =>
      queue.filter((account) => {
        const accountInfo = accountMap[account.account_email]
        return !isMockAccount(accountInfo) || (canUseDevelopmentHarness && showMockAccounts)
      }),
    [accountMap, canUseDevelopmentHarness, queue, showMockAccounts],
  )

  const visibleSpamRescueQueue = useMemo(
    () =>
      spamRescueQueue
        .map((account) => {
          const accountInfo = accountMap[account.account_email]
          if (isMockAccount(accountInfo) && !(canUseDevelopmentHarness && showMockAccounts)) {
            return null
          }
          return account
        })
        .filter((account): account is SpamRescueAccount => Boolean(account)),
    [accountMap, canUseDevelopmentHarness, showMockAccounts, spamRescueQueue],
  )

  const activeVisibleSpamRescueQueue = useMemo(
    () =>
      visibleSpamRescueQueue
        .map((account) => {
          const messages = account.messages.filter((message) => !stagedSpamRescueActions[message.id])
          return {
            ...account,
            count: messages.length,
            messages,
          }
        })
        .filter((account) => account.messages.length > 0),
    [stagedSpamRescueActions, visibleSpamRescueQueue],
  )

  const activeVisibleQueue = useMemo(
    () =>
      visibleQueue.map((account) => ({
        ...account,
        groups: account.groups.map((group) => {
          const messages = group.messages.filter((message) => !stagedActions[message.id])
          return {
            ...group,
            count: messages.length,
            messages,
          }
        }),
      })),
    [stagedActions, visibleQueue],
  )

  const nextReviewMessage = useMemo(() => {
    for (const account of activeVisibleQueue) {
      for (const group of account.groups) {
        if (group.messages.length > 0) {
          return group.messages[0]
        }
      }
    }
    return null
  }, [activeVisibleQueue])

  const visibleProcessedMessages = useMemo(
    () =>
      processedMessages.filter((message) => {
        const accountInfo = accountMap[message.account_email]
        return !isMockAccount(accountInfo) || (canUseDevelopmentHarness && showMockAccounts)
      }),
    [accountMap, canUseDevelopmentHarness, processedMessages, showMockAccounts],
  )

  const queueStats = useMemo(() => {
    let totalMessages = 0

    activeVisibleQueue.forEach((account) => {
      account.groups.forEach((group) => {
        totalMessages += group.count
      })
    })

    return {
      accountCount: activeVisibleQueue.length,
      totalMessages,
    }
  }, [activeVisibleQueue])

  const visibleSpamRescueCount = useMemo(
    () => activeVisibleSpamRescueQueue.reduce((total, account) => total + account.messages.length, 0),
    [activeVisibleSpamRescueQueue],
  )

  const stagedSpamRescueList = useMemo(
    () =>
      stagedSpamRescueOrder
        .map((candidateId) => stagedSpamRescueActions[candidateId])
        .filter((action): action is StagedSpamRescueAction => Boolean(action)),
    [stagedSpamRescueActions, stagedSpamRescueOrder],
  )

  const stagedSpamRescueByAccount = useMemo(() => {
    const grouped = new Map<string, StagedSpamRescueAction[]>()
    stagedSpamRescueList.forEach((item) => {
      grouped.set(item.accountEmail, [...(grouped.get(item.accountEmail) ?? []), item])
    })
    return Array.from(grouped.entries()).map(([accountEmail, items]) => ({
      accountEmail,
      items,
    }))
  }, [stagedSpamRescueList])

  const monitoredQueueAccounts = useMemo(
    () =>
      visibleAccounts.map((account) => {
        const queueAccount = activeVisibleQueue.find((queueItem) => queueItem.account_email === account.email_address)
        return {
          account,
          queueAccount,
        }
      }),
    [activeVisibleQueue, visibleAccounts],
  )

  const stagedList = useMemo(
    () =>
      stagedOrder
        .map((messageId) => stagedActions[messageId])
        .filter((action): action is StagedQueueAction => Boolean(action)),
    [stagedActions, stagedOrder],
  )

  const stagedByAccount = useMemo(() => {
    const grouped = new Map<string, StagedQueueAction[]>()
    stagedList.forEach((item) => {
      grouped.set(item.accountEmail, [...(grouped.get(item.accountEmail) ?? []), item])
    })
    return Array.from(grouped.entries()).map(([accountEmail, items]) => ({
      accountEmail,
      items,
    }))
  }, [stagedList])

  const totalStagedCount = stagedList.length + stagedSpamRescueList.length

  async function handleSync() {
    setBusy(true)
    setNotice('Refreshing unread Inbox messages from connected Gmail and mock accounts...')
    try {
      const result = await syncUnread()
      await loadAll()
      setNotice(formatSyncResultNotice(result))
    } catch (error) {
      setNotice(userFacingErrorMessage(error, 'Sync failed.'))
    } finally {
      setBusy(false)
    }
  }

  function stageSingleAction(message: ReviewMessage, action: Category) {
    commitIdempotencyKeyRef.current = null
    setAction(message.id, action)
    setCommitErrors((current) => {
      const next = { ...current }
      delete next[message.id]
      return next
    })
    setStagedActions((current) => ({
      ...current,
      [message.id]: {
        clientActionId: current[message.id]?.clientActionId ?? buildClientActionId(),
        messageId: message.id,
        accountEmail: message.account_email,
        sender: message.sender,
        senderDomain: message.sender_domain,
        subject: message.subject,
        action,
        actionLabel: ACTION_LABELS[action],
        expectedVersion: message.state_version,
        stagedAt: new Date().toISOString(),
      },
    }))
    setStagedOrder((current) => (current.includes(message.id) ? current : [...current, message.id]))
    setNotice(`${ACTION_LABELS[action]} staged for "${message.subject}". Commit when ready.`)
  }

  function stageRuleAction(message: ReviewMessage, action: Category) {
    commitIdempotencyKeyRef.current = null
    const pattern = message.sender_domain
    setAction(message.id, action)
    setCommitErrors((current) => {
      const next = { ...current }
      delete next[message.id]
      return next
    })
    setStagedActions((current) => ({
      ...current,
      [message.id]: {
        clientActionId: current[message.id]?.clientActionId ?? buildClientActionId(),
        messageId: message.id,
        accountEmail: message.account_email,
        sender: message.sender,
        senderDomain: message.sender_domain,
        subject: message.subject,
        action,
        actionLabel: ACTION_LABELS[action],
        expectedVersion: message.state_version,
        stagedAt: new Date().toISOString(),
        rule: {
          scope: 'global',
          accountEmail: null,
          ruleType: 'domain',
          pattern,
          action,
        },
      },
    }))
    setStagedOrder((current) => (current.includes(message.id) ? current : [...current, message.id]))
    setNotice(`Rule for ${pattern} staged with ${ACTION_LABELS[action]}. Commit when ready.`)
  }

  function handleUndoLastStagedAction() {
    const lastMessageId = stagedOrder.at(-1)
    if (lastMessageId === undefined) {
      return
    }
    const staged = stagedActions[lastMessageId]
    commitIdempotencyKeyRef.current = null
    setStagedActions((current) => {
      const next = { ...current }
      delete next[lastMessageId]
      return next
    })
    setStagedOrder((current) => current.slice(0, -1))
    setNotice(staged ? `Restored "${staged.subject}" to the queue.` : 'Restored the last staged message.')
  }

  function handleDiscardStagedActions() {
    const count = stagedList.length
    commitIdempotencyKeyRef.current = null
    setStagedActions({})
    setStagedOrder([])
    setCommitErrors({})
    setNotice(count === 1 ? 'Discarded 1 staged change.' : `Discarded ${count} staged changes.`)
  }

  async function handleCommitStagedActions() {
    if (stagedList.length === 0 || commitBusy) {
      return
    }
    const idempotencyKey = commitIdempotencyKeyRef.current ?? buildClientActionId()
    commitIdempotencyKeyRef.current = idempotencyKey
    setCommitBusy(true)
    setBusy(true)
    setNotice(stagedList.length === 1 ? 'Committing 1 staged change...' : `Committing ${stagedList.length} staged changes...`)
    try {
      const response = await commitStagedQueueActions({
        idempotency_key: idempotencyKey,
        actions: stagedList.map((item) => ({
          client_action_id: item.clientActionId,
          message_id: item.messageId,
          action: item.action,
          expected_version: item.expectedVersion,
          ...(item.rule
            ? {
                rule: {
                  scope: item.rule.scope,
                  account_email: item.rule.accountEmail,
                  rule_type: item.rule.ruleType,
                  pattern: item.rule.pattern,
                  action: item.rule.action,
                },
              }
            : {}),
        })),
      })
      const failedResults = response.results.filter((result) => result.status !== 'committed')
      const failedByMessage = Object.fromEntries(
        failedResults.map((result) => [result.message_id, result.message]),
      )
      setCommitErrors(failedByMessage)
      commitIdempotencyKeyRef.current = null
      setStagedActions({})
      setStagedOrder([])
      await loadAll({ preserveCommitErrors: true, preserveScroll: true })
      const committedText =
        response.committed_count === 1
          ? 'Committed 1 change.'
          : `Committed ${response.committed_count} changes.`
      const failedText =
        response.failed_count === 0
          ? ''
          : response.failed_count === 1
            ? ' 1 message needs attention.'
            : ` ${response.failed_count} messages need attention.`
      setNotice(`${committedText}${failedText}`)
    } catch (error) {
      setNotice(userFacingErrorMessage(error, 'Could not commit staged changes.'))
    } finally {
      setCommitBusy(false)
      setBusy(false)
    }
  }

  function stageSpamRescueAction(message: SpamRescueMessage, action: SpamRescueAction) {
    commitIdempotencyKeyRef.current = null
    setSpamRescueCommitErrors((current) => {
      const next = { ...current }
      delete next[message.id]
      return next
    })
    setStagedSpamRescueActions((current) => ({
      ...current,
      [message.id]: {
        clientActionId: current[message.id]?.clientActionId ?? buildClientActionId(),
        candidateId: message.id,
        accountEmail: message.account_email,
        gmailMessageId: message.gmail_message_id,
        sender: message.sender,
        senderDomain: message.sender_domain,
        subject: message.subject,
        action,
        actionLabel: SPAM_RESCUE_ACTION_LABELS[action],
        expectedVersion: message.state_version,
        stagedAt: new Date().toISOString(),
      },
    }))
    setStagedSpamRescueOrder((current) =>
      current.includes(message.id) ? current : [...current, message.id],
    )
    setNotice(`${SPAM_RESCUE_ACTION_LABELS[action]} staged for "${message.subject}". Commit when ready.`)
  }

  function handleUndoLastStagedSpamRescueAction() {
    const lastCandidateId = stagedSpamRescueOrder.at(-1)
    if (lastCandidateId === undefined) {
      return
    }
    const staged = stagedSpamRescueActions[lastCandidateId]
    commitIdempotencyKeyRef.current = null
    setStagedSpamRescueActions((current) => {
      const next = { ...current }
      delete next[lastCandidateId]
      return next
    })
    setStagedSpamRescueOrder((current) => current.slice(0, -1))
    setNotice(staged ? `Restored "${staged.subject}" to Spam Rescue.` : 'Restored the last staged Spam Rescue candidate.')
  }

  function handleDiscardStagedSpamRescueActions() {
    const count = stagedSpamRescueList.length
    commitIdempotencyKeyRef.current = null
    setStagedSpamRescueActions({})
    setStagedSpamRescueOrder([])
    setSpamRescueCommitErrors({})
    setNotice(count === 1 ? 'Discarded 1 Spam Rescue change.' : `Discarded ${count} Spam Rescue changes.`)
  }

  async function handleCommitStagedSpamRescueActions() {
    if (stagedSpamRescueList.length === 0 || commitBusy) {
      return
    }
    const idempotencyKey = commitIdempotencyKeyRef.current ?? buildClientActionId()
    commitIdempotencyKeyRef.current = idempotencyKey
    setCommitBusy(true)
    setBusy(true)
    setNotice(
      stagedSpamRescueList.length === 1
        ? 'Committing 1 Spam Rescue change...'
        : `Committing ${stagedSpamRescueList.length} Spam Rescue changes...`,
    )
    try {
      const response = await commitStagedSpamRescueActions({
        idempotency_key: idempotencyKey,
        actions: stagedSpamRescueList.map((item) => ({
          client_action_id: item.clientActionId,
          account_email: item.accountEmail,
          gmail_message_id: item.gmailMessageId,
          action: item.action,
          expected_version: item.expectedVersion,
        })),
      })
      const failedResults = response.results.filter((result) => result.status !== 'committed')
      const failedByCandidate = Object.fromEntries(
        failedResults.map((result) => [result.candidate_id, result.message]),
      )
      setSpamRescueCommitErrors(failedByCandidate)
      commitIdempotencyKeyRef.current = null
      setStagedSpamRescueActions({})
      setStagedSpamRescueOrder([])
      await loadAll({ preserveCommitErrors: true, preserveScroll: true })
      const committedText =
        response.committed_count === 1
          ? 'Committed 1 Spam Rescue change.'
          : `Committed ${response.committed_count} Spam Rescue changes.`
      const failedText =
        response.failed_count === 0
          ? ''
          : response.failed_count === 1
            ? ' 1 candidate needs attention.'
            : ` ${response.failed_count} candidates need attention.`
      setNotice(`${committedText}${failedText}`)
    } catch (error) {
      setNotice(userFacingErrorMessage(error, 'Could not commit Spam Rescue changes.'))
    } finally {
      setCommitBusy(false)
      setBusy(false)
    }
  }

  useEffect(() => {
    function handleReviewQueueKeyboard(event: KeyboardEvent) {
      if (
        view !== 'queue' ||
        loading ||
        busy ||
        commitBusy ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        isEditableKeyboardTarget(event.target)
      ) {
        return
      }

      const action = REVIEW_QUEUE_KEYBOARD_ACTIONS[event.key]
      if (action && nextReviewMessage) {
        event.preventDefault()
        stageSingleAction(nextReviewMessage, action)
        return
      }

      if (event.key.toLowerCase() === 'u' && stagedList.length > 0) {
        event.preventDefault()
        handleUndoLastStagedAction()
        return
      }

      if (event.key.toLowerCase() === 'c' && stagedList.length > 0) {
        event.preventDefault()
        void handleCommitStagedActions()
      }
    }

    window.addEventListener('keydown', handleReviewQueueKeyboard)
    return () => window.removeEventListener('keydown', handleReviewQueueKeyboard)
  }, [busy, commitBusy, loading, nextReviewMessage, stagedList.length, view])

  useEffect(() => {
    function handleAutoResponseEscape(event: KeyboardEvent) {
      if (!autoResponseMessage || autoResponseBusy || event.key !== 'Escape') {
        return
      }
      event.preventDefault()
      closeAutoResponseModal()
    }

    window.addEventListener('keydown', handleAutoResponseEscape)
    return () => window.removeEventListener('keydown', handleAutoResponseEscape)
  }, [autoResponseBusy, autoResponseMessage])

  async function handleCreateManualRule() {
    if (!newRulePattern.trim()) {
      setNotice('Add a pattern before creating a rule.')
      return
    }

    setBusy(true)
    setNotice('Creating a manual rule...')
    try {
      const result = await createRule({
        scope: 'global',
        rule_type: newRuleType,
        pattern: newRulePattern.trim(),
        action: newRuleAction,
      })
      setNewRulePattern('')
      await loadAll()
      setNotice(`Manual rule created and ${result.reclassified_messages} queued messages were reclassified.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Manual rule creation failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCreateProcessedAutoCleanRule(message: ProcessedMessage, action: Category) {
    if (message.action_source !== 'high_confidence_auto_clean') {
      return
    }
    if (!message.sender_domain) {
      setNotice('This processed message does not have a sender domain for a rule.')
      return
    }

    setBusy(true)
    setNotice(`Creating an ${ACTION_LABELS[action]} rule for ${message.sender_domain}...`)
    try {
      const result = await createRule({
        scope: 'global',
        account_email: null,
        rule_type: 'domain',
        pattern: message.sender_domain,
        action,
        source_message_id: message.message_id ?? undefined,
        apply_to_source: false,
      })
      await loadAll({ preserveScroll: true })
      setNotice(
        `Rule created for ${message.sender_domain}; ${result.reclassified_messages} queued messages were reclassified.`,
      )
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Rule creation failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleConnectAccount() {
    setBusy(true)
    setNotice('Connecting the next mock Gmail account...')
    try {
      await connectMockAccount()
      await loadAll()
      setNotice('Another mock Gmail account is now available.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to connect another account.')
    } finally {
      setBusy(false)
    }
  }

  async function handleConnectGmailModifyAccount() {
    setBusy(true)
    setNotice('Opening Google OAuth for Gmail...')
    try {
      if (!import.meta.env.DEV) {
        await startHostedGmailConnect('modify')
        return
      }
      await connectGmailModifyAccount()
      await loadAll()
      setNotice('Gmail account connected. Fynish actions will update Gmail when the account has modify access.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to connect Gmail modify account.')
    } finally {
      setBusy(false)
    }
  }

  async function handleReconnectGmailAccount(account: Account) {
    setBusy(true)
    setNotice(`Opening Google OAuth for ${account.email_address}...`)
    try {
      await startHostedGmailConnect('modify', account.email_address)
      return
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to reconnect ${account.email_address}.`)
    } finally {
      setBusy(false)
    }
  }

  async function handleConnectDigestSender() {
    setBusy(true)
    setNotice('Opening Google OAuth for the digest sender...')
    try {
      await startDigestSenderConnect()
      return
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to connect digest sender.')
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveDigestSettings() {
    if (!notificationSettings) {
      return
    }
    setBusy(true)
    setNotice('Saving digest settings...')
    setSettingsErrors({})
    try {
      const response = await updateNotificationSettings({
        recipient_email: notificationSettings.recipient_email,
        timezone: notificationSettings.timezone,
        digest_enabled: notificationSettings.digest_enabled,
        digest_time: notificationSettings.digest_time,
        ai_digest_summary_enabled: notificationSettings.ai_digest_summary_enabled,
      })
      setNotificationSettings(response.settings)
      setNotice(
        response.settings.digest_enabled
          ? `Daily digest enabled for ${response.settings.digest_time}.`
          : 'Daily digest disabled.',
      )
    } catch (error) {
      const fieldErrors = settingsFieldErrorsFromError(error)
      setSettingsErrors(fieldErrors)
      setNotice(error instanceof Error ? error.message : 'Unable to save digest settings.')
    } finally {
      setBusy(false)
    }
  }

  function updateLocalDigestSettings(changes: Partial<NotificationSettings>) {
    setNotificationSettings((current) => (current ? { ...current, ...changes } : current))
    setSettingsErrors((current) => {
      const next = { ...current }
      if ('recipient_email' in changes) {
        delete next.recipient_email
      }
      if ('digest_time' in changes) {
        delete next.digest_time
      }
      if ('timezone' in changes) {
        delete next.timezone
      }
      return next
    })
  }

  function handleScrollToTop() {
    window.scrollTo({ top: 0, behavior: 'auto' })
  }

  async function refreshAttentionNotes() {
    const response = await fetchAiDigestAttentionNotes()
    setAiDigestAttentionNotes(response.notes)
    setAttentionNoteDrafts(attentionNoteDraftsFromNotes(response.notes))
  }

  async function refreshWritingStyleCards() {
    if (!featureFlags.writing_style_cards) {
      setWritingStyleCards([])
      setWritingStyleDrafts({})
      return
    }
    const response = await fetchWritingStyleCards()
    setWritingStyleCards(response.cards)
    setWritingStyleDrafts(
      Object.fromEntries(
        response.cards.map((card) => [card.id, card.style_card_markdown]),
      ),
    )
  }

  function updateWritingStyleDraft(cardId: number, value: string) {
    setWritingStyleDrafts((current) => ({ ...current, [cardId]: value }))
  }

  async function handleCreateWritingStyleCard() {
    setBusy(true)
    setNotice('Sampling Gmail Sent mail to build a draft writing style card...')
    try {
      await createWritingStyleCard()
      await refreshWritingStyleCards()
      setNotice('Sampled Sent mail and built a draft writing style card. Review, edit, and approve it when it feels right.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to sample Sent mail for a writing style card.')
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveWritingStyleCard(card: WritingStyleCard) {
    const draft = writingStyleDrafts[card.id] ?? card.style_card_markdown
    setBusy(true)
    setNotice(`Saving writing style card for ${card.account_email}...`)
    try {
      await updateWritingStyleCard(card.id, { style_card_markdown: draft })
      await refreshWritingStyleCards()
      setNotice(`Writing style card saved for ${card.account_email}.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to save style card for ${card.account_email}.`)
    } finally {
      setBusy(false)
    }
  }

  async function handleApproveWritingStyleCard(card: WritingStyleCard) {
    const draft = writingStyleDrafts[card.id] ?? card.style_card_markdown
    setBusy(true)
    setNotice(`Approving writing style card for ${card.account_email}...`)
    try {
      if (draft !== card.style_card_markdown) {
        await updateWritingStyleCard(card.id, { style_card_markdown: draft })
      }
      await approveWritingStyleCard(card.id)
      await refreshWritingStyleCards()
      setNotice(`Writing style card approved for ${card.account_email}. Auto-Respond will use it.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to approve style card for ${card.account_email}.`)
    } finally {
      setBusy(false)
    }
  }

  async function handleDisableWritingStyleCard(card: WritingStyleCard) {
    setBusy(true)
    setNotice(`Disabling writing style card for ${card.account_email}...`)
    try {
      await disableWritingStyleCard(card.id)
      await refreshWritingStyleCards()
      setNotice(`Writing style card disabled for ${card.account_email}.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to disable style card for ${card.account_email}.`)
    } finally {
      setBusy(false)
    }
  }

  function updateAttentionNoteDraft(noteId: number, changes: Partial<AttentionNoteDraft>) {
    setAttentionNoteDrafts((current) => ({
      ...current,
      [noteId]: {
        ...(current[noteId] ?? { domain: '', label: '', note: '' }),
        ...changes,
      },
    }))
  }

  async function handleCreateAiDigestAttentionNote() {
    setBusy(true)
    setNotice('Adding AI digest attention note...')
    try {
      await createAiDigestAttentionNote({
        domain: newAttentionDomain,
        label: newAttentionLabel,
        note: newAttentionNote,
        enabled: true,
      })
      setNewAttentionDomain('')
      setNewAttentionLabel('')
      setNewAttentionNote('')
      await refreshAttentionNotes()
      setNotice('AI digest attention note added.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to add attention note.')
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveAiDigestAttentionNote(note: AiDigestAttentionNote) {
    const draft = attentionNoteDrafts[note.id]
    if (!draft) {
      return
    }
    setBusy(true)
    setNotice(`Saving AI digest note for ${note.domain}...`)
    try {
      await updateAiDigestAttentionNote(note.id, draft)
      await refreshAttentionNotes()
      setNotice(`AI digest note saved for ${draft.domain || note.domain}.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to save note for ${note.domain}.`)
    } finally {
      setBusy(false)
    }
  }

  async function handleToggleAiDigestAttentionNote(note: AiDigestAttentionNote) {
    setBusy(true)
    setNotice(`${note.enabled ? 'Disabling' : 'Enabling'} AI digest note for ${note.domain}...`)
    try {
      await updateAiDigestAttentionNote(note.id, { enabled: !note.enabled })
      await refreshAttentionNotes()
      setNotice(`AI digest note ${note.enabled ? 'disabled' : 'enabled'} for ${note.domain}.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to update note for ${note.domain}.`)
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteAiDigestAttentionNote(note: AiDigestAttentionNote) {
    setBusy(true)
    setNotice(`Deleting AI digest note for ${note.domain}...`)
    try {
      await deleteAiDigestAttentionNote(note.id)
      await refreshAttentionNotes()
      setNotice(`AI digest note deleted for ${note.domain}.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Unable to delete note for ${note.domain}.`)
    } finally {
      setBusy(false)
    }
  }

  async function handleToggleRule(rule: Rule) {
    setBusy(true)
    setNotice(`${rule.enabled ? 'Disabling' : 'Enabling'} rule for ${rule.pattern}...`)
    try {
      await updateRule(rule.id, { enabled: !rule.enabled })
      await loadAll()
      setNotice(`Rule updated for ${rule.pattern}.`)
    } catch (error) {
      if (isApiNotFound(error)) {
        await loadAll()
        setNotice('Rule no longer exists. Refreshed the list.')
        return
      }
      setNotice(error instanceof Error ? error.message : 'Unable to update rule.')
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteRule(rule: Rule) {
    setBusy(true)
    setNotice(`Deleting rule for ${rule.pattern}...`)
    try {
      await deleteRule(rule.id)
      await loadAll()
      setNotice(`Rule deleted for ${rule.pattern}.`)
    } catch (error) {
      if (isApiNotFound(error)) {
        await loadAll()
        setNotice('Rule no longer exists. Refreshed the list.')
        return
      }
      setNotice(error instanceof Error ? error.message : 'Unable to delete rule.')
    } finally {
      setBusy(false)
    }
  }

  async function handleDisableAccount(id: number) {
    setBusy(true)
    setNotice('Disabling the selected account...')
    try {
      await disableAccount(id)
      await loadAll()
      setNotice('Account disabled.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to disable account.')
    } finally {
      setBusy(false)
    }
  }

  async function handleEnableAccount(id: number) {
    setBusy(true)
    setNotice('Enabling the selected account...')
    try {
      await enableAccount(id)
      await loadAll()
      setNotice('Account enabled. Refresh Mail Account will sync it again.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to enable account.')
    } finally {
      setBusy(false)
    }
  }

  async function handleLogout() {
    setBusy(true)
    setNotice('Signing out...')
    try {
      await logoutCurrentUser()
      setAuthStatus({ auth_enabled: authStatus.auth_enabled, user: null })
      window.location.assign('/auth/login')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to sign out right now.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRecoverProcessedMessage(message: ProcessedMessage) {
    if (message.message_id === null) {
      setNotice('This processed message cannot be recovered because the original message is unavailable.')
      return
    }

    setBusy(true)
    setNotice('Recovering the message back into the review queue...')
    try {
      await recoverProcessedMessage(message.message_id)
      await loadAll()
      setNotice('Message recovered to Inbox and returned to review queue.')
    } catch (error) {
      if (isApiNotFound(error)) {
        await loadAll()
        setNotice('Message is no longer available. Refreshed the processed mail list.')
        return
      }
      setNotice(userFacingErrorMessage(error, 'Unable to recover the message.'))
    } finally {
      setBusy(false)
    }
  }

  function openAutoResponseModal(message: ReviewMessage) {
    setAutoResponseMessage(message)
    setAutoResponseGuidance('')
    setAutoResponseDraft(null)
    setAutoResponseDraftBody('')
    setAutoResponseSendResult(null)
    setAutoResponseError(null)
  }

  function closeAutoResponseModal() {
    if (autoResponseBusy) {
      return
    }
    setAutoResponseMessage(null)
    setAutoResponseGuidance('')
    setAutoResponseDraft(null)
    setAutoResponseDraftBody('')
    setAutoResponseSendResult(null)
    setAutoResponseError(null)
  }

  async function handleGenerateAutoResponseDraft() {
    if (!autoResponseMessage) {
      return
    }

    setAutoResponseBusy(true)
    setAutoResponseError(null)
    try {
      const result = await generateAutoResponseDraft(autoResponseMessage.id, {
        user_guidance: autoResponseGuidance.trim() || null,
      })
      setAutoResponseDraft(result.draft)
      if (featureFlags.auto_response_send) {
        const previewResult = await previewAutoResponseSend(autoResponseMessage.id, {
          draft_body: result.draft.draft_body,
        })
        setAutoResponseDraftBody(previewResult.preview.body_text)
      } else {
        setAutoResponseDraftBody(result.draft.draft_body)
      }
      setAutoResponseSendResult(null)
      setNotice(`Draft response generated for "${autoResponseMessage.subject}". Review it before sending.`)
    } catch (error) {
      setAutoResponseError(userFacingErrorMessage(error, 'Unable to generate a draft response.'))
    } finally {
      setAutoResponseBusy(false)
    }
  }

  async function handleCopyAutoResponseDraft() {
    if (!autoResponseDraftBody.trim()) {
      return
    }

    try {
      await navigator.clipboard.writeText(autoResponseDraftBody)
      setNotice('Draft response copied. Paste it into Gmail when you are ready.')
    } catch {
      setNotice('Could not copy automatically. Select the draft text and copy it manually.')
    }
  }

  async function handleSendAutoResponse() {
    if (!autoResponseMessage || !autoResponseDraft || !autoResponseDraftBody.trim()) {
      return
    }

    const confirmed = window.confirm(
      `Send this reply from ${autoResponseMessage.account_email} to ${autoResponseMessage.reply_to || autoResponseMessage.sender}?`,
    )
    if (!confirmed) {
      return
    }

    setAutoResponseBusy(true)
    setAutoResponseError(null)
    try {
      const result = await sendAutoResponse(autoResponseMessage.id, {
        idempotency_key: createIdempotencyKey('auto-response-send'),
        draft_body: autoResponseDraftBody,
        confirmed: true,
        include_context: false,
      })
      setAutoResponseSendResult(result.send)
      setNotice(`Reply sent to ${result.send.to_email}.`)
    } catch (error) {
      setAutoResponseError(userFacingErrorMessage(error, 'Unable to send the reply.'))
    } finally {
      setAutoResponseBusy(false)
    }
  }

  function setAction(messageId: number, action: Category) {
    setActionMap((current) => ({ ...current, [messageId]: action }))
  }

  function handleRowActionClick(message: ReviewMessage, action: Category) {
    stageSingleAction(message, action)
  }

  const renderSpamRescue = () => (
    <section className="panel spam-rescue-panel">
      <div className="queue-controls">
        <div>
          <h2>Spam Rescue</h2>
          <p className="subtle">
            Review likely false positives from Spam, then choose whether to restore them or leave them alone.
          </p>
        </div>
        <div className="spam-rescue-summary" aria-label="Spam Rescue snapshot">
          <div className="summary-stat">
            <strong>{activeVisibleSpamRescueQueue.length}</strong>
            <span>Accounts</span>
          </div>
          <div className="summary-stat">
            <strong>{visibleSpamRescueCount}</strong>
            <span>Candidates</span>
          </div>
        </div>
      </div>

      {stagedSpamRescueList.length > 0 ? (
        <div className="staged-queue-panel spam-rescue-staged-panel">
          <div className="staged-queue-toolbar">
            <div>
              <strong>
                {stagedSpamRescueList.length === 1
                  ? '1 Spam Rescue change staged'
                  : `${stagedSpamRescueList.length} Spam Rescue changes staged`}
              </strong>
              <p className="subtle">Spam Rescue will update when you commit.</p>
            </div>
            <div className="staged-queue-actions">
              <button
                type="button"
                className="staged-queue-secondary-button"
                onClick={handleUndoLastStagedSpamRescueAction}
                disabled={commitBusy}
              >
                Undo Last
              </button>
              <button
                type="button"
                className="staged-queue-secondary-button"
                onClick={handleDiscardStagedSpamRescueActions}
                disabled={commitBusy}
              >
                Discard
              </button>
              <button
                type="button"
                className="button primary"
                onClick={() => void handleCommitStagedSpamRescueActions()}
                disabled={commitBusy}
              >
                {commitBusy ? 'Committing...' : 'Commit Changes'}
              </button>
            </div>
          </div>
          <div className="staged-queue-list">
            {stagedSpamRescueByAccount.map((group) => (
              <section key={group.accountEmail} className="staged-account-group">
                <div className="staged-account-header">
                  <strong>{group.accountEmail}</strong>
                  <span className="count-pill">{group.items.length}</span>
                </div>
                <div className="staged-account-items">
                  {group.items.map((item) => (
                    <div key={item.candidateId} className="staged-queue-item">
                      <span className="classification-pill classification-pill-review">
                        {item.actionLabel}
                      </span>
                      <div>
                        <strong>{item.subject}</strong>
                        <p className="message-meta">
                          {item.sender} | {item.senderDomain}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="empty-state">Loading Spam Rescue candidates...</div>
      ) : visibleSpamRescueCount === 0 && stagedSpamRescueList.length === 0 ? (
        <div className="empty-state">No likely Spam false positives found.</div>
      ) : (
        activeVisibleSpamRescueQueue.map((account) => (
          <section key={account.account_email} className="account-card spam-rescue-account">
            <div className="account-header">
              <div className="account-title">
                <h2>{account.account_email}</h2>
                <span className="pill">Spam</span>
              </div>
              <div className="message-meta">Candidates: {account.messages.length}</div>
            </div>

            <div className="message-list">
              {account.messages.map((message) => (
                <article key={message.id} className="message-row spam-rescue-row">
                  <div className="row-main">
                    <div>
                      <div className="row-topline">
                        <div className="sender-line">
                          <span className="classification-pill classification-pill-review">
                            <span>Rescue</span>
                            <span>{formatConfidencePercent(message.confidence)}</span>
                          </span>
                          <strong>{message.sender}</strong>
                          <span className="message-meta">{message.sender_domain}</span>
                        </div>
                        <span className="spam-source-pill">Spam</span>
                        {message.protection_reasons.length > 0 ? (
                          <span className="safety-pill">Protected</span>
                        ) : null}
                      </div>

                      <div className="subject-line">
                        <strong>{message.subject}</strong>
                        <span className="message-meta">{formatRelativeDate(message.received_at)}</span>
                        {message.has_attachments ? <span className="message-meta">Attachment</span> : null}
                      </div>
                      {spamRescueCommitErrors[message.id] ? (
                        <p className="queue-commit-error">{spamRescueCommitErrors[message.id]}</p>
                      ) : null}

                      <div className="message-preview spam-rescue-preview">
                        <strong className="message-detail-label">Preview</strong>
                        <p>{buildSpamRescuePreviewText(message)}</p>
                      </div>

                      <div className="spam-rescue-detail-grid">
                        <div>
                          <strong className="message-detail-label">Rescue reasons</strong>
                          <ul className="reason-list queue-reason-list">
                            {message.rescue_reasons.map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                        </div>

                        {message.protection_reasons.length > 0 ? (
                          <div>
                            <strong className="message-detail-label">Protected signals</strong>
                            <ul className="protection-list">
                              {message.protection_reasons.map((reason) => (
                                <li key={reason}>{reason}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                      </div>

                      <div className="spam-rescue-actions">
                        <button
                          type="button"
                          className="button primary"
                          onClick={() => stageSpamRescueAction(message, 'restore_to_inbox')}
                          disabled={busy || commitBusy}
                        >
                          Restore to Inbox
                        </button>
                        <button
                          type="button"
                          className="button secondary"
                          onClick={() => stageSpamRescueAction(message, 'leave_in_spam')}
                          disabled={busy || commitBusy}
                        >
                          Leave in Spam
                        </button>
                      </div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))
      )}
    </section>
  )

  const renderQueue = () => (
    <section className="panel">
      <div className="queue-controls">
        <div>
          <h2>Review Queue</h2>
          <p className="subtle">
            Review unread Inbox mail, apply rules, and keep Gmail actions reversible with Fynish labels.
          </p>
        </div>
      </div>

      {stagedList.length > 0 ? (
        <div className="staged-queue-panel">
          <div className="staged-queue-toolbar">
            <div>
              <strong>
                {stagedList.length === 1 ? '1 change staged' : `${stagedList.length} changes staged`}
              </strong>
              <p className="subtle">Gmail and Fynish will update when you commit.</p>
            </div>
            <div className="staged-queue-actions">
              <button
                type="button"
                className="staged-queue-secondary-button"
                aria-keyshortcuts="U"
                title="Undo last staged change"
                onClick={handleUndoLastStagedAction}
                disabled={commitBusy}
              >
                Undo Last
              </button>
              <button
                type="button"
                className="staged-queue-secondary-button"
                onClick={handleDiscardStagedActions}
                disabled={commitBusy}
              >
                Discard
              </button>
              <button
                type="button"
                className="button primary"
                aria-keyshortcuts="C"
                title="Commit staged changes"
                onClick={() => void handleCommitStagedActions()}
                disabled={commitBusy}
              >
                {commitBusy ? 'Committing...' : 'Commit Changes'}
              </button>
            </div>
          </div>
          <div className="staged-queue-list">
            {stagedByAccount.map((group) => (
              <section key={group.accountEmail} className="staged-account-group">
                <div className="staged-account-header">
                  <strong>{group.accountEmail}</strong>
                  <span className="count-pill">{group.items.length}</span>
                </div>
                <div className="staged-account-items">
                  {group.items.map((item) => (
                    <div key={item.messageId} className="staged-queue-item">
                      <span className={`classification-pill classification-pill-${queueCategoryClassName(item.action)}`}>
                        {item.actionLabel}
                      </span>
                      <div>
                        <strong>{item.subject}</strong>
                        <p className="message-meta">
                          {item.sender} | {item.senderDomain}
                        </p>
                        {item.rule ? (
                          <p className="message-meta">
                            Rule staged: {item.rule.pattern} {'->'} {ACTION_LABELS[item.rule.action]}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="empty-state">Loading the current review queue...</div>
      ) : queueStats.totalMessages === 0 && stagedList.length === 0 ? (
        <>
          <div className="empty-state">
            No unread Inbox messages are in the queue right now.
          </div>
          <div className="accounts-grid">
            {monitoredQueueAccounts.map(({ account, queueAccount }) => (
              <article key={account.id} className="account-tile">
                <div className="account-tile-header">
                  <div>
                    <strong>{account.email_address}</strong>
                    <p className="subtle">{formatProvider(account.provider)}</p>
                  </div>
                  <div className="account-status-stack">
                    <span className={account.enabled ? 'pill' : 'count-pill'}>
                      {account.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    {accountAuthStatusLabel(account) ? (
                      <span className={accountAuthStatusClass(account)}>
                        {accountAuthStatusLabel(account)}
                      </span>
                    ) : null}
                  </div>
                </div>
                <p className="message-meta">
                  Access: {accountAccessLabel(account)} | Last sync:{' '}
                  {formatRelativeDate(queueAccount?.last_sync_at ?? account.last_sync_at)}
                </p>
                {account.auth_status === 'reconnect_required' && account.auth_status_reason ? (
                  <p className="account-auth-reason">{account.auth_status_reason}</p>
                ) : null}
              </article>
            ))}
          </div>
        </>
      ) : (
        activeVisibleQueue.map((account) => (
          <section key={account.account_email} className="account-card">
            {(() => {
              const emptyGroups = account.groups.filter((group) => group.messages.length === 0)
              const populatedGroups = account.groups.filter((group) => group.messages.length > 0)

              return (
                <>
            <div className="account-header">
              <div className="account-title">
                <h2>{account.account_email}</h2>
                <span className="pill">
                  {accountAccessLabel(accountMap[account.account_email] ?? {
                    id: 0,
                    email_address: account.account_email,
                    enabled: true,
                    provider: 'mock_gmail',
                    last_sync_at: account.last_sync_at,
                    oauth_scopes: [],
                    auth_status: 'not_applicable',
                    auth_status_label: 'Not applicable',
                    auth_status_reason: null,
                  })}
                </span>
              </div>
              <div className="message-meta">Last sync: {formatRelativeDate(account.last_sync_at)}</div>
            </div>

            {emptyGroups.length > 0 ? (
              <div className="empty-groups-row">
                {emptyGroups.map((group) => (
                  <div key={`${account.account_email}-${group.category}`} className="empty-group-chip">
                    <strong>{group.display_name}</strong>
                    <span className="count-pill">{group.count}</span>
                  </div>
                ))}
              </div>
            ) : null}

            {populatedGroups.map((group) => (
              <section key={`${account.account_email}-${group.category}`} className="group-section">
                <div className="group-header">
                  <div className="group-title">
                    <h3>{group.display_name}</h3>
                    <span className="count-pill">{group.count}</span>
                  </div>
                </div>

                <div className="message-list">
                  {group.messages.map((message) => {
                    const classificationCategory = message.recommended_action
                    const classificationClass = queueCategoryClassName(classificationCategory)

                    return (
                    <article
                      key={message.id}
                      className={`message-row message-row-${classificationClass}`}
                    >
                      <div className="row-main">
                        <div>
                          <div className="row-topline">
                            <div className="sender-line">
                              <span className={`classification-pill classification-pill-${classificationClass}`}>
                                <span>{QUEUE_CLASSIFICATION_LABELS[classificationCategory]}</span>
                                <span>{formatConfidencePercent(message.confidence)}</span>
                              </span>
                              <strong>{message.sender}</strong>
                              <span className="message-meta">{message.sender_domain}</span>
                            </div>
                            {message.protected ? <span className="safety-pill">Protected</span> : null}
                            {message.queue_source_label ? (
                              <span
                                className="queue-source-pill"
                                title={message.queue_source_detail ?? 'Left in Gmail Inbox and kept here for review.'}
                              >
                                {message.queue_source_label}
                              </span>
                            ) : null}
                          </div>

                          <div className="subject-line">
                            <strong>{message.subject}</strong>
                            <span className="message-meta">{formatRelativeDate(message.received_at)}</span>
                            {message.has_attachments ? <span className="message-meta">Attachment</span> : null}
                          </div>
                          {commitErrors[message.id] ? (
                            <p className="queue-commit-error">{commitErrors[message.id]}</p>
                          ) : null}

                          <div className="message-preview">
                            <button
                              type="button"
                              className={`queue-preview-toggle ${expandedQueuePreviewId === message.id ? 'expanded' : ''}`}
                              aria-expanded={expandedQueuePreviewId === message.id}
                              onClick={() =>
                                setExpandedQueuePreviewId((current) =>
                                  current === message.id ? null : message.id,
                                )
                              }
                            >
                              <strong>Preview</strong>
                              <p>{buildPreviewText(message)}</p>
                            </button>
                            {expandedQueuePreviewId === message.id ? (
                              <div className="queue-preview-expanded">
                                <div className="queue-preview-scroll">
                                  {cleanPreviewText(
                                    message.body_preview?.trim() ||
                                      message.snippet?.trim() ||
                                      'No additional text available.',
                                  )}
                                </div>
                              </div>
                            ) : null}
                          </div>

                          <div className="queue-card-layout">
                            <div className="queue-card-recommendation">
                              <p className="queue-recommendation-line">
                                <strong className="message-detail-label">Suggested classification:</strong>{' '}
                                <span className="queue-recommendation-value">
                                  {ACTION_LABELS[message.recommended_action]}
                                </span>
                              </p>
                              <ul className="reason-list queue-reason-list">
                                {message.reasons.map((reason) => (
                                  <li key={reason}>{reason}</li>
                                ))}
                              </ul>
                              {message.protection_reasons.length > 0 ? (
                                <ul className="protection-list">
                                  {message.protection_reasons.map((reason) => (
                                    <li key={reason}>{reason}</li>
                                  ))}
                                </ul>
                              ) : null}
                            </div>

                            <div className="queue-bootstrap-controls">
                              <div className="queue-action-group">
                                <strong className="message-detail-label">This Message</strong>
                                <p className="queue-helper">
                                  One-click actions that affect only this message.
                                </p>
                                <div className="row-actions">
                                  {(['keep', 'bulk_mail', 'junk_review', 'trash'] as Category[]).map((action) => (
                                    <button
                                      key={action}
                                      type="button"
                                      aria-label={`${ACTION_LABELS[action]} now for ${message.subject}`}
                                      aria-keyshortcuts={
                                        nextReviewMessage?.id === message.id
                                          ? action === 'keep'
                                            ? '1'
                                            : action === 'bulk_mail'
                                              ? '2'
                                              : action === 'junk_review'
                                                ? '3'
                                                : '4'
                                          : undefined
                                      }
                                      className={`action-button action-button-${queueCategoryClassName(action)} ${actionMap[message.id] === action ? 'active' : ''}`}
                                      // eslint-disable-next-line react-hooks/refs
                                      onClick={() => handleRowActionClick(message, action)}
                                      disabled={busy || commitBusy}
                                    >
                                      {ACTION_LABELS[action]}
                                    </button>
                                  ))}
                                  {featureFlags.auto_response_drafts ? (
                                    <button
                                      type="button"
                                      className="queue-rule-button auto-response-button"
                                      onClick={() => openAutoResponseModal(message)}
                                      disabled={busy || commitBusy}
                                    >
                                      Auto-Respond
                                    </button>
                                  ) : null}
                                </div>
                              </div>

                              <div className="queue-action-group queue-rule-group">
                                <strong className="message-detail-label">Teach Fynish</strong>
                                <p className="queue-helper">
                                  Create a reusable rule and apply it to this message now.
                                </p>
                                <p className="queue-helper queue-helper-detail">
                                  Domain rules are exact matches, so a rule for <code>nextdoor.com</code> does not also
                                  match <code>rs.email.nextdoor.com</code>.
                                </p>
                                <div className="row-actions">
                                  <button
                                    type="button"
                                    className="queue-rule-button"
                                    // eslint-disable-next-line react-hooks/refs
                                    onClick={() => stageRuleAction(message, 'keep')}
                                    disabled={busy || commitBusy}
                                  >
                                    Always Keep Domain
                                  </button>
                                  <button
                                    type="button"
                                    className="queue-rule-button"
                                    onClick={() => stageRuleAction(message, 'junk_review')}
                                    disabled={busy || commitBusy}
                                  >
                                    Always Junk Domain
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </article>
                    )
                  })}
                </div>
              </section>
            ))}
                </>
              )
            })()}
          </section>
        ))
      )}
    </section>
  )

  const renderProcessed = () => (
    <section className="panel">
      <div className="section-header">
        <div>
          <h2>Processed Mail</h2>
          <p className="subtle">
            Recent messages processed by Fynish across visible accounts, with the newest activity first.
          </p>
          <p className="message-meta">
            Mail processing most recently ran:{' '}
            {latestVisibleAccountSyncAt ? formatRelativeDate(latestVisibleAccountSyncAt) : 'Not synced yet'}
          </p>
        </div>
        <div className="toolbar" style={{ marginTop: 0 }}>
          <button className="button secondary" type="button" onClick={() => void loadAll()} disabled={busy}>
            Refresh Processed List
          </button>
          <span className="message-meta">{visibleProcessedMessages.length} shown</span>
        </div>
      </div>

      {loading ? (
        <div className="empty-state">Loading processed messages...</div>
      ) : visibleProcessedMessages.length === 0 ? (
        <div className="empty-state">
          No processed messages yet.
          {canUseDevelopmentHarness && !showMockAccounts
            ? ' Turn on mock accounts if you want to view processed seeded demo activity too.'
            : ''}
        </div>
      ) : (
        <div className="processed-list" role="list" aria-label="Processed mail list">
          {visibleProcessedMessages.map((message) => {
            const processedClass = queueCategoryClassName(message.selected_action)

            return (
            <div key={message.id} className="processed-item" role="listitem">
              <button
                type="button"
                className={`processed-row processed-row-${processedClass} ${expandedProcessedId === message.id ? 'expanded' : ''}`}
                aria-expanded={expandedProcessedId === message.id}
                onClick={() =>
                  setExpandedProcessedId((current) => (current === message.id ? null : message.id))
                }
              >
                <span className={`processed-action processed-action-${message.selected_action}`}>
                  {PROCESSED_ACTION_LABELS[message.selected_action] ?? formatActionSource(message.selected_action)}
                </span>
                <span className="processed-source" title={`Source: ${formatActionSource(message.action_source)}`}>
                  {formatActionSource(message.action_source)}
                </span>
                <span className="processed-account" title={message.account_email}>
                  {message.account_email}
                </span>
                <span className="processed-sender" title={message.sender}>
                  {message.sender}
                </span>
                <span className="processed-subject" title={message.subject}>
                  {message.subject}
                </span>
                <span className="processed-time" title={message.processed_at}>
                  {formatCompactDateTime(message.processed_at)}
                </span>
              </button>
              {expandedProcessedId === message.id ? (
                <div className={`processed-expanded processed-expanded-${processedClass}`}>
                  <strong>Preview</strong>
                  <p className="message-meta">Source: {formatActionSource(message.action_source)}</p>
                  <p className="message-meta">From: {message.sender_email || message.sender}</p>
                  <div className="processed-preview-scroll">
                    {message.preview || 'No preview available.'}
                  </div>
                  {message.created_rule_id ? (
                    <p className="message-meta">Rule created from this action: #{message.created_rule_id}</p>
                  ) : null}
                  {message.action_source === 'high_confidence_auto_clean' ? (
                    <div className="card-actions processed-teach-actions" style={{ marginTop: '12px' }}>
                      <button
                        className="button secondary"
                        type="button"
                        onClick={() => void handleCreateProcessedAutoCleanRule(message, 'junk_review')}
                        disabled={busy || !message.sender_domain}
                      >
                        Always Junk Rule
                      </button>
                      <button
                        className="button secondary"
                        type="button"
                        onClick={() => void handleCreateProcessedAutoCleanRule(message, 'keep')}
                        disabled={busy || !message.sender_domain}
                      >
                        Always Keep Rule
                      </button>
                    </div>
                  ) : null}
                  {message.message_id !== null ? (
                    <div className="card-actions" style={{ marginTop: '12px' }}>
                      <button
                        className="button secondary"
                        type="button"
                        onClick={() => void handleRecoverProcessedMessage(message)}
                        disabled={busy}
                      >
                        Recover
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
            )
          })}
        </div>
      )}
    </section>
  )

  const renderRules = () => (
    <section className="panel">
      <div className="section-header">
        <div>
          <h2>Rules</h2>
          <p className="subtle">Global, explainable rules that the local classifier checks before score-based routing.</p>
        </div>
      </div>

      <div className="inline-form">
        <select className="settings-select" value={newRuleType} onChange={(event) => setNewRuleType(event.target.value)}>
          <option value="sender">Sender</option>
          <option value="domain">Domain</option>
          <option value="subject_contains">Subject contains</option>
          <option value="list_id">List-ID</option>
        </select>
        <input
          className="text-input"
          value={newRulePattern}
          onChange={(event) => setNewRulePattern(event.target.value)}
          placeholder={newRuleType === 'domain' ? 'e.g. newsletters.apple.com' : 'Pattern'}
        />
        <select
          className="settings-select"
          value={newRuleAction}
          onChange={(event) => setNewRuleAction(event.target.value as Category)}
        >
          {Object.entries(ACTION_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button className="button primary" type="button" onClick={() => void handleCreateManualRule()} disabled={busy}>
          Add Rule
        </button>
      </div>

      {newRuleType === 'domain' ? (
        <p className="rule-helper-text">
          Domain rules match the sender domain exactly. For example, <code>example.com</code> matches{' '}
          <code>foo@example.com</code>, but not <code>foo@mail.example.com</code>.
        </p>
      ) : null}

      <div className="rules-grid">
        {rules.length === 0 ? (
          <div className="empty-state">No rules yet. Create one from the queue or add a manual rule here.</div>
        ) : (
          rules.map((rule) => (
            <article key={rule.id} className="rule-card">
              <div className="rule-card-header">
                <div>
                  <strong>{rule.pattern}</strong>
                  <p className="subtle">
                    {rule.rule_type} {'->'} {ACTION_LABELS[rule.action]}
                  </p>
                </div>
                <span className={rule.enabled ? 'pill' : 'count-pill'}>{rule.enabled ? 'Enabled' : 'Disabled'}</span>
              </div>
              <p className="message-meta">
                Scope: {rule.scope} | Matches: {rule.match_count} | Last matched: {formatRelativeDate(rule.last_matched_at)}
              </p>
              <div className="card-actions">
                <button className="toggle-button" type="button" onClick={() => void handleToggleRule(rule)} disabled={busy}>
                  {rule.enabled ? 'Disable' : 'Enable'}
                </button>
                <button className="account-button" type="button" onClick={() => void handleDeleteRule(rule)} disabled={busy}>
                  Delete
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  )

  const renderAccounts = () => (
    <section className="panel">
      <div className="section-header">
        <div>
          <h2>Accounts</h2>
          <p className="subtle">
            Connect Gmail, refresh unread Inbox mail, and process messages one at a time.
          </p>
        </div>
        <div className="toolbar">
          <button className="button primary" type="button" onClick={() => void handleConnectGmailModifyAccount()} disabled={busy}>
            Add Gmail Account
          </button>
          {canUseDevelopmentHarness ? (
            <button className="button secondary" type="button" onClick={() => void handleConnectAccount()} disabled={busy}>
              Connect Mock Account
            </button>
          ) : null}
          {canUseDevelopmentHarness ? (
            <label className="view-toggle">
              <input
                type="checkbox"
                checked={showMockAccounts}
                onChange={() => setShowMockAccounts((current) => !current)}
              />
              <span>Show mock accounts</span>
            </label>
          ) : null}
        </div>
      </div>

      <div className="accounts-grid">
        {visibleAccounts.map((account) => (
          <article key={account.id} className="account-tile">
            <div className="account-tile-header">
              <div>
                <strong>{account.email_address}</strong>
                <p className="subtle">{formatProvider(account.provider)}</p>
              </div>
              <div className="account-status-stack">
                <span className={account.enabled ? 'pill' : 'count-pill'}>{account.enabled ? 'Enabled' : 'Disabled'}</span>
                {accountAuthStatusLabel(account) ? (
                  <span className={accountAuthStatusClass(account)}>{accountAuthStatusLabel(account)}</span>
                ) : null}
              </div>
            </div>
            <p className="message-meta">
                Access: {accountAccessLabel(account)} | Last sync: {formatRelativeDate(account.last_sync_at)}
            </p>
            {account.auth_status === 'reconnect_required' && account.auth_status_reason ? (
              <p className="account-auth-reason">{account.auth_status_reason}</p>
            ) : null}
            <div className="card-actions">
              {account.provider === 'gmail_readonly' ? (
                <button
                  className="account-button"
                  type="button"
                  onClick={() => void handleReconnectGmailAccount(account)}
                  disabled={busy}
                >
                  Reconnect Gmail
                </button>
              ) : null}
              {account.enabled ? (
                <button
                  className="account-button"
                  type="button"
                  onClick={() => void handleDisableAccount(account.id)}
                  disabled={busy}
                >
                  Disable Account
                </button>
              ) : (
                <button
                  className="account-button"
                  type="button"
                  onClick={() => void handleEnableAccount(account.id)}
                  disabled={busy}
                >
                  Enable Account
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  )

  const renderSettings = () => (
    <section className="panel">
      <div className="section-header">
        <div>
          <h2>Settings</h2>
          <p className="subtle">
            Current product behavior is intentionally compact while scheduled delivery features stay out of the active flow.
          </p>
        </div>
      </div>

      <div className="settings-grid">
        {SETTINGS_ITEMS.map((setting) => (
          <article key={setting.title} className="setting-card">
            <strong>{setting.title}</strong>
            <p className="subtle">{setting.description}</p>
            <p>{setting.value}</p>
          </article>
        ))}
        {digestSenderStatus?.can_manage ? (
          <article className="setting-card">
            <strong>Digest Sender</strong>
            <p className="subtle">
              {(digestSenderStatus.configured_email || 'The digest sender')} sends digest email only; it is not a monitored inbox.
            </p>
            {digestSenderStatus.sender?.auth_status === 'reconnect_required' ? (
              <p className="account-auth-reason">{digestSenderStatus.sender.auth_status_reason}</p>
            ) : digestSenderStatus.sender ? (
              <p className="message-meta">Connected as {digestSenderStatus.sender.email_address}</p>
            ) : (
              <p className="account-auth-reason">Digest sender is not connected.</p>
            )}
            <div className="card-actions">
              <button className="button secondary" type="button" onClick={() => void handleConnectDigestSender()} disabled={busy}>
                {digestSenderStatus.sender ? 'Reconnect Digest Sender' : 'Connect Digest Sender'}
              </button>
            </div>
          </article>
        ) : null}
        <article className="setting-card">
          <strong>Daily Digest</strong>
          <p className="subtle">One processed-mail digest per user per day, sent in the account timezone.</p>
          {notificationSettings ? (
            <>
              <div className="settings-form-grid">
                <label className="settings-field checkbox-field">
                  <span>Enable daily digest</span>
                  <input
                    type="checkbox"
                    checked={notificationSettings.digest_enabled}
                    onChange={(event) => updateLocalDigestSettings({ digest_enabled: event.target.checked })}
                  />
                </label>
                <label className="settings-field checkbox-field">
                  <span>AI digest summary</span>
                  <input
                    type="checkbox"
                    checked={notificationSettings.ai_digest_summary_enabled}
                    onChange={(event) => updateLocalDigestSettings({ ai_digest_summary_enabled: event.target.checked })}
                  />
                </label>
                <label className="settings-field">
                  <span>Send time</span>
                  <input
                    className="text-input"
                    type="time"
                    value={notificationSettings.digest_time}
                    onChange={(event) => updateLocalDigestSettings({ digest_time: event.target.value })}
                  />
                  {settingsErrors.digest_time ? (
                    <small className="field-error">{settingsErrors.digest_time}</small>
                  ) : null}
                </label>
                <label className="settings-field">
                  <span>Recipient</span>
                  <input
                    className="text-input"
                    type="email"
                    value={notificationSettings.recipient_email ?? ''}
                    placeholder={authStatus.user?.email ?? 'Digest recipient'}
                    onChange={(event) => updateLocalDigestSettings({ recipient_email: event.target.value })}
                  />
                  {settingsErrors.recipient_email ? (
                    <small className="field-error">{settingsErrors.recipient_email}</small>
                  ) : null}
                </label>
                <label className="settings-field">
                  <span>Timezone</span>
                  <input
                    className="text-input"
                    type="text"
                    value={notificationSettings.timezone}
                    onChange={(event) => updateLocalDigestSettings({ timezone: event.target.value })}
                  />
                  {settingsErrors.timezone ? (
                    <small className="field-error">{settingsErrors.timezone}</small>
                  ) : null}
                </label>
              </div>
              <p className="subtle">
                AI digest summary sends digest message metadata and snippets to OpenAI to generate a short briefing.
              </p>
              <div className="card-actions">
                <button className="button primary" type="button" onClick={() => void handleSaveDigestSettings()} disabled={busy}>
                  Save Digest Settings
                </button>
              </div>
            </>
          ) : (
            <p>Loading digest settings...</p>
          )}
        </article>
        {featureFlags.writing_style_cards ? (
          <article className="setting-card writing-style-card">
            <strong>Writing style</strong>
            <p className="subtle">
              Review and edit the private style card Auto-Respond uses when drafting replies.
            </p>
            <div className="writing-style-toolbar">
              <div className="settings-field">
                <span>Style owner</span>
                <strong>{signedInStyleEmail}</strong>
              </div>
              <div className="card-actions writing-style-toolbar-actions">
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => void handleCreateWritingStyleCard()}
                  disabled={busy || !authStatus.user?.email}
                >
                  Sample Sent Mail
                </button>
              </div>
            </div>
            <p className="subtle">
              Fynish samples your signed-in Gmail Sent mail, derives a private editable card, and leaves approval to you.
            </p>
            <div className="writing-style-list">
              {signedInWritingStyleCards.length === 0 ? (
                <p className="subtle">
                  No writing style card exists yet for {signedInStyleEmail}.
                </p>
              ) : (
                signedInWritingStyleCards.map((card) => {
                  const draft = writingStyleDrafts[card.id] ?? card.style_card_markdown
                  const hasUnsavedChanges = draft !== card.style_card_markdown
                  return (
                    <div className="writing-style-row" key={card.id}>
                      <div className="attention-note-row-header">
                        <div>
                          <strong>{card.account_email}</strong>
                          <p className="message-meta">
                            {card.source_provider.replaceAll('_', ' ')} | Updated {formatRelativeDate(card.updated_at)}
                          </p>
                        </div>
                        <div className="account-status-stack">
                          <span className={`status-pill ${card.status === 'approved' ? 'enabled' : 'disabled'}`}>
                            {card.status}
                          </span>
                          {hasUnsavedChanges ? <span className="count-pill">Unsaved</span> : null}
                        </div>
                      </div>
                      <textarea
                        className="text-input writing-style-textarea"
                        value={draft}
                        onChange={(event) => updateWritingStyleDraft(card.id, event.target.value)}
                      />
                      <div className="card-actions">
                        <button
                          className="button secondary"
                          type="button"
                          onClick={() => void handleSaveWritingStyleCard(card)}
                          disabled={busy || !hasUnsavedChanges}
                        >
                          Save Changes
                        </button>
                        <button
                          className="button primary"
                          type="button"
                          onClick={() => void handleApproveWritingStyleCard(card)}
                          disabled={busy || card.status === 'disabled'}
                        >
                          Approve
                        </button>
                        <button
                          className="button secondary"
                          type="button"
                          onClick={() => void handleCreateWritingStyleCard()}
                          disabled={busy}
                        >
                          Resample Sent Mail
                        </button>
                        <button
                          className="button ghost"
                          type="button"
                          onClick={() => void handleDisableWritingStyleCard(card)}
                          disabled={busy || card.status === 'disabled'}
                        >
                          Disable
                        </button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </article>
        ) : null}
        <article className="setting-card attention-notes-card">
          <strong>AI digest attention notes</strong>
          <p className="subtle">
            Attention notes guide only the AI digest summary. They do not change Gmail actions, queue rules, or auto-cleaning.
          </p>
          <div className="attention-note-create-grid">
            <label className="settings-field">
              <span>Domain</span>
              <input
                className="text-input"
                type="text"
                value={newAttentionDomain}
                placeholder="example.net"
                onChange={(event) => setNewAttentionDomain(event.target.value)}
              />
            </label>
            <label className="settings-field">
              <span>Label</span>
              <input
                className="text-input"
                type="text"
                value={newAttentionLabel}
                placeholder="Example Security"
                onChange={(event) => setNewAttentionLabel(event.target.value)}
              />
            </label>
            <label className="settings-field attention-note-wide-field">
              <span>Note</span>
              <textarea
                className="text-input attention-note-textarea"
                value={newAttentionNote}
                placeholder="Treat routine status messages as routine unless the subject or preview shows escalation."
                onChange={(event) => setNewAttentionNote(event.target.value)}
              />
            </label>
            <div className="card-actions attention-note-create-actions">
              <button
                className="button secondary"
                type="button"
                onClick={() => void handleCreateAiDigestAttentionNote()}
                disabled={busy || !newAttentionDomain.trim() || !newAttentionNote.trim()}
              >
                Add Note
              </button>
            </div>
          </div>
          <div className="attention-notes-list">
            {aiDigestAttentionNotes.map((note) => {
              const draft = attentionNoteDrafts[note.id] ?? {
                domain: note.domain,
                label: note.label,
                note: note.note,
              }
              return (
                <div className="attention-note-row" key={note.id}>
                  <div className="attention-note-row-header">
                    <strong>{note.label || note.domain}</strong>
                    <span className={`status-pill ${note.enabled ? 'enabled' : 'disabled'}`}>
                      {note.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </div>
                  <div className="attention-note-edit-grid">
                    <label className="settings-field">
                      <span>Domain</span>
                      <input
                        className="text-input"
                        type="text"
                        value={draft.domain}
                        onChange={(event) => updateAttentionNoteDraft(note.id, { domain: event.target.value })}
                      />
                    </label>
                    <label className="settings-field">
                      <span>Label</span>
                      <input
                        className="text-input"
                        type="text"
                        value={draft.label}
                        onChange={(event) => updateAttentionNoteDraft(note.id, { label: event.target.value })}
                      />
                    </label>
                    <label className="settings-field attention-note-wide-field">
                      <span>Note</span>
                      <textarea
                        className="text-input attention-note-textarea"
                        value={draft.note}
                        onChange={(event) => updateAttentionNoteDraft(note.id, { note: event.target.value })}
                      />
                    </label>
                  </div>
                  <div className="card-actions">
                    <button
                      className="button secondary"
                      type="button"
                      onClick={() => void handleSaveAiDigestAttentionNote(note)}
                      disabled={busy}
                    >
                      Save
                    </button>
                    <button
                      className="button secondary"
                      type="button"
                      onClick={() => void handleToggleAiDigestAttentionNote(note)}
                      disabled={busy}
                    >
                      {note.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      className="button ghost"
                      type="button"
                      onClick={() => void handleDeleteAiDigestAttentionNote(note)}
                      disabled={busy}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </article>
      </div>

      {canUseDevelopmentHarness ? (
        <article className="setting-card" style={{ marginTop: '14px' }}>
            <strong>Development Harness</strong>
            <p className="subtle">
              Mock-account controls are kept here for testing and validation, but they are no longer part of the normal product flow.
            </p>
            <div className="card-actions">
              <button className="button secondary" type="button" onClick={() => void handleConnectAccount()} disabled={busy}>
                Connect Mock Account
              </button>
              <label className="view-toggle">
                <input
                  type="checkbox"
                  checked={showMockAccounts}
                  onChange={() => setShowMockAccounts((current) => !current)}
                />
                <span>Show mock accounts in the app</span>
              </label>
            </div>
          </article>
      ) : null}
    </section>
  )

  return (
    <div className="app-shell">
      <div className="app-frame">
        <section className="masthead">
          <div className="masthead-brand">
            <img className="brand-logo" src={fynishMailLogo} alt="Fynish Mail" />
            <div className="masthead-title">
              <div className="eyebrow">Gmail triage and workflow automation</div>
              <h1>Fynish Mail</h1>
            </div>
          </div>

          {authStatus.auth_enabled ? (
            <div className="masthead-session" aria-label="Signed-in user">
              <div className="session-copy">
                <strong>{authStatus.user?.name ?? 'Signed in'}</strong>
                <span>{authStatus.user?.email ?? 'Private Fynish session'}</span>
              </div>
              <button className="button secondary" type="button" onClick={() => void handleLogout()} disabled={busy}>
                Log out
              </button>
            </div>
          ) : null}

          <div className="masthead-stats" aria-label="Queue snapshot">
            <div className="summary-stat">
              <strong>{queueStats.accountCount}</strong>
              <span>Accounts</span>
            </div>
            <div className="summary-stat">
              <strong>{queueStats.totalMessages}</strong>
              <span>Unread queued</span>
            </div>
            <div className="summary-stat">
              <strong>{totalStagedCount}</strong>
              <span>Staged</span>
            </div>
          </div>

          <p className="masthead-notice">{notice}</p>
        </section>

        <div className="top-nav">
          <button className="button secondary top-nav-refresh" type="button" onClick={() => void handleSync()} disabled={busy}>
            Refresh Mail Accounts
          </button>
          <nav className="section-tabs" aria-label="Primary navigation">
            {([
              ['queue', 'Review Queue'],
              ...(featureFlags.spam_rescue ? [['spam_rescue', 'Spam Rescue'] as [ViewName, string]] : []),
              ['processed', 'Processed Mail'],
              ['rules', 'Rules'],
              ['accounts', 'Accounts'],
              ['settings', 'Settings'],
            ] as Array<[ViewName, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`tab-button ${view === value ? 'active' : ''}`}
                onClick={() => setView(value)}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>

        {view === 'queue' ? renderQueue() : null}
        {view === 'spam_rescue' ? renderSpamRescue() : null}
        {view === 'processed' ? renderProcessed() : null}
        {view === 'rules' ? renderRules() : null}
        {view === 'accounts' ? renderAccounts() : null}
        {view === 'settings' ? renderSettings() : null}
      </div>
      {autoResponseMessage ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="auto-response-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="auto-response-title"
          >
            <div className="auto-response-header">
              <div>
                <div className="eyebrow">
                  {featureFlags.auto_response_send ? 'Reviewed response' : 'Draft-only response'}
                </div>
                <h2 id="auto-response-title">Auto-Respond</h2>
                <p className="message-meta">
                  {autoResponseMessage.sender} | {autoResponseMessage.subject}
                </p>
              </div>
              <button
                type="button"
                className="button secondary"
                onClick={closeAutoResponseModal}
                disabled={autoResponseBusy}
              >
                Close
              </button>
            </div>

            <label className="auto-response-field">
              <span>Context to include</span>
              <textarea
                value={autoResponseGuidance}
                onChange={(event) => setAutoResponseGuidance(event.target.value)}
                maxLength={1200}
                placeholder="Add facts, constraints, tone notes, or the outcome you want the reply to move toward."
                disabled={autoResponseBusy}
              />
            </label>

            <div className="auto-response-actions">
              <button
                type="button"
                className="button primary"
                onClick={() => void handleGenerateAutoResponseDraft()}
                disabled={autoResponseBusy}
              >
                {autoResponseBusy ? 'Generating...' : autoResponseDraft ? 'Regenerate Draft' : 'Generate Draft'}
              </button>
              <span className="message-meta">
                {featureFlags.auto_response_send
                  ? 'Review and edit before sending.'
                  : 'Fynish will not send this message.'}
              </span>
            </div>

            {autoResponseError ? <p className="queue-commit-error">{autoResponseError}</p> : null}

            {autoResponseDraft ? (
              <div className="auto-response-output">
                <div className="auto-response-output-header">
                  <strong>Draft response</strong>
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => void handleCopyAutoResponseDraft()}
                  >
                    Copy Draft
                  </button>
                </div>
                <textarea
                  value={autoResponseDraftBody}
                  onChange={(event) => {
                    setAutoResponseDraftBody(event.target.value)
                    setAutoResponseSendResult(null)
                  }}
                  readOnly={autoResponseBusy || Boolean(autoResponseSendResult)}
                />
                {featureFlags.auto_response_send ? (
                  <div className="auto-response-send-panel">
                    <div>
                      <strong>Send reviewed reply</strong>
                      <p className="message-meta">
                        Sends from {autoResponseMessage.account_email} in the original Gmail thread.
                      </p>
                    </div>
                    <button
                      type="button"
                      className="button primary"
                      onClick={() => void handleSendAutoResponse()}
                      disabled={autoResponseBusy || Boolean(autoResponseSendResult) || !autoResponseDraftBody.trim()}
                    >
                      {autoResponseBusy ? 'Sending...' : autoResponseSendResult ? 'Sent' : 'Send Reply'}
                    </button>
                  </div>
                ) : null}
                {autoResponseSendResult ? (
                  <p className="auto-response-sent">
                    Sent to {autoResponseSendResult.to_email}
                    {autoResponseSendResult.gmail_sent_message_id
                      ? ` | Gmail id ${autoResponseSendResult.gmail_sent_message_id}`
                      : ''}
                  </p>
                ) : null}
                {autoResponseDraft.caveats.length > 0 ? (
                  <ul className="reason-list auto-response-caveats">
                    {autoResponseDraft.caveats.map((caveat) => (
                      <li key={caveat}>{caveat}</li>
                    ))}
                  </ul>
                ) : null}
                <p className="auto-response-meta">
                  {autoResponseDraft.model} | {autoResponseDraft.style_source.replaceAll('_', ' ')} |{' '}
                  {featureFlags.auto_response_send ? 'review required' : 'draft only'}
                </p>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
      {showScrollTopButton ? (
        <button
          className="scroll-top-button"
          type="button"
          aria-label="Scroll to top"
          title="Scroll to top"
          onClick={handleScrollToTop}
        >
          <span aria-hidden="true">↑</span>
        </button>
      ) : null}
    </div>
  )
}

export default App
