# Account Authorization and Monitored Email Use Cases

Status: draft for pre-publication review.

This note captures the account authorization cases we want to revisit before publishing the project to GitHub and writing the Medium article.

## Terminology

- **Fynish sign-in account**: the Google account used to log in to Fynish.
- **Monitored Gmail account**: a Gmail mailbox that Fynish reads, classifies, and optionally writes Gmail labels to.
- **Same-account setup**: the Fynish sign-in account and monitored Gmail account are the same email address.
- **Different-account setup**: the Fynish sign-in account owns or controls a different monitored Gmail account.

## Core Use Cases

1. New Fynish user signs in and adds their own Gmail account.
   - Example: sign-in `user.com`, monitored account `user.com`.
   - Expected behavior: allowed when Google OAuth succeeds.

2. New Fynish user signs in and adds a different Gmail account they control.
   - Example: sign-in `secondary.user@example.com`, monitored account `monitored.friend@example.com`.
   - Expected behavior: allowed when Google OAuth succeeds for the monitored account.

3. Existing monitored account needs OAuth refresh.
   - Account exists and is enabled, but the stored token is expired or revoked.
   - Expected behavior: user clicks account-level `Reconnect Gmail`, completes Google OAuth, and Fynish replaces the stored token.

4. Disabled monitored account needs to be re-enabled.
   - Account exists with `enabled=false`.
   - Expected behavior: user can click `Enable Account`; account becomes enabled and remains visible.
   - If the OAuth token is stale, user also clicks `Reconnect Gmail`.

5. User disables a monitored account.
   - Expected behavior: account remains visible to its owning Fynish user, stops sync/processing, and can be re-enabled.
   - Other users cannot enable or disable it.

6. User adds multiple Gmail mailboxes.
   - One Fynish sign-in account owns several monitored Gmail accounts.
   - Expected behavior: all owned accounts appear in Accounts, Review Queue, Rules, and Processed Mail for that Fynish user only.

7. User tries to add a Gmail mailbox already connected to another Fynish user.
   - Expected behavior: blocked with a clear conflict message.

8. User signs in with a different Fynish login.
   - Example: `primary.user@example.com` versus `secondary.user@example.com`.
   - Expected behavior: account lists, queues, rules, processed mail, and settings are isolated by signed-in user.

9. User guesses another user's resource IDs.
   - Examples: disable account, enable account, recover message, edit/delete rule, or process message by direct API call.
   - Expected behavior: return not found or unauthorized without mutating another user's resources.

10. User reconnects the wrong Google mailbox from an account tile.
    - Example: clicks `Reconnect Gmail` for `monitored.friend@example.com`, but Google OAuth completes as `secondary.user@example.com`.
    - Recommended behavior: strict reconnect should reject the callback because the returned OAuth email does not match the intended account.

11. User clicks top-level `Add Gmail Account` and chooses an already connected account they own.
    - Expected behavior: either refresh/update the existing token and enable the account, or show a clear already-connected message.
    - Recommended behavior: treat this as same-user reconnect/update.

12. User clicks top-level `Add Gmail Account` and chooses a Gmail account owned by another Fynish user.
    - Expected behavior: block.

13. User logs out and another approved tester logs in on the same browser.
    - Expected behavior: no frontend state leaks from the previous signed-in user after reload.

14. Fynish sign-in account is approved, but monitored Gmail account is not separately approved.
    - Current policy question: should a signed-in approved tester be allowed to monitor any Gmail account they can OAuth, or should monitored Gmail accounts also require allowlist approval?

15. Token is revoked at Google while the account remains enabled.
    - Expected behavior: sync fails for that account with a clear reconnect message, and other accounts continue to sync.

16. Token refresh fails during scheduled sync.
    - Expected behavior: failure is isolated to the affected account, logged clearly, and does not block other enabled accounts.

17. Read-only versus modify-capable Gmail scopes.
    - Current hosted product path expects modify-capable Gmail.
    - Expected behavior: normal hosted UI requests modify scope. Existing read-only accounts should show limited capability or be prompted to reconnect with modify scope.

18. Removing a monitored account entirely.
    - Current behavior: disable exists; delete/remove does not appear to be a normal product action.
    - Policy question: is disable enough for V1, or do users need permanent removal?

19. Multiple Fynish users share the same monitored Gmail mailbox.
    - Current likely behavior: blocked because one monitored Gmail account belongs to one Fynish user.
    - Policy question: keep single ownership for V1, or design shared ownership later?

20. Legacy account rows and new `mail_accounts` rows coexist.
    - Expected behavior: account identity and authorization resolve through the owning `mail_accounts.user_id`, with legacy rows treated as compatibility data only.

## Known or Likely Gaps

- Account-level reconnect should carry an intended monitored email through OAuth state and reject callbacks for a different Gmail account.
- Top-level `Add Gmail Account` can remain flexible, but account-level `Reconnect Gmail` should be strict.
- The monitored Gmail allowlist policy is not yet explicit.
- There may not be automated coverage for same-user reconnect replacing an existing token.
- There may not be automated coverage for wrong-email reconnect rejection.
- Scheduled sync failures are clearer now, but persistent account-level UI status may still be needed.
- Legacy global account structures should be reviewed before public release.

## Pre-Publication Review Checklist

- [ ] Confirm the product policy for monitored Gmail allowlisting.
- [ ] Confirm whether shared monitored Gmail ownership is out of scope for V1.
- [ ] Confirm whether account removal is needed, or disable/re-enable is enough.
- [ ] Add strict account-level reconnect validation.
- [ ] Add tests for same-user reconnect token replacement.
- [ ] Add tests for wrong-email reconnect rejection.
- [ ] Add tests for add-account conflict with another Fynish user.
- [ ] Verify scheduled sync isolates failures per account.
- [ ] Review docs and Medium article language so sign-in account versus monitored account is clear.
