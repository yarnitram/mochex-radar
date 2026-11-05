# Spec 009 — Durable provider request budget

When DEX lookup and DATABASE_URL are configured, reserve a provider request in
PostgreSQL before HTTP transport. A shared provider row uses a transaction lock
to enforce UTC-day counts and a 250ms gap between request reservations across
processes. Database time determines rollover. Polling waits outside the transaction.
Failed or cancelled requests consume their reservation; database failure prevents
the provider call. Invalid mints never reserve. Process ceiling still applies.

`DEX_LOOKUP_DAILY_REQUESTS` defaults to 100. All workers must use the same limit.
Changes to this operator setting take effect on restart; raising it permits more
requests within that day. A restart alone does not reset the stored usage.
Without a database, manual lookup retains its explicitly limited process budget;
unattended workers must require a database. This is a request count, not a monetary
credit estimate or full provider cost ledger. Row coordination covers this app's
token-pairs endpoint; it cannot coordinate unrelated external clients.

Acceptance: concurrent connections cannot exceed the daily ceiling, exhaustion
survives reconnection, UTC day rolls over, and DB failures block transport.
