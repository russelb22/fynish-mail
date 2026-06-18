# AI Digest Summary Feature Spec

## Purpose

This document defines a proposed Fynish feature:

- use an LLM to summarize the user's daily processed-mail activity
- add a short narrative briefing to the existing daily digest
- help the user understand patterns, risk, and context without reading every processed row

The feature should make Fynish feel less like a log viewer and more like a trusted inbox assistant.

## Product Goal

The AI digest summary should answer:

- what happened in my inbox today?
- what did Fynish do automatically?
- were any auto-cleaned messages notable?
- were there clusters of similar mail from the same domain or organization?
- is anything worth my attention even if the queue is mostly handled?

The tone should be:

- concise
- calm
- transparent
- factual
- non-alarmist
- careful about uncertainty

The summary should not pretend to know facts that are not present in the digest input.

## Recommendation Summary

Recommended rollout:

1. implement an optional OpenAI-backed summary first
2. use structured digest data, not full raw mailbox exports
3. request structured JSON output from the model
4. render the AI section above the existing Processed Mail table
5. keep the existing digest usable if AI generation fails
6. keep the summarizer behind a per-user setting until trust is established
7. enable first for Russel only, then expand after reviewing live examples

OpenAI API access is the recommended first provider. Local LLM support should be treated as a future provider option behind the same summarizer interface.

## Why This Fits Fynish

Fynish already has:

- classification results
- action logs
- action source stamps
- rule application
- high-confidence auto-cleaning
- top sender-domain summaries
- daily digest delivery

Those pieces are useful individually, but an LLM can connect them into a readable explanation.

Example value:

- "Most of today's auto-cleaned messages were promotional finance newsletters."
- "Several kept messages were school or account-security related."
- "No auto-cleaned messages looked personal based on sender and subject."
- "Three domains produced most of today's noise."

This can increase trust in automation because users can see both the mechanical facts and a higher-level interpretation.

## User Experience

### V1 user story

As a Fynish user, I receive a daily digest with a short AI-generated briefing that tells me what Fynish noticed in my processed mail, so I can understand the day's inbox activity quickly.

### Placement

The AI summary should appear near the top of the HTML digest, after the numeric summary cards and before the Processed Mail table.

Recommended section title:

- `Today's inbox briefing`

Recommended subsections:

- `Summary`
- `Worth noticing`
- `Auto-clean review`
- `Top noise sources`

The section should be omitted if:

- the user has not enabled AI summaries
- the OpenAI API key is not configured
- the model request fails
- there is too little digest activity to summarize

In those cases, the normal digest should still send.

### Domain Attention Notes

Users can configure domain-specific attention notes for the AI digest summary.

These notes are digest-interpretation preferences only. They help the model decide whether recurring mail from a known domain appears routine or worth mentioning in the briefing.

Examples:

- `example.net`: routine low-battery, status, and bypass notices should usually stay routine; more severe alarm/security conditions may deserve attention.
- `truecoach.co`: routine workout assignments and reminders should usually stay routine; likely direct coach/client communication may deserve attention.

Attention notes must not:

- change Review Queue classification
- create or update rules
- trigger auto-cleaning
- execute Gmail label changes
- persist model judgments per message

## V1 Content

### Summary

A short paragraph, 1-3 sentences.

Example:

> Fynish processed 74 messages today, mostly newsletters and promotional mail. No auto-cleaned messages stood out as personal based on sender, subject, and snippet. School and account-security messages were kept.

### Key Takeaways

Recommended max:

- 3-5 bullets

Each bullet should be short and grounded in the input.

Examples:

- `Finance newsletters were the largest junk cluster.`
- `School-related notices were kept.`
- `Amazon/order notifications were kept rather than auto-cleaned.`

### Auto-Clean Review

This subsection should focus specifically on messages with:

- `action_source = high_confidence_auto_clean`

If none exist, say nothing or render a quiet line such as:

- `No messages were auto-cleaned in this digest window.`

If auto-cleaned messages exist, summarize:

- count
- dominant sender domains
- whether any subjects look potentially personal or important
- whether the user may want to review the Processed Mail table

The model must not mark an item safe or unsafe with certainty. It should use language like:

- `appears to be`
- `looks like`
- `based on subject and sender`

### Notable Kept Messages

This section should identify messages that may be useful to the user because they were kept, not because the model is taking action.

Examples:

- school notices
- security alerts
- receipts or delivery updates
- personal-looking messages

### Top Noise Sources

This section should summarize repeated sender domains.

It should complement the existing top-domain table rather than replace it.

Example:

- `tradivore.com and premiumretiring.com accounted for much of the promotional finance mail.`

## Input Scope

V1 should send the model only the minimum useful digest data:

- digest window
- processed count
- counts by action
- counts by action source
- top sender domains
- up to 50 processed message rows
- account email
- sender display string
- sender domain
- subject
- short snippet or body preview, if already available in Fynish
- selected action
- action source
- processed timestamp
- matching domain attention notes, when a processed message sender domain exactly matches a configured note

Domain attention notes should include:

- domain
- label
- note text
- matched message count
- up to 3 sample subjects

V1 should not send:

- full email bodies by default
- attachments
- Gmail thread history
- OAuth tokens or provider metadata
- internal database IDs unless needed for debugging
- user secrets

## Privacy Posture

Recommended V1 privacy stance:

- opt-in per user
- disclose that digest metadata/snippets may be sent to OpenAI when enabled
- include subjects and snippets/body previews in V1
- do not include full bodies by default
- truncate long snippets
- cap the number of messages included
- do not store the raw prompt by default
- do not store generated AI summaries in V1; generate them only for the email being sent

OpenAI's current API documentation states that API data is not used to train OpenAI models by default unless the customer opts in, and that API abuse-monitoring logs may be retained for a limited period by default. See:

- [OpenAI API data controls](https://platform.openai.com/docs/guides/your-data)
- [OpenAI enterprise privacy](https://openai.com/policies/api-data-usage-policies/)

This does not remove the need for Fynish to treat email-derived content carefully.

## Provider Recommendation

### Recommended V1 provider

Use OpenAI API.

Reasons:

- best quality for summarization
- no local model hosting burden
- simpler VM operations
- lower implementation risk
- supports structured outputs for predictable rendering
- easier to improve prompt behavior quickly

The OpenAI docs recommend the Responses API for new text generation applications, and Structured Outputs can enforce a JSON schema for model responses. See:

- [OpenAI text generation guide](https://platform.openai.com/docs/guides/text?api-mode=responsesPer)
- [OpenAI Responses API reference](https://platform.openai.com/docs/api-reference/responses?lang=curl)
- [OpenAI Structured Outputs guide](https://platform.openai.com/docs/guides/structured-outputs?api-mode=responses)

### Future provider

Add a local LLM provider later only if one of these becomes important:

- strong privacy requirement
- recurring API cost becomes material
- Fynish is deployed in an environment with enough local compute
- users want offline operation

The implementation should still use a provider abstraction so local LLM support does not require redesigning the digest service later.

## Non-Goals for V1

V1 should not:

- let the AI modify mail
- let the AI create or edit rules
- ask the AI to classify messages instead of the existing classifier
- send full mailbox contents to the model
- add chat inside the digest email
- add per-message AI explanations for every row
- block digest delivery if the model request fails

## Trust and Safety Requirements

The AI section must be advisory only.

It should never say:

- `This is definitely safe`
- `This was correctly deleted`
- `You do not need to review this`

Preferred wording:

- `Based on sender and subject, this appears promotional.`
- `This may be worth reviewing if you were expecting it.`
- `No obvious personal messages appeared in the auto-cleaned set.`

The digest should preserve the existing recovery path:

- link to Processed Mail
- show auto-cleaned messages clearly
- keep action/source badges visible

## Success Criteria

The feature is successful if:

- the digest is faster to understand
- the AI summary is short and useful
- auto-cleaned activity is easier to audit
- failures fall back to the normal digest
- users can enable or disable AI summaries per account
- no sensitive unnecessary data is sent to the model

## Open Questions

Resolved V1 decisions:

1. Include snippets/body previews in the AI input.
2. Generate AI summaries only for the email being sent; do not store summaries in the database for V1.
3. Enable for Russel only at first. Kim should remain on the normal digest until the feature has been reviewed.
4. Use `AI digest summary` as the user-facing setting label.

Remaining open questions:

1. None for V1.

Final V1 decisions:

- default model: `gpt-5-mini`
- manual review digests should include AI summaries when the user setting is enabled
- model choice remains an operator env var, not a user-facing UI setting
- AI summaries are rendered in both HTML and plain-text digest output
