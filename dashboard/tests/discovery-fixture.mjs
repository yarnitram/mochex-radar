export const source = "dexscreener:token-profiles-latest-v1";
export const instant = "2026-01-01T12:00:00Z";
export const catalog = {
  status: "current_catalog",
  coverage: "profile_window_only",
  category: "unclassified",
  security_status: "UNKNOWN",
  approved_pump_watch: false,
  mints: ["A", "B"].map((char, index) => ({
    mint: char.repeat(32),
    source,
    first_known_at: instant,
    last_known_at: instant,
    first_ingested_at: instant,
    last_scan_at: index === 0 ? null : instant,
  })),
};
export const polls = {
  status: "stored_polls",
  coverage: "profile_window_only",
  polls: [
    {
      id: "00000000-0000-4000-8000-000000000001",
      source,
      started_at: instant,
      finished_at: instant,
      status: "success",
      response_hash: "a".repeat(64),
      input_count: 0,
      discovered_count: 0,
      ingested_at: instant,
    },
    {
      id: "00000000-0000-4000-8000-000000000002",
      source,
      started_at: instant,
      finished_at: instant,
      status: "provider_error",
      response_hash: null,
      input_count: null,
      discovered_count: null,
      ingested_at: instant,
    },
  ],
};
