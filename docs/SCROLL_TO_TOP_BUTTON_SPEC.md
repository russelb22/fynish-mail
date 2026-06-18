# Scroll To Top Button Spec

Status: Implemented locally on 2026-06-05. Deployment pending.

## Purpose

Add a small floating up-arrow button that appears after the user scrolls down long Fynish pages.

Clicking the button should immediately return the user to the top of the current page, making long review sessions easier on Processed Mail, Rules, and likely Review Queue.

## Product Recommendation

Implement the button on:

- Processed Mail
- Rules
- Review Queue

Processed Mail and Rules are the clear first targets because they can become long, scan-heavy pages. Review Queue should also receive it because staged review can involve long account/message groups, and the masthead/staged controls are useful to return to quickly.

Do not add it to Accounts or Settings in the first pass unless testing shows those pages commonly become long enough to need it.

## Visual Direction

The control should resemble the small circular arrow affordance in Codex/ChatGPT:

- circular button
- subtle border
- white or translucent white background
- soft shadow
- single up-arrow icon
- compact size, around `42px` to `48px`
- no visible text label

Recommended placement:

- fixed near the lower center of the viewport
- above the bottom edge enough to avoid browser/mobile safe areas
- `bottom: 24px`
- `left: 50%`
- `transform: translateX(-50%)`
- high enough `z-index` to float above page content

Why lower center instead of near the page top:

- when the user is scrolled down, a top-positioned control may not be visible
- lower center matches the referenced Codex/ChatGPT affordance
- it avoids competing with page headers, nav tabs, and action buttons

## Behavior

The button should:

- appear only after the user has scrolled down meaningfully
- hide near the top of the page
- jump immediately to the top when clicked
- remain independent of backend state
- not trigger data reloads
- not clear staged Review Queue actions
- not alter the active view

Recommended threshold:

- show when `window.scrollY >= 360`
- hide when `window.scrollY < 240`

Using separate show/hide thresholds prevents flicker around the boundary.

Recommended scroll target:

```ts
window.scrollTo({ top: 0, behavior: 'auto' })
```

## Accessibility

The button should include:

- `type="button"`
- `aria-label="Scroll to top"`
- keyboard focus styles
- enough contrast for the arrow and border
- no keyboard shortcut in V1

The icon can be:

- a simple `↑` glyph if no icon library is currently used
- `ArrowUp` from an existing icon library if one already exists in the frontend

Do not add a new icon dependency solely for this button.

## Responsive Behavior

Desktop:

- bottom-center floating button
- do not overlap staged Review Queue commit controls when possible

Mobile:

- keep bottom-center placement
- use safe-area padding:

```css
bottom: calc(18px + env(safe-area-inset-bottom));
```

If the button overlaps an important mobile action surface during testing, move it slightly right:

```css
left: auto;
right: 18px;
transform: none;
```

## Implementation Plan

### Slice 1: Shared Frontend Control

Files likely touched:

- `frontend/src/App.tsx`
- `frontend/src/App.css`

Add shared state:

- `showScrollTopButton`

Add a scroll listener:

- passive listener on `window`
- clean up on unmount
- throttle is optional for V1 because the state only changes at threshold crossings

Show the button when:

- current view is `queue`, `processed`, or `rules`
- scroll position is below the threshold

Hide the button when:

- current view is `accounts` or `settings`
- scroll position is above the threshold
- app is loading the first view, if needed to avoid visual flash

Good enough to advance:

- button appears after scrolling down on Processed Mail
- button disappears after returning to top
- click jumps to top
- navigation between views does not leave stale visibility state

### Slice 2: Visual Polish And Page Coverage

Polish:

- circular shape
- subtle border/shadow
- hover/focus states
- pressed state
- mobile safe-area placement

Verify on:

- Processed Mail
- Rules
- Review Queue with staged controls visible

Good enough to ship:

- button does not cover primary action controls
- text/buttons underneath remain readable
- focus ring is visible
- no layout shift when the button appears or disappears

## Acceptance Criteria

- On Processed Mail, scrolling down reveals the up-arrow button.
- Clicking the button immediately jumps back to the masthead/top navigation.
- On Rules, scrolling down reveals the same button and behavior.
- On Review Queue, scrolling down reveals the same button and behavior.
- On Accounts and Settings, the button does not appear in V1.
- The button is keyboard focusable and screen-reader labeled.
- The button does not affect queued messages, staged actions, rules, or backend data.

## Implementation Notes

Implemented as a frontend-only shared floating control in `frontend/src/App.tsx` and `frontend/src/App.css`.

Current behavior:

- appears on Review Queue, Processed Mail, and Rules
- remains hidden on Accounts and Settings
- shows after scrolling below `360px`
- hides after returning above `240px`
- uses `window.scrollTo({ top: 0, behavior: 'auto' })`
- uses a centered circular button with `aria-label="Scroll to top"`

## Test Plan

Manual:

- open Processed Mail with enough rows to scroll
- scroll down past the threshold
- confirm button appears
- click button
- confirm page returns to top and button hides
- repeat on Rules
- repeat on Review Queue
- confirm no button on Accounts and Settings

Automated:

- add a lightweight Playwright smoke test if the existing e2e setup already has a long Processed Mail fixture
- otherwise defer automation until the next frontend interaction test pass

Suggested Playwright assertions:

- scroll to `window.scrollY = 500`
- expect button with label `Scroll to top` to be visible
- click it
- wait for `window.scrollY` to return near `0`

## Non-Goals

Do not include in V1:

- per-page persistent scroll restoration
- keyboard shortcuts
- "scroll to bottom"
- remembering prior scroll position per tab
- backend changes
- database changes

## Open Question

If Review Queue staged controls and the floating button ever overlap on mobile, should the button move to the lower-right corner only for that view?

Recommendation: start bottom-center everywhere, then adjust only if testing shows overlap.
