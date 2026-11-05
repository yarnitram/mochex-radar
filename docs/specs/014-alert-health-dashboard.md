# Spec 014 — Alert delivery health visibility

## Scope

Expose the existing count-only operational outbox status in the Next dashboard.
No new backend endpoint, secret configuration, market signal, or delivery action.
The server aggregator reads `/api/v1/alerts/status` alongside other fixed paths,
with the existing independent timeout, no-cache behavior and schema validation.

## Display contract

- Display all retained stored counts for pending, processing (labeled Claimed),
  sent, failed, uncertain and expired. These are record states, not daily metrics.
- Missing state keys default to zero only for an available configured outbox.
  Disabled, loading or unavailable storage displays em dashes, never healthy zeroes.
- Uncertain notices show a review explanation and no resend control.
- Browser refresh failure retains prior counts under an explicit outdated badge.
- Alert-service failure does not hide core observations or other available sections.
- Stored states do not verify worker liveness, bot configuration or destination access.
- No message body, bot token, chat ID, destination detail or raw provider response
  is exposed. Server runtime schema strips unknown root fields and rejects invalid
  count types, negatives, fractional values and unknown delivery-state keys.

## Acceptance

Runtime contract tests verify defaults, stripping unrelated fields and malformed
counts. Browser tests verify uncertain review, no action controls, failed refresh
retention, disabled/unavailable states and independence from core observations.
Mobile layout stays inside the viewport. Production build/typecheck and the
existing backend/PostgreSQL CI gate must pass before merge.
