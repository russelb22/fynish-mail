# Send To Things V1 Plan

## Summary

Add a per-message `Send to Things` action to Fynish so a user can turn an email into a task in the Things app on Mac.

V1 should be:
- explicit
- lightweight
- user-initiated
- Mac-only
- Things-only
- non-destructive to email state

The goal is not to make Things a core dependency of Fynish. The goal is to validate a broader product idea:

- some emails should become tasks instead of being immediately archived, kept, trashed, or ruled away

## Product position

This should be treated as:
- an optional power feature
- a message-to-task export
- the first destination in a future task-export concept

It should **not** be framed as:
- a core requirement for using Fynish
- a full task-management integration platform

Recommended product framing:
- `Send to Things`

Not recommended for V1:
- generic `To Do Item` wording without an actual multi-destination system behind it

Reason:
- the implementation is specifically Mac + Things in V1
- the explicit label sets the right expectation

## Why Things first

Things is the best first target because:
- it has no full public API, but it does have an official URL scheme
- the URL scheme is browser-friendly for a hosted app
- it avoids building a local Mac helper just to validate the concept
- it is lower effort than a Reminders/AppleScript bridge

Official references:
- Things FAQ: no public API, but AppleScript and URL scheme are supported
- Things URL scheme
- Things AppleScript support

## Core user story

As a Fynish user,
when I see an email that represents work I should do later,
I want to click one button and create a Things task from that email,
so I can move the work into my task system without losing the message context.

## V1 behavior

### Entry point

Add a button in the `THIS MESSAGE` action area on the Review Queue page:

- `Send to Things`

This should appear alongside the other per-message actions, but remain clearly secondary to the main triage actions.

### On click

When clicked:
1. Fynish builds a Things `add` URL
2. the browser opens the Things URL
3. Things creates a new task
4. Fynish shows a local notice like:
   - `Opening Things to create a task from this message.`

### Task content

Use the email subject as the Things task title.

Use a cleaned plain-text note body built from:
- sender
- account email
- received timestamp
- subject
- body preview or expanded message body
- optional “Created from Fynish” footer

Recommended note template:

```text
From: {sender}
Account: {account_email}
Received: {received_at}
Subject: {subject}

{message_body_or_preview}

Created from Fynish
```

### Email state

Do **not** automatically mutate the email when the user sends it to Things.

V1 should not:
- mark the message reviewed
- remove it from the queue
- archive it
- keep it
- create a rule

Reason:
- “send to task system” is different from “done triaging”
- the user may still want to decide whether the email should stay, be trashed, or be ruled

## Scope

### In scope

- Mac + Things support only
- one-click per-message export from Review Queue
- Things task creation via URL scheme
- plain-text task note generation
- UI notice on click
- lightweight local audit event in Fynish

### Out of scope

- Reminders integration
- AppleScript execution
- local Mac helper app
- bulk export
- syncing task completion back into Fynish
- detecting whether Things is installed
- preventing duplicate task creation
- task due dates, tags, projects, areas, or headings
- multi-destination task export abstraction

## Technical approach

### Browser-side launch

Use the Things URL scheme directly from the browser.

Expected shape:
- `things:///add?...`

Populate:
- `title`
- `notes`

This should be triggered by a real user click, which gives the best chance that browsers on macOS will allow the custom URL scheme handoff.

### Why not AppleScript in V1

Do not use AppleScript in V1.

Reason:
- a hosted browser app cannot directly run AppleScript on the user’s Mac
- the backend in Cloud Run cannot touch local apps
- AppleScript would require a local bridge/helper process

That is too much infrastructure for the first validation step.

### Why not Reminders first

Do not route through Apple Reminders first.

Reason:
- Reminders still needs a local bridge if controlled via AppleScript
- it adds an unnecessary indirection layer
- users with Things should get a direct Things flow

## Data generation rules

### Title

Source:
- email `subject`

Fallback:
- `Untitled email task`

### Notes

Source priority:
1. expanded message body text if already available in the UI
2. `body_preview`
3. `snippet`

### Sanitization

Before building the URL:
- convert to plain text
- strip obvious HTML
- normalize whitespace
- trim very long content

### Length limit

Impose a V1 note limit before URL encoding.

Recommended initial limit:
- 4,000 to 8,000 characters

Reason:
- Things supports notes, but very large payloads are a browser and URL-handling risk
- V1 should optimize for reliability over completeness

## UI design

### Placement

Place `Send to Things` in the `THIS MESSAGE` area on Review Queue.

Why:
- this is a message-level choice
- it belongs with message-level actions, not global rule creation
- it should be available where the user is already deciding what to do with a message

### Visual weight

Make it visually secondary to:
- `Keep`
- `Bulk Mail`
- `Junk`
- `Trash`

Suggested style:
- secondary pill button
- not highlighted as a primary destructive or routing action

### Notice text

Suggested success-side notice:
- `Opening Things to create a task from this message.`

Suggested fallback/error text:
- `Unable to open Things from this browser.`

## Audit behavior

Record the export in Fynish so the user has a local trace that they created a task.

Recommended V1 action log event:
- `selected_action = 'send_to_things'`

Important:
- do not show this as a standard processed-mail routing action
- or, if shown later, show it as a distinct export-type event

V1 can keep this simple:
- log it
- do not build a full task-history UI yet

## Suggested implementation shape

### Frontend

Add:
- helper to build a Things URL from a queue message
- per-message click handler
- UI button in `THIS MESSAGE`

Likely files:
- `frontend/src/App.tsx`
- `frontend/src/api.ts` only if audit logging is routed through backend
- `frontend/src/types.ts` only if new API response data is needed

### Backend

Two viable V1 options:

#### Option A: frontend-only launch

Frontend directly builds and opens the Things URL.

Pros:
- smallest implementation
- no backend dependency for task creation

Cons:
- no audit trail unless handled separately

#### Option B: frontend launch + backend audit event

Frontend builds and opens the Things URL, then calls a backend endpoint to log the export.

Pros:
- preserves a Fynish audit trail
- better long-term foundation

Cons:
- slightly more code

Recommended V1:
- **Option B**

### Suggested backend endpoint

Add a lightweight endpoint such as:

- `POST /api/messages/{message_id}/send-to-things`

Behavior:
- log a `send_to_things` event in `actions_log`
- return `200`
- do not mutate message queue state

Important:
- the backend should **not** attempt to talk to Things
- the browser remains responsible for opening the Things URL

## Edge cases

### Things not installed

If Things is not installed:
- the browser may show nothing useful or fail to open the URL scheme

V1 handling:
- keep it simple
- show a generic failure notice if the launch appears to fail

Do not overengineer installation detection in V1.

### Duplicate clicks

If the user clicks twice:
- two Things tasks may be created

Acceptable in V1.

Future improvement:
- add local “already sent to Things” indicator

### Long email body

If the email body is very long:
- truncate notes before URL generation

### Special characters

Always URL-encode:
- title
- notes

## Testing plan

### Unit tests

Add tests for:
- Things URL builder
- note text generation and truncation
- subject fallback behavior
- plain-text sanitization behavior

### UI tests

Validate:
- button appears in `THIS MESSAGE`
- clicking it triggers the launch function
- notice is shown

### Manual validation

On a Mac with Things installed:
1. open a message in Review Queue
2. click `Send to Things`
3. confirm Things opens
4. confirm task title matches email subject
5. confirm notes include sender + body text
6. confirm the message remains in Fynish queue

## Success criteria

V1 is successful when:
- a user can click `Send to Things` from a queue message
- Things opens and creates a task
- task title comes from the email subject
- task notes contain useful email context
- Fynish does not accidentally change message review state
- the flow feels fast and low-friction

## Recommended next step after V1

If V1 feels good, the next iteration should be:

1. add export audit logging and a subtle “Sent to Things” indicator if not already included
2. consider a generic task-export abstraction
3. only later explore:
   - Apple Reminders
   - local AppleScript bridge
   - additional task destinations
