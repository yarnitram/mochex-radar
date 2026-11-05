# Spec 013 — Collector data-quality notices

With `ALERT_DATA_QUALITY_ENABLED=true`, a completed MEXC collector cycle with at
least one provider failure queues a typed DATA_QUALITY notice after candle/cycle
storage commits. The notice preserves failure count, number of collection targets,
newly inserted row count, cycle timestamps, rule version and one-hour expiry.
Zero newly inserted rows alone is not a failure: normal repeated candles deduplicate.

Queue enablement is independent of Telegram sending, which stays disabled by
default. Existing outbox deduplication and 30-minute cooldown apply. Queue failure
logs only a sanitized error class and does not undo the committed collection.
Queue initialization failure requires operator correction/restart; no claim is
made that every failure produces an alert when the queue itself is unavailable.

Default flag is false. Enabling it only produces operational evidence; no Pump or
Dump notice, automatic trade, or Telegram transport is invoked by the collector.
The separate sender's opt-in and credentials are still required for delivery.

Acceptance: healthy/duplicate cycles create no warning; failed cycle evidence and
expiry are preserved; queue cooldown and DB failure are distinct outcomes; the
collector flag controls invocation. Full database outbox behavior is verified by
the preceding phase's PostgreSQL integration tests.
