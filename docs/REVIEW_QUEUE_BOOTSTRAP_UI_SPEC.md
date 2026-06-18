# Review Queue Bootstrap UI Spec

## Goal
Make the Review Queue easier for a new user who is teaching Fynish how to handle large volumes of mail. The page should optimize for quick one-message decisions and fast rule creation, not batch processing.

## Primary UX principles
- Favor per-message actions over batch actions.
- Expose rule creation choices directly instead of hiding them in a dropdown.
- Separate "do this once" from "teach Fynish for the future."
- Keep every important decision to one click.

## Proposed interaction model
Each message card should have two action groups:

### 1. This Message
These buttons apply only to the current message and execute immediately.
- Keep
- Bulk
- Junk
- Trash

### 2. Teach Fynish
These buttons create a rule and also apply that outcome to the current message.
- Always Keep Domain
- Always Junk Domain

## Elements to de-emphasize
- Disable or hide `Execute Selected + Create Rules` during the bootstrap-focused redesign.
- Remove the `Create Rule` dropdown from the primary queue workflow.
- Remove `Live Preflight` and `Execute Live` from the main queue workflow.
- Keep bulk/category actions in the backend for now, but do not emphasize them in the UI.

## Accepted UI direction
- Keep the existing top-of-card reading order:
  - sender / subject
  - clickable `Preview`
  - `RECOMMENDATION: <Action>`
  - reasons
  - `This Message`
  - `Teach Fynish`
- Keep `Preview` collapsed by default to a short excerpt and allow inline expansion to a scrollable text box.
- Allow only one expanded preview at a time in the queue.
- Make `This Message` and `Teach Fynish` sibling panels below the recommendation area.
- Keep the rule panel visually lighter but still fully visible.
- Add short helper text explaining that rule buttons both save the rule and action the current message.
- Use `Trash` as the visible UI label even though the backend action key remains `trash`.

## Implemented queue behavior
- The main queue now uses the accepted bootstrap-first layout.
- `Execute Selected + Create Rules` remains present only as a disabled placeholder during the redesign.
- The `Create Rule` dropdown is removed from the main queue.
- `Live Preflight` and `Execute Live` are removed from the main queue.
- The queue now uses direct one-click rule teaching:
  - `Always Keep Domain`
  - `Always Junk Domain`
- The queue uses `Trash` rather than `Soft Trash` in visible UI labels.

## Acceptance criteria
- The user can visually compare single-message actions vs rule-teaching actions.
- The queue feels simpler than the previous dropdown-based flow.
- The layout remains readable without requiring hidden controls.
- The page makes clear that batch actions are being de-emphasized for new-user bootstrap mode.
- The preview expansion pattern is useful now and can later evolve into a fuller message/thread read surface.
