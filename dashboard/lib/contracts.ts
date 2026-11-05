import { z } from "zod";

export const coreSchema = z.object({
  data_status: z.string(),
  as_of: z.string(),
  interval: z.literal("15m"),
  markets: z.array(
    z.object({
      asset_id: z.string(),
      base: z.string(),
      quote: z.string(),
      market_id: z.string(),
      status: z.enum(["current", "stale", "missing"]),
      close: z.string().nullable(),
      candle_return: z.string().nullable(),
      close_time: z.string().nullable(),
      retrieved_at: z.string().nullable(),
    }),
  ),
});
export const btcSchema = z.object({
  state: z.enum(["unknown", "neutral", "supportive", "caution", "blocked"]),
  reason: z.string(),
  rule_version: z.string(),
  provisional: z.boolean(),
  return_1h: z.string().nullable(),
  data_as_of: z.string().nullable(),
  input_open_times: z.array(z.string()),
});
export const collectorSchema = z.object({
  status: z.string(),
  last_cycle: z
    .object({
      finished_at: z.string(),
      stored_count: z.number(),
      provider_failures: z.number(),
    })
    .nullable(),
});
export const scansSchema = z.object({
  status: z.string(),
  scans: z.array(
    z.object({
      id: z.string(),
      mint: z.string(),
      categories: z.array(z.string()),
      category_source: z.string(),
      finished_at: z.string(),
      status: z.enum([
        "success",
        "empty",
        "provider_error",
        "budget_exhausted",
        "skipped_budget",
      ]),
      pool_count: z.number(),
    }),
  ),
});
export type Service<T> =
  | { status: "available"; data: T }
  | { status: "unavailable"; data: null };
const count = z.number().int().nonnegative().default(0);
export const outboxSchema = z.object({
  status: z.enum(["storage_disabled", "stored_outbox"]),
  states: z
    .object({
      pending: count,
      processing: count,
      sent: count,
      failed: count,
      uncertain: count,
      expired: count,
    })
    .strict(),
});
const timestamp = z.string().datetime({ offset: true });
const profileSource = z.literal("dexscreener:token-profiles-latest-v1");
export const catalogSchema = z.discriminatedUnion("status", [
  z.object({
    status: z.literal("storage_disabled"),
    mints: z.array(z.never()),
  }),
  z.object({
    status: z.literal("current_catalog"),
    coverage: z.literal("profile_window_only"),
    category: z.literal("unclassified"),
    security_status: z.literal("UNKNOWN"),
    approved_pump_watch: z.literal(false),
    mints: z
      .array(
        z.object({
          mint: z.string().regex(/^[1-9A-HJ-NP-Za-km-z]{32,44}$/),
          source: profileSource,
          first_known_at: timestamp,
          last_known_at: timestamp,
          first_ingested_at: timestamp,
          last_scan_at: timestamp.nullable(),
        }),
      )
      .max(100),
  }),
]);
export const profilePollsSchema = z.discriminatedUnion("status", [
  z.object({
    status: z.literal("storage_disabled"),
    polls: z.array(z.never()),
  }),
  z.object({
    status: z.literal("stored_polls"),
    coverage: z.literal("profile_window_only"),
    polls: z
      .array(
        z
          .object({
            id: z.string().uuid(),
            source: profileSource,
            started_at: timestamp,
            finished_at: timestamp,
            status: z.enum(["success", "provider_error", "budget_exhausted"]),
            response_hash: z
              .string()
              .regex(/^[a-f0-9]{64}$/)
              .nullable(),
            input_count: z.number().int().nonnegative().nullable(),
            discovered_count: z.number().int().nonnegative().nullable(),
            ingested_at: timestamp,
          })
          .superRefine((poll, ctx) => {
            const values = [
              poll.response_hash,
              poll.input_count,
              poll.discovered_count,
            ];
            if (
              poll.status === "success"
                ? values.some((value) => value === null)
                : values.some((value) => value !== null)
            ) {
              ctx.addIssue({
                code: "custom",
                message: "poll counts and response hash must match outcome",
              });
            }
            if (
              poll.input_count !== null &&
              poll.discovered_count !== null &&
              poll.discovered_count > poll.input_count
            ) {
              ctx.addIssue({
                code: "custom",
                message: "discovered count exceeds input count",
              });
            }
          }),
      )
      .max(10),
  }),
]);
export type Snapshot = {
  fetched_at: string;
  core: Service<z.infer<typeof coreSchema>>;
  btc: Service<z.infer<typeof btcSchema>>;
  collector: Service<z.infer<typeof collectorSchema>>;
  scans: Service<z.infer<typeof scansSchema>>;
  outbox: Service<z.infer<typeof outboxSchema>>;
  catalog: Service<z.infer<typeof catalogSchema>>;
  profilePolls: Service<z.infer<typeof profilePollsSchema>>;
  authorities: Service<z.infer<typeof authoritiesSchema>>;
};

const key = z.string().regex(/^[1-9A-HJ-NP-Za-km-z]{32,44}$/);
const authorityState = z.enum(["PRESENT", "DISABLED", "UNKNOWN"]);
const authorityEvidence = z
  .object({
    mint: key,
    known_at: timestamp,
    slot: z.number().int().nonnegative(),
    owner: key.nullable(),
    reason: z.enum([
      "account_missing",
      "token_2022_extensions_not_evaluated",
      "unsupported_owner",
      "executable_account",
      "unsupported_mint_layout",
      "uninitialized_or_invalid_mint",
      "invalid_authority_layout",
      "partial_authority_evidence",
    ]),
    response_hash: z.string().regex(/^[a-f0-9]{64}$/),
    mint_authority_status: authorityState,
    freeze_authority_status: authorityState,
    mint_authority: key.nullable(),
    freeze_authority: key.nullable(),
    source: z.literal("solana-public-mainnet:getAccountInfo:finalized"),
    parser_version: z.literal("spl-mint-authorities-v1"),
    security_status: z.literal("UNKNOWN"),
    approved_pump_watch: z.literal(false),
  })
  .superRefine((e, ctx) => {
    for (const [state, address] of [
      [e.mint_authority_status, e.mint_authority],
      [e.freeze_authority_status, e.freeze_authority],
    ]) {
      if ((state === "PRESENT") !== (address !== null))
        ctx.addIssue({
          code: "custom",
          message: "authority address must match presence",
        });
    }
    if (e.reason === "partial_authority_evidence") {
      if (
        e.owner !== "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA" ||
        e.mint_authority_status === "UNKNOWN" ||
        e.freeze_authority_status === "UNKNOWN"
      )
        ctx.addIssue({
          code: "custom",
          message: "unsupported partial SPL evidence",
        });
    } else if (
      e.mint_authority_status !== "UNKNOWN" ||
      e.freeze_authority_status !== "UNKNOWN"
    ) {
      ctx.addIssue({
        code: "custom",
        message: "unsupported evidence cannot claim known authority state",
      });
    }
  });
export const authoritiesSchema = z
  .discriminatedUnion("status", [
    z.object({
      status: z.literal("storage_disabled"),
      observations: z.array(z.never()),
    }),
    z.object({
      status: z.literal("stored_partial_evidence"),
      as_of: timestamp,
      security_status: z.literal("UNKNOWN"),
      approved_pump_watch: z.literal(false),
      observations: z
        .array(
          z.object({
            evidence: authorityEvidence,
            ingested_at: timestamp,
            expires_at: timestamp,
            freshness: z.enum(["current", "stale"]),
          }),
        )
        .max(100),
    }),
  ])
  .superRefine((data, ctx) => {
    if (data.status !== "stored_partial_evidence") return;
    for (const row of data.observations) {
      const known = Date.parse(row.evidence.known_at),
        cutoff = Date.parse(data.as_of);
      if (
        known > cutoff ||
        Date.parse(row.ingested_at) > cutoff ||
        Date.parse(row.expires_at) !== known + 900000 ||
        (row.freshness === "current") !== cutoff - known < 900000
      )
        ctx.addIssue({
          code: "custom",
          message: "invalid evidence cutoff or freshness",
        });
    }
  });
