# Processed Mail Expansion Interaction Plan

## Purpose

This document evaluates a refinement to the `Processed Mail` tab:

- keep the default list even denser
- show only the email title/subject in the main row
- reveal more email text only when the user clicks the row

Status:

- implemented

## Recommendation

This is a good idea.

It fits the purpose of the `Processed Mail` tab well because that screen is primarily:

- an audit trail
- an activity feed
- a confidence-building review surface

not:

- a deep reading interface

Reducing the default row to the most important metadata will make the list easier to scan, especially when many items have long sender strings or long preview text.

## Recommended interaction

I recommend:

- keep the main processed row to exactly one line
- remove the body preview from the default row
- show only:
  - action
  - account
  - sender
  - subject
  - processed time
- when the user clicks the row, open an inline expandable detail panel directly beneath it

I do **not** recommend a popup for the first version.

## Why inline expansion is better than a popup

An inline expansion panel is better here because:

1. it preserves context in the timeline
2. it makes it obvious which processed message is being expanded
3. it is easier to scan multiple items in sequence
4. it avoids modal/popup interaction overhead
5. it is simpler to implement and less fragile on smaller screens

So the recommended pattern is:

- collapsed one-line row by default
- click row
- a second lightweight detail row expands below it

## UX goals

### Primary goals

- make the processed list denser and faster to scan
- keep the audit trail readable without visual clutter
- let the user inspect more text only on demand

### Secondary goals

- make room for longer subjects
- reduce line noise from preview text
- create a pattern that could later support showing more metadata

## Proposed row behavior

### Default collapsed row

Show only:

```text
[Action] [Account] [Sender] [Subject] [Processed time]
```

Example:

```text
Soft Trash  primary.user@example.com  notifications@example.net  Example alert subject  7:48 AM
```

### Expanded detail row

When expanded, show a compact detail panel below the main row with:

- subject repeated only if useful
- preview/body excerpt
- optional flags such as:
  - `Auto-processed by rule`
  - `User override`
  - `Created rule`

Example:

```text
Preview: Garage panel armed at 7:42 AM. User: Russle Brunton. Partition: Bridgland...
```

## Recommended visual behavior

### Collapsed state

- one line only
- no wrapping
- ellipsis on overflow
- row remains compact

### Expanded state

- inserted directly below the clicked row
- light background or inset panel
- up to 5 lines of preview text
- no full message body dump

### Expansion rule

Recommended first version:

- only one processed message can be expanded at a time

Why:

- keeps the list clean
- reduces scroll thrash
- simplifies state management

## Accessibility recommendation

The row should behave like an expandable disclosure control:

- clickable row or explicit chevron affordance
- `aria-expanded`
- keyboard accessible via Enter/Space if a button-like control is used

## Backend impact

Small.

The processed-messages endpoint now returns:

- `subject`
- `preview`
- processed metadata

The implemented version also widened the preview construction so the expansion panel has enough text to fill multiple lines:

- snippet and body preview are combined when both are available
- preview text is clamped much less aggressively than the original one-line summary

Possible optional backend additions later:

- `auto_processed: boolean`
- `created_rule_id`
- `user_overrode`
- `received_at`

But the current payload is already enough for the first interaction change.

## Frontend impact

Moderate but straightforward.

Changes needed:

1. remove preview text from the collapsed processed row
2. add row-expanded state by processed message id
3. render an inline expandable detail section under the active row
4. keep rows single-line in collapsed state

## Suggested implementation approach

### Phase 1

- make collapsed rows subject-only for message content
- add single expanded row state
- show preview text below when expanded

### Phase 2

- add a small chevron or disclosure icon
- add optional metadata in the expanded section

### Phase 3

- optional keyboard polish
- optional account/action filtering if the list grows

## Edge cases

### Missing preview text

If a processed message has no preview:

- still allow expansion
- show `No preview available`

### Long sender + long subject

Collapsed row should still remain one line with truncation.

Priority order for visible content:

1. action
2. subject
3. sender
4. account
5. processed time

This may require column tuning during implementation.

### Repeated clicks

Recommended behavior:

- clicking the same row again collapses it
- clicking a different row closes the old one and opens the new one

## Acceptance criteria

This enhancement is complete when:

1. the default `Processed Mail` rows show no preview text
2. the default row remains exactly one line tall
3. clicking a row expands an inline detail area below it
4. the detail area shows additional email text from the existing preview
5. only one row is expanded at a time
6. the expanded preview can show up to 5 lines
7. the interaction remains fast and readable on real processed-mail volumes

## Recommendation in one sentence

Proceed with this upgrade, but implement it as an inline expandable detail row rather than a popup, because that will keep the `Processed Mail` tab denser, clearer, and easier to scan.
