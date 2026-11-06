# Normalized swap storage foundation

The source-scoped immutable identity consists of source, signature, instruction
path and swap index. Repeated identical writes preserve first ingestion time;
conflicting payloads raise an error. Point-in-time reads require both known_at
and server-assigned ingested_at at or before cutoff. Reads reject overflow.

This module is not wired into bootstrap, providers or candidate scores. Full raw
evidence hashes, parser/batch provenance, completeness and funding history remain
required before operational integration. Tests use TEST_DATABASE_URL only and
clean up uniquely scoped fixture rows. CI supplies temporary PostgreSQL.
