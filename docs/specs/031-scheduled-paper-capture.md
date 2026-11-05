# Spec 031 — Opt-in stored-snapshot paper worker

Poll one existing predeclared paper plan, never create a campaign automatically.
Use the existing bounded repeatable-read read-only PostgreSQL loader, preserving
retrieval times. Optional open-time upper bound limits old outcome snapshots while
the retrieval/close cutoff stays at actual cycle time. No provider call or DB write.

Prioritize captures still inside their grace window, then completed-candle outcomes
for existing captures. Bound each cycle to five actions. Recheck the real clock
after loading and preserve missed/unavailable/incomplete slots. Existing records
are exclusive and never overwritten; concurrent shared-filesystem duplicate writes
are skipped. One configured worker/plan and shared persistent journal directory are
required; unrelated filesystem copies do not constitute one journal.

Provider/storage failures are sanitized and retried only on later cycles; never
make up captures, rewrite timestamps, enable alerts, or emit trading orders. Source
mismatch/corrupt journal fails closed. CLI supports --once and 1..30-second polling;
optional Compose paper profile stays disabled without explicit plan configuration.

Acceptance: due capture before outcomes, future and missed slots not loaded,
separate later outcome, late query crosses grace safely, retry on DB failure,
concurrent duplicate behavior, bounded cycles and actual PostgreSQL range cutoff.
