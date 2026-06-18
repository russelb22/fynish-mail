# Review Queue Visual Classification UI Plan

## Purpose

This document defines the next UI refinement for the Fynish Review Queue:

- remove multi-select checkboxes from queue rows
- emphasize the suggested classification visually
- make the queue faster to scan at a glance

The goal is to better match Fynish’s current real workflow:

- one-message-at-a-time triage
- visually clear suggested category
- easy confirmation or override by the user

## Summary

The Review Queue should move away from looking like a selectable batch-processing list and toward looking like a prioritized triage surface.

Recommended changes:

1. remove the queue-row checkbox
2. add a classification pill to each message row
3. include both category label and confidence percentage in the pill
4. lightly tint each message row/card based on the suggested category
5. keep per-message actions unchanged for V1 of this UI change

## Product Intent

The visual language should communicate:

- “Fynish suggests this category”
- not “this action has already been taken”

So the design should feel:

- confident
- scannable
- calm
- reversible

It should not feel:

- alarmist
- over-automated
- final

## Scope

### In scope

- queue row visual redesign
- classification pill
- confidence display
- category-based soft row tint
- checkbox removal

### Out of scope

- new action logic
- new classification logic
- bulk action redesign
- processed mail styling changes
- mobile-specific redesign beyond making sure the new UI still fits

## Current Problem

The current queue still carries some batch-processing UI assumptions:

- message selection checkboxes
- less visual emphasis on the suggested category itself

That creates two mismatches:

1. the UI suggests a bulk workflow users are not actually using
2. the suggested classification is present, but not visually strong enough for fast scanning

## Desired Outcome

Each message in the Review Queue should clearly show:

- the message sender / subject context
- the suggested category
- the confidence score
- a soft category-colored background hint

The result should make it easier to scan down the queue and instantly understand:

- what Fynish thinks
- how certain it is
- which items deserve a quick confirm versus a careful look

## Recommended UI Model

## 1. Remove Queue Selection Checkboxes

### Change

Remove the per-message checkbox from queue rows.

### Why

- the current user workflow is not centered on selecting many messages and applying one action
- the checkbox adds clutter
- it visually implies a spreadsheet-like batch interaction model

### Expected effect

- cleaner rows
- more room for sender/subject/classification display
- stronger emphasis on the message itself

## 2. Add Classification Pill

### Change

Add a pill near the front of each message row showing:

- suggested category
- confidence percentage

### Example labels

- `Keep 99%`
- `Bulk 76%`
- `Junk 91%`
- `Trash 84%`
- `Review 62%`

### Why

- the pill is the clearest compact summary of what Fynish thinks
- confidence gives users a quick read on when to trust the suggestion versus inspect more closely

## 3. Add Soft Row Tint by Suggested Category

### Change

Give each queue row/card a very light background tint based on the suggested category.

### Why

- makes the queue visually scannable
- helps the eye group similar messages quickly
- reinforces the pill without requiring users to read every label

### Design constraint

The row tint must be subtle.

It should:

- support scanning
- preserve readability
- avoid making the queue feel loud or chaotic

It should not:

- overpower the text
- create accessibility contrast issues
- make low-stakes categories feel visually alarming

## Recommended Color Direction

Use restrained semantic colors.

### Keep

- pill: muted green
- row tint: very pale green

### Bulk Mail

- pill: warm amber / gold
- row tint: very pale amber

### Junk Review

- pill: dusty orange
- row tint: very pale orange

### Trash

- pill: muted brick / red
- row tint: very pale rose

### Needs Review

- pill: slate / blue-gray
- row tint: very pale cool gray-blue

## Visual Treatment Rules

### Pill

- higher contrast than the row tint
- readable on both desktop and laptop screens
- compact but prominent

### Row tint

- low saturation
- low opacity feel
- should still look clean beside white panels and soft Fynish backgrounds

### Text

- sender and subject remain the primary content
- pill supports, not replaces, readable text hierarchy

## Information Hierarchy

Recommended row hierarchy:

1. classification pill
2. sender
3. subject
4. supporting metadata such as received date / account
5. expanded content / actions below when opened

This keeps the “what does Fynish think?” signal close to the front of the row.

## Confidence Display Rules

Show confidence as a rounded percentage.

Recommendation:

- whole-number percent
- derived from existing confidence score

Examples:

- `0.99` -> `99%`
- `0.76` -> `76%`

Do not overcomplicate this first version with:

- bands
- confidence bars
- warning icons

The pill text should be enough.

## Interaction Model

This change should not alter the user’s actual message action flow.

### Keep the existing per-message actions

- Keep
- Bulk Mail
- Junk
- Trash
- Teach Fynish
- expanded preview behavior

The visual redesign should improve queue comprehension without forcing users to learn a new action model at the same time.

## Mobile / Narrow Width Behavior

The pill must remain visible on narrower screens.

Recommendations:

- avoid overly long category labels in the pill
- allow sender/subject truncation before hiding the pill
- keep the tint effect intact even when the row wraps

Preferred short labels for pills:

- `Keep`
- `Bulk`
- `Junk`
- `Trash`
- `Review`

## Accessibility Considerations

### Requirements

- color cannot be the only signal
- pill text must remain explicit
- row tint must preserve readable contrast
- category meaning must still be understandable in grayscale / low-color conditions

### Implication

The pill text is mandatory.
The tint is supplementary.

## Implementation Plan

### Phase 1: Queue Row Styling

1. remove checkbox rendering from queue rows
2. add category-to-style mapping
3. add pill component styling
4. add row tint styling
5. update spacing/layout so the row still feels balanced

### Phase 2: Confidence Formatting

1. expose rounded confidence text where needed
2. place confidence inside the pill
3. validate edge cases like missing or very low confidence values

### Phase 3: Final Fit and Finish

1. test desktop layout
2. test laptop/narrow browser layout
3. test hosted app visually with mixed queue categories
4. tune colors and padding if the first pass feels too loud or too flat

## Suggested Technical Approach

### Frontend areas likely involved

- Review Queue row rendering in `frontend/src/App.tsx`
- queue row / pill styles in `frontend/src/App.css`

### Likely additions

- helper for confidence percent formatting
- helper for category style class naming
- CSS variables for each queue category color family

### Recommended CSS pattern

Use explicit category classes such as:

- `queue-row-keep`
- `queue-row-bulk-mail`
- `queue-row-junk-review`
- `queue-row-trash`
- `queue-row-needs-review`

and matching pill classes such as:

- `queue-pill-keep`
- `queue-pill-bulk-mail`
- `queue-pill-junk-review`
- `queue-pill-trash`
- `queue-pill-needs-review`

This keeps styling predictable and easy to tune later.

## Validation Plan

### Functional validation

- queue still loads correctly
- per-message actions still work
- teach-rule flow still works
- expand/collapse behavior still works

### Visual validation

- each category has distinct but subtle tinting
- pill is always readable
- no layout break on narrow width
- queue feels calmer and easier to scan than before

### User-level validation

Questions to answer after implementation:

- can the user tell category suggestions faster?
- does the queue feel cleaner after checkbox removal?
- are any colors too strong or too similar?

## Success Criteria

This UI refinement is successful when:

- the queue no longer looks like a bulk-selection tool
- the suggested category is obvious at a glance
- confidence is easy to read without opening the message
- the queue becomes easier to scan visually
- the design feels more intentional without becoming visually noisy

## Recommendation

Proceed with this as a focused queue-only UI update.

Do not combine it with deeper workflow changes in the same pass.

The best version of this change is:

- visually clearer
- interaction-stable
- subtle enough to preserve calm
- strong enough to make Fynish’s suggestion feel immediately legible
