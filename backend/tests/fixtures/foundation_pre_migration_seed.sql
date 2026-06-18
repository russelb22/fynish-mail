INSERT INTO accounts (
    email_address, enabled, provider, last_sync_at, created_at, updated_at
) VALUES
    ('legacy-mock@example.com', 1, 'mock_gmail', '2026-05-08T12:00:00+00:00', '2026-05-01T00:00:00+00:00', '2026-05-08T12:00:00+00:00'),
    ('legacy-live@gmail.com', 1, 'gmail_readonly', '2026-05-08T13:00:00+00:00', '2026-05-01T00:05:00+00:00', '2026-05-08T13:00:00+00:00'),
    ('legacy-disabled@gmail.com', 0, 'gmail_readonly', '2026-05-08T14:00:00+00:00', '2026-05-01T00:10:00+00:00', '2026-05-08T14:00:00+00:00');

INSERT INTO gmail_account_connections (
    account_id, token_path, scopes_json, created_at, updated_at
) VALUES
    (2, '/tmp/legacy-live-token.json', '["https://www.googleapis.com/auth/gmail.modify"]', '2026-05-01T00:05:00+00:00', '2026-05-08T13:00:00+00:00'),
    (3, '/tmp/legacy-disabled-token.json', '["https://www.googleapis.com/auth/gmail.readonly"]', '2026-05-01T00:10:00+00:00', '2026-05-08T14:00:00+00:00');

INSERT INTO messages (
    gmail_message_id, gmail_thread_id, account_email, sender, sender_domain, reply_to,
    recipient_to, recipient_cc, subject, received_at, snippet, body_preview,
    gmail_labels_json, headers_json, has_attachments, current_category, confidence,
    protected, reviewed, created_at, updated_at
) VALUES
    (
        'mock-100', 'mock-thread-100', 'legacy-mock@example.com',
        'Kitchen Mailer <hello@recipe-box.co>', 'recipe-box.co', 'hello@recipe-box.co',
        'legacy-mock@example.com', '', 'This week''s dinner newsletter',
        '2026-05-08T08:00:00+00:00',
        'A weekly dinner newsletter with recipes and offers.',
        'A weekly dinner newsletter with recipes, offers, and unsubscribe links.',
        '["INBOX","UNREAD","CATEGORY_PROMOTIONS"]', '{"List-Unsubscribe":"<mailto:unsubscribe@recipe-box.co>"}',
        0, 'bulk_mail', 0.91, 0, 0, '2026-05-08T08:00:00+00:00', '2026-05-08T08:00:00+00:00'
    ),
    (
        'live-200', 'live-thread-200', 'legacy-live@gmail.com',
        'Prize Center <claim@winner-promo.top>', 'winner-promo.top', 'claim@winner-promo.top',
        'legacy-live@gmail.com', '', 'Claim your reward before midnight',
        '2026-05-08T09:00:00+00:00',
        'Claim your reward before midnight.',
        'Claim your reward before midnight and confirm your payment details to release the prize.',
        '["INBOX","UNREAD","CATEGORY_PROMOTIONS"]', '{"Reply-To":"claim@winner-promo.top"}',
        0, 'junk_review', 0.87, 0, 0, '2026-05-08T09:00:00+00:00', '2026-05-08T09:00:00+00:00'
    ),
    (
        'live-201', 'live-thread-201', 'legacy-live@gmail.com',
        'Neighborhood Alerts <alerts@neighborhoodalerts.com>', 'neighborhoodalerts.com', 'alerts@neighborhoodalerts.com',
        'legacy-live@gmail.com', '', 'One repair could cost more than a decade of coverage',
        '2026-05-08T10:00:00+00:00',
        'One repair could cost more than a decade of coverage.',
        'One repair could cost more than a decade of coverage. Review your neighborhood alert now.',
        '["UNREAD","CATEGORY_PROMOTIONS"]', '{"List-Unsubscribe":"<mailto:unsubscribe@neighborhoodalerts.com>"}',
        0, 'trash', 0.96, 0, 1, '2026-05-08T10:00:00+00:00', '2026-05-08T10:05:00+00:00'
    ),
    (
        'disabled-300', 'disabled-thread-300', 'legacy-disabled@gmail.com',
        'Bank Alerts <alerts@bank.example>', 'bank.example', 'alerts@bank.example',
        'legacy-disabled@gmail.com', '', 'Security alert for your account',
        '2026-05-08T11:00:00+00:00',
        'We noticed a new sign-in.',
        'We noticed a new sign-in to your account from a new browser.',
        '["INBOX","UNREAD","IMPORTANT"]', '{"From":"alerts@bank.example"}',
        0, 'keep', 0.99, 1, 0, '2026-05-08T11:00:00+00:00', '2026-05-08T11:00:00+00:00'
    );

INSERT INTO classification_results (
    message_id, category, confidence, reasons_json, protected, protection_reasons_json, created_at
) VALUES
    (1, 'bulk_mail', 0.91, '["List-Unsubscribe header found","Promotional content detected"]', 0, '[]', '2026-05-08T08:00:01+00:00'),
    (2, 'junk_review', 0.87, '["Suspicious reward language","Unknown sender domain"]', 0, '[]', '2026-05-08T09:00:01+00:00'),
    (3, 'trash', 0.96, '["Repeated promotional content","High confidence spam pattern"]', 0, '[]', '2026-05-08T10:00:01+00:00'),
    (4, 'keep', 0.99, '["Known bank alert pattern"]', 1, '["Financial/security protected topic"]', '2026-05-08T11:00:01+00:00');

INSERT INTO rules (
    scope, account_email, rule_type, pattern, action, enabled, created_from_account,
    created_from_message_id, match_count, last_matched_at, created_at, updated_at
) VALUES
    ('global', NULL, 'domain', 'recipe-box.co', 'junk_review', 1, NULL, NULL, 4, '2026-05-08T08:15:00+00:00', '2026-05-07T00:00:00+00:00', '2026-05-08T08:15:00+00:00'),
    ('account', 'legacy-live@gmail.com', 'domain', 'example.net', 'trash', 1, 'legacy-live@gmail.com', 'live-200', 2, '2026-05-08T09:15:00+00:00', '2026-05-07T01:00:00+00:00', '2026-05-08T09:15:00+00:00'),
    ('account', 'legacy-disabled@gmail.com', 'sender', 'alerts@bank.example', 'keep', 0, 'legacy-disabled@gmail.com', 'disabled-300', 1, '2026-05-08T11:15:00+00:00', '2026-05-07T02:00:00+00:00', '2026-05-08T11:15:00+00:00');

INSERT INTO actions_log (
    gmail_message_id, account_email, selected_action, recommended_action, user_overrode,
    gmail_labels_added_json, gmail_labels_removed_json, created_rule_id, created_at
) VALUES
    (
        'live-201', 'legacy-live@gmail.com', 'trash', 'trash', 0,
        '["Fynish/Trash"]', '["INBOX"]', NULL, '2026-05-08T10:05:00+00:00'
    ),
    (
        'mock-100', 'legacy-mock@example.com', 'keep', 'bulk_mail', 1,
        '[]', '[]', 1, '2026-05-08T08:20:00+00:00'
    );

INSERT INTO notification_settings (
    id, enabled, recipient_email, timezone, morning_enabled, morning_time,
    evening_enabled, evening_time, send_only_if_queue_nonempty, created_at, updated_at
) VALUES
    (
        1, 1, 'owner@example.com', 'America/Los_Angeles', 1, '08:15',
        0, '16:00', 1, '2026-05-01T00:00:00+00:00', '2026-05-08T12:30:00+00:00'
    );
