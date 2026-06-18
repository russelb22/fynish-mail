CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_address TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    provider TEXT NOT NULL DEFAULT 'mock_gmail',
    last_sync_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mail_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    external_account_email TEXT NOT NULL,
    display_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    high_confidence_auto_clean_enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    last_sync_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, provider, external_account_email),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS provider_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_account_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    connection_type TEXT NOT NULL DEFAULT 'oauth',
    credentials_ref TEXT,
    token_path TEXT,
    scopes_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(mail_account_id) REFERENCES mail_accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS digest_sender_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    email_address TEXT NOT NULL,
    connection_type TEXT NOT NULL DEFAULT 'oauth',
    token_path TEXT,
    scopes_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, email_address)
);

CREATE TABLE IF NOT EXISTS oauth_connect_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    scope_mode TEXT NOT NULL,
    oauth_state TEXT NOT NULL UNIQUE,
    redirect_after TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT NOT NULL,
    gmail_thread_id TEXT,
    account_email TEXT NOT NULL,
    sender TEXT,
    sender_domain TEXT,
    reply_to TEXT,
    recipient_to TEXT,
    recipient_cc TEXT,
    subject TEXT,
    received_at TEXT,
    snippet TEXT,
    body_preview TEXT,
    gmail_labels_json TEXT NOT NULL DEFAULT '[]',
    headers_json TEXT NOT NULL DEFAULT '{}',
    has_attachments INTEGER NOT NULL DEFAULT 0,
    current_category TEXT,
    confidence REAL,
    protected INTEGER NOT NULL DEFAULT 0,
    recovery_pending INTEGER NOT NULL DEFAULT 0,
    reviewed INTEGER NOT NULL DEFAULT 0,
    queue_source TEXT NOT NULL DEFAULT 'classifier',
    queue_source_detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(gmail_message_id, account_email)
);

CREATE TABLE IF NOT EXISTS classification_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    protected INTEGER NOT NULL DEFAULT 0,
    protection_reasons_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL DEFAULT 'global',
    account_email TEXT,
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_from_account TEXT,
    created_from_message_id TEXT,
    match_count INTEGER NOT NULL DEFAULT 0,
    last_matched_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT NOT NULL,
    account_email TEXT NOT NULL,
    selected_action TEXT NOT NULL,
    recommended_action TEXT,
    user_overrode INTEGER NOT NULL DEFAULT 0,
    action_source TEXT NOT NULL DEFAULT 'manual',
    gmail_labels_added_json TEXT NOT NULL DEFAULT '[]',
    gmail_labels_removed_json TEXT NOT NULL DEFAULT '[]',
    created_rule_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staged_commit_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS auto_response_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    mail_account_id INTEGER,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'gmail',
    account_email TEXT NOT NULL,
    to_email TEXT NOT NULL,
    cc_email TEXT,
    bcc_email TEXT,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    gmail_thread_id TEXT,
    gmail_sent_message_id TEXT,
    gmail_response_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(message_id) REFERENCES messages(id),
    FOREIGN KEY(mail_account_id) REFERENCES mail_accounts(id)
);

CREATE TABLE IF NOT EXISTS gmail_account_connections (
    account_id INTEGER PRIMARY KEY,
    token_path TEXT NOT NULL,
    scopes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notification_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    recipient_email TEXT,
    timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    morning_enabled INTEGER NOT NULL DEFAULT 1,
    morning_time TEXT NOT NULL DEFAULT '08:00',
    evening_enabled INTEGER NOT NULL DEFAULT 1,
    evening_time TEXT NOT NULL DEFAULT '16:00',
    send_only_if_queue_nonempty INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_settings_by_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    recipient_email TEXT,
    timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    morning_enabled INTEGER NOT NULL DEFAULT 1,
    morning_time TEXT NOT NULL DEFAULT '08:00',
    evening_enabled INTEGER NOT NULL DEFAULT 1,
    evening_time TEXT NOT NULL DEFAULT '16:00',
    send_only_if_queue_nonempty INTEGER NOT NULL DEFAULT 1,
    digest_enabled INTEGER NOT NULL DEFAULT 0,
    digest_time TEXT NOT NULL DEFAULT '17:00',
    ai_digest_summary_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS ai_digest_domain_attention_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, domain),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS writing_style_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mail_account_id INTEGER,
    account_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    source_provider TEXT NOT NULL DEFAULT 'manual',
    sample_start_date TEXT,
    sample_end_date TEXT,
    sample_bucket_count INTEGER NOT NULL DEFAULT 0,
    sampled_message_count INTEGER NOT NULL DEFAULT 0,
    sampled_word_count INTEGER NOT NULL DEFAULT 0,
    style_card_markdown TEXT NOT NULL,
    style_card_json TEXT,
    user_edited INTEGER NOT NULL DEFAULT 0,
    edited_at TEXT,
    generator_model TEXT,
    generated_at TEXT NOT NULL,
    approved_at TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(mail_account_id) REFERENCES mail_accounts(id)
);

CREATE TABLE IF NOT EXISTS digest_delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    digest_type TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    scheduled_for TEXT,
    sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    recipient_email TEXT,
    processed_count INTEGER NOT NULL DEFAULT 0,
    new_rules_count INTEGER NOT NULL DEFAULT 0,
    queue_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
