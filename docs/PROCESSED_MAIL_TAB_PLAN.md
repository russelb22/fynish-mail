# Processed Mail Tab Feature Plan

## Purpose

This document plans a new main-page tab for Fynish that shows a single chronological list of emails already processed by Fynish.

The goal is to give the user a simple audit/review surface for recent Fynish activity without needing to inspect Gmail directly or search through rules/action logs.

Status:

- implemented
- later refined by [docs/PROCESSED_MAIL_EXPANSION_PLAN.md](docs/PROCESSED_MAIL_EXPANSION_PLAN.md)

## Feature summary

Add a new top-level tab to the main Fynish page:

- `Processed Mail`

This tab should show:

- one flat list across all visible accounts
- most recent processed emails at the top
- one row per processed email
- compact single-line display per row

Each row should include, as space allows:

- source email / sender
- destination email / account
- subject
- processed action/category
- processed timestamp

## Working definition of “processed”

For this feature, “processed by Fynish” should mean:

- the message has a corresponding `actions_log` row created by Fynish

This includes:

- manual row actions
- category bulk actions
- rule-driven auto-processing during sync
- `Keep` actions that remove a message from the queue

This definition is better than relying only on `messages.reviewed = 1`, because:

- some messages may become reviewed for reconciliation reasons
- `actions_log` gives us an actual Fynish action record
- the log already contains action metadata and timing

## Product goals

### Primary goals

- let the user quickly review what Fynish has done recently
- create confidence that actions are being applied correctly
- provide a compact “activity feed” for processed messages
- support future debugging and audit workflows

### Secondary goals

- help spot accidental over-processing
- make rule auto-processing more transparent
- create a foundation for future undo/audit tooling

## Non-goals

This first version should not attempt to:

- provide full message detail pages
- provide undo actions
- provide Gmail-side restore from this screen
- support advanced filtering beyond simple basic controls
- show multiple visual lines per message

## Assumptions for V1 of this feature

These are the assumptions I recommend unless you want to change them:

1. The list should include all Fynish-processed actions, including `Keep`.
2. The list should merge all visible accounts into one timeline.
3. The list should respect the existing `Show mock accounts` setting.
4. The list should default to a reasonable recent limit, such as 200 rows.
5. The row should stay strictly one line tall with truncation, not wrapping.
6. The body preview should be short and only shown when there is room.

## Current data sources

The current system already has almost everything needed:

- `actions_log`
- `messages`

Relevant existing fields:

### `actions_log`

- `gmail_message_id`
- `account_email`
- `selected_action`
- `recommended_action`
- `user_overrode`
- `gmail_labels_added_json`
- `gmail_labels_removed_json`
- `created_rule_id`
- `created_at`

### `messages`

- `gmail_message_id`
- `account_email`
- `sender`
- `subject`
- `snippet`
- `body_preview`
- `received_at`
- `current_category`

That means the backend can build this feature now without any schema change.

## Recommended backend approach

### New service function

Add a new backend service query, for example:

- `get_processed_messages(limit: int = 200, account_email: str | None = None)`

This should:

1. read from `actions_log`
2. join to `messages` on:
   - `gmail_message_id`
   - `account_email`
3. sort by `actions_log.created_at DESC`
4. return compact row payloads

### Recommended SQL shape

Conceptually:

```sql
SELECT
  l.id,
  l.created_at AS processed_at,
  l.account_email,
  l.selected_action,
  l.recommended_action,
  l.user_overrode,
  l.created_rule_id,
  m.sender,
  m.subject,
  m.snippet,
  m.body_preview,
  m.received_at
FROM actions_log l
LEFT JOIN messages m
  ON l.gmail_message_id = m.gmail_message_id
 AND l.account_email = m.account_email
ORDER BY l.created_at DESC
LIMIT ?
```

### New API endpoint

Recommended endpoint:

- `GET /api/messages/processed`

Suggested query params:

- `limit`
- optional later: `account_email`

Suggested response shape:

```json
{
  "messages": [
    {
      "id": 501,
      "processed_at": "2026-05-08T14:20:00+00:00",
      "account_email": "primary.user@example.com",
      "sender": "alerts@example.net",
      "subject": "Security alert for your account",
      "preview": "We noticed a sign-in from a new browser...",
      "selected_action": "keep",
      "recommended_action": "keep",
      "user_overrode": false
    }
  ]
}
```

### Preview construction

Recommended preview logic:

- combine `snippet` and `body_preview` when both exist and differ
- normalize whitespace
- clamp to a longer excerpt suitable for inline expansion
- use the preview primarily in the expanded detail state, not the collapsed row

## Recommended frontend approach

### New tab

Extend the current top-level views with:

- `processed`

Current views are:

- `queue`
- `rules`
- `accounts`
- `settings`
- `reminders`

The new view would become:

- `processed`

### Placement

Recommended placement in the top nav:

- immediately after `Review Queue`

That keeps it close to the core workflow.

### Page layout

Keep the page intentionally simple:

1. compact header
2. optional count summary
3. single scrollable list/table

### Row layout

Every row should remain one line tall.

Recommended order:

```text
[Action] [Account] [Sender] [Subject] [Processed time]
```

Alternative, if account/source reads better:

```text
[Processed time] [Action] [Account] [Sender] [Subject]
```

My recommendation:

- put `Action` first for quick scanning
- put `Processed time` at the far right

Example:

```text
Soft Trash  primary.user@example.com  alerts@example.net  Example alert subject...  7:48 AM
```

### Visual behavior

Recommended UI rules:

- no wrapping in collapsed state
- `white-space: nowrap`
- `overflow: hidden`
- `text-overflow: ellipsis`
- one subtle row divider
- compact font and spacing

For the implemented version:

- collapsed rows stay one line tall
- clicking a row expands an inline detail panel beneath it
- the detail panel shows a longer preview excerpt

### Optional first-pass controls

If desired in V1 of this feature:

- `Refresh` button that just reloads the processed list
- count of currently displayed processed rows

Not necessary yet:

- search
- filter chips
- account dropdown
- date range filters

## Interaction design notes

This screen should feel more like:

- an activity log

than:

- another triage screen

So I recommend:

- no checkboxes
- no action buttons in the first version
- no multi-line cards

That keeps it fast and readable.

## Performance considerations

This query should be inexpensive at current scale, but we should still:

- default to a bounded limit such as 200
- sort by indexed or indexable timestamp

Recommended future index if needed:

- `actions_log(created_at DESC)`

If the list grows substantially later, we can add:

- pagination
- cursor-based fetch
- account filters

## Edge cases

### 1. Message exists in actions log but not in messages

Possible if:

- message row was cleaned up or migration changes later

Recommended handling:

- still render the row
- show fallback text such as:
  - sender: `Unknown sender`
  - subject: `Unknown subject`

### 2. Same message processed multiple times

This can happen if:

- a message is re-imported and reprocessed later

Recommended handling:

- show each action log row separately
- do not dedupe in the UI

This is an activity log, so separate events are useful.

### 3. Auto-processed rule actions

Recommended handling:

- include them normally
- later we can add a subtle indicator like `Auto`

### 4. Keep actions

Recommended handling:

- include them

This is important for a full audit trail and user trust.

## Testing plan

### Backend tests

Add tests for:

- processed endpoint returns most recent rows first
- joins message data correctly
- handles missing message join gracefully
- respects limit
- includes auto-applied rule actions

### Frontend tests

Add tests for:

- new `Processed Mail` tab renders
- rows stay one line
- newest entries appear first
- visible account filtering respects mock-account toggle

### Manual validation

Recommended manual test set:

1. process one `Keep`
2. process one `Junk`
3. process one `Soft Trash`
4. trigger one rule auto-process
5. verify all four appear in the processed list in descending timestamp order

## Suggested implementation phases

### Phase 1: Backend support

- add processed messages service query
- add API endpoint
- add tests

### Phase 2: Frontend tab

- add `Processed Mail` tab
- add compact one-line row list
- add data fetch and loading states

### Phase 3: Polish

- improve truncation and spacing
- optional account/action badges
- optional `Auto` indicator for rule-driven processing

## Acceptance criteria

This feature is complete when:

1. there is a new `Processed Mail` tab in the main navigation
2. it shows a flat list of processed emails across visible accounts
3. the newest processed emails appear first
4. each row is exactly one line tall
5. each row shows sender, destination account, subject, and short preview where space allows
6. rows are sourced from actual Fynish processing events, not just reviewed messages
7. the view remains fast and readable with at least 200 recent rows

## Recommendation

This is a strong next feature.

It is relatively low risk because:

- it can be built from existing data
- it does not require schema changes
- it improves trust and visibility immediately

I recommend implementing it as a read-only activity tab first, then deciding later whether it should gain filtering, undo, or audit controls.
