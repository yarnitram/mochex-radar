const source = "solana-public-mainnet:getAccountInfo:finalized";
const program = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const token2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";
const base = {
  source,
  parser_version: "spl-mint-authorities-v1",
  security_status: "UNKNOWN",
  approved_pump_watch: false,
  response_hash: "a".repeat(64),
  owner: program,
  slot: 123456,
  reason: "partial_authority_evidence",
  mint_authority_status: "DISABLED",
  freeze_authority_status: "DISABLED",
  mint_authority: null,
  freeze_authority: null,
};
export const authorities = {
  status: "stored_partial_evidence",
  as_of: "2026-01-01T12:05:00Z",
  security_status: "UNKNOWN",
  approved_pump_watch: false,
  observations: [
    {
      evidence: {
        ...base,
        mint: "1".repeat(32),
        known_at: "2026-01-01T12:00:00Z",
      },
      ingested_at: "2026-01-01T12:01:00Z",
      expires_at: "2026-01-01T12:15:00Z",
      freshness: "current",
    },
    {
      evidence: {
        ...base,
        mint: "1".repeat(31) + "2",
        known_at: "2026-01-01T11:00:00Z",
        mint_authority_status: "PRESENT",
        mint_authority: program,
      },
      ingested_at: "2026-01-01T11:01:00Z",
      expires_at: "2026-01-01T11:15:00Z",
      freshness: "stale",
    },
    {
      evidence: {
        ...base,
        mint: "1".repeat(31) + "3",
        known_at: "2026-01-01T12:00:00Z",
        owner: token2022,
        reason: "token_2022_extensions_not_evaluated",
        mint_authority_status: "UNKNOWN",
        freeze_authority_status: "UNKNOWN",
      },
      ingested_at: "2026-01-01T12:01:00Z",
      expires_at: "2026-01-01T12:15:00Z",
      freshness: "current",
    },
  ],
};
