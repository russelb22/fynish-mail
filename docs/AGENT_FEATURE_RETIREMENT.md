# Agent feature retirement

Fynish no longer generates AI digest briefings or replies, sends replies through
Auto-Respond, or samples Sent mail for a writing-style card. The standard daily
digest still runs on its existing schedule and uses the existing digest-sender
connection. Gmail sign-in, sync, staged actions, rules, recovery, and Spam Rescue
are unchanged. Keep the Gmail read/modify scopes and the digest sender's send
scope where those features require them.

## Rolling deployment

Upgrade the backend before or alongside the frontend. Older web bundles still
request the attention-notes endpoint on startup. It returns an authenticated
empty list, retired feature flags are false, and legacy digest summary fields
remain false/null. Legacy digest settings updates ignore the AI toggle without
overwriting its stored value. Retired feature write endpoints and reply routes
are unavailable.

The existing schema and stored rows are deliberately untouched. Decide on
retention for historical reply-send audit data separately before a migration.
After older clients are no longer in use, remove compatibility responses and,
under a separate reviewed data migration, retire old schema from SQLite and
Postgres. Old AI-specific deployment variables are no longer read by this
revision. Remove those settings and review any dedicated credential after the
rollback window, without affecting credentials shared by other services.

Earlier AI feature specs are historical. This change does not adjust Google
Workspace API quotas or billing.
