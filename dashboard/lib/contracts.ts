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
  features?: Service<z.infer<typeof featuresSchema>>;
  research?: Service<z.infer<typeof researchSchema>>;
  categories?: Service<z.infer<typeof categoriesSchema>>;
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

const featureDecimal = z.string().regex(/^-?\d+(\.\d+)?$/).nullable();
export const featuresSchema = z.object({
  data_status: z.enum(["stored_observations", "storage_disabled"]),
  as_of: z.string().datetime({ offset: true }),
  interval: z.literal("15m"),
  research_only: z.literal(true),
  signals_enabled: z.literal(false),
  markets: z
    .array(
      z.object({
        base: z.enum(["SOL", "XRP", "DOGE", "LINK", "SUI", "AVAX", "ADA"]),
        status: z.enum(["ok", "unavailable"]),
        reason: z.string().nullable(),
        feature_version: z.literal("core-features-v1"),
        provisional: z.literal(true),
        data_as_of: z.string().datetime({ offset: true }).nullable(),
        relative_strength_reason: z.string().nullable(),
        features: z.object({
          atr: featureDecimal,
          atr_pct: featureDecimal,
          range_atr: featureDecimal,
          relative_volume: featureDecimal,
          relative_strength: featureDecimal,
          volatility_state: z
            .enum(["expanding", "compressed", "normal"])
            .nullable(),
          structure_state: z
            .enum(["breakout_up", "breakdown", "range"])
            .nullable(),
        }),
      }),
    )
    .length(7),
});

const planId = z.string().regex(/^[0-9a-f]{64}$/);
const researchStatusCounts = z
  .object({
    scheduled: count,
    awaiting_capture: count,
    pending_outcome: count,
    complete: count,
    complete_excluded: count,
    missed_capture: count,
    incomplete_capture: count,
    incomplete_outcome: count,
  })
  .strict();
const researchFeatureCounts = z
  .object({
    ok: count,
    unavailable: count,
  })
  .strict();
const researchPlan = z.discriminatedUnion("status", [
  z
    .object({
      plan_id: planId,
      status: z.literal("available"),
      asset_id: z
        .string()
        .regex(/^cex:mexc-usdt-futures:(SOL|XRP|DOGE|LINK|SUI|AVAX|ADA)_USDT$/),
      interval: z.enum(["15m", "1h"]),
      decision_start: timestamp,
      decision_end: timestamp,
      total_slots: z.number().int().min(2).max(1000),
      as_of: timestamp,
      status_counts: researchStatusCounts,
      feature_status_counts: researchFeatureCounts,
    })
    .strict()
    .superRefine((plan, ctx) => {
      const slotTotal = Object.values(plan.status_counts).reduce(
        (sum, val) => sum + val,
        0,
      );
      const capturedTotal =
        plan.status_counts.pending_outcome +
        plan.status_counts.complete +
        plan.status_counts.complete_excluded +
        plan.status_counts.incomplete_outcome;
      const featureTotal =
        plan.feature_status_counts.ok + plan.feature_status_counts.unavailable;
      if (
        slotTotal !== plan.total_slots ||
        featureTotal !== capturedTotal ||
        Date.parse(plan.decision_start) >= Date.parse(plan.decision_end)
      ) {
        ctx.addIssue({
          code: "custom",
          message: "research plan slot or feature counts inconsistent",
        });
      }
    }),
  z
    .object({
      plan_id: planId,
      status: z.literal("unavailable"),
      asset_id: z.null(),
      interval: z.null(),
      decision_start: z.null(),
      decision_end: z.null(),
      total_slots: z.null(),
      as_of: z.null(),
      status_counts: z.null(),
      feature_status_counts: z.null(),
    })
    .strict(),
]);
export const researchSchema = z
  .discriminatedUnion("status", [
    z
      .object({
        status: z.literal("disabled"),
        research_only: z.literal(true),
        plans: z.array(z.never()),
      })
      .strict(),
    z
      .object({
        status: z.literal("configured"),
        research_only: z.literal(true),
        plans: z.array(researchPlan).max(10),
      })
      .strict(),
  ])
  .superRefine((data, ctx) => {
    if (data.status !== "configured") return;
    const ids = data.plans.map((p) => p.plan_id);
    if (new Set(ids).size !== ids.length) {
      ctx.addIssue({
        code: "custom",
        message: "duplicate research plan IDs",
      });
    }
  });

const categoryTag = z.enum(["meme", "ai", "unclassified"]);
const categoryAsset = z
  .object({
    asset_id: z
      .string()
      .regex(
        /^(cex:mexc-usdt-futures:(SOL|XRP|DOGE|LINK|SUI|AVAX|ADA)_USDT|solana:mint:[1-9A-HJ-NP-Za-km-z]{32,44})$/,
      ),
    asset_class: z.enum(["cex_futures", "solana_dex"]),
    risk_model: z.enum(["cex_usdt_perpetual", "solana_spl_token"]),
    categories: z.array(categoryTag).min(1).max(2),
    category_sources: z.array(z.string().min(1)),
    assigned_at: timestamp.nullable(),
    rationale: z.string().min(1).nullable(),
    coverage_gap: z.boolean(),
    conflict: z.boolean(),
  })
  .strict()
  .superRefine((asset, ctx) => {
    const isCex = asset.asset_id.startsWith("cex:mexc-usdt-futures:");
    if (
      (isCex &&
        (asset.asset_class !== "cex_futures" ||
          asset.risk_model !== "cex_usdt_perpetual")) ||
      (!isCex &&
        (asset.asset_class !== "solana_dex" ||
          asset.risk_model !== "solana_spl_token"))
    ) {
      ctx.addIssue({
        code: "custom",
        message: "asset_class and risk_model must match canonical asset_id",
      });
    }
    if (
      new Set(asset.categories).size !== asset.categories.length ||
      (asset.categories.includes("unclassified") && asset.categories.length > 1)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "unclassified cannot combine with sector tags",
      });
    }
    if (
      asset.conflict &&
      (!asset.coverage_gap || asset.categories[0] !== "unclassified")
    ) {
      ctx.addIssue({
        code: "custom",
        message: "conflicting claims must remain unclassified coverage gaps",
      });
    }
    if (
      !asset.coverage_gap &&
      (asset.category_sources.length === 0 ||
        !asset.assigned_at ||
        !asset.rationale)
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "classified assets require provenance source, timestamp, and rationale",
      });
    }
  });
export const categoriesSchema = z
  .object({
    registry_version: z.literal("category-registry-v1"),
    filter: z.enum(["all", "meme", "ai", "unclassified"]),
    research_only: z.literal(true),
    signals_enabled: z.literal(false),
    summary: z
      .object({
        total_assets: count,
        meme_count: count,
        ai_count: count,
        overlapping_meme_ai_count: count,
        unclassified_count: count,
        coverage_gap_count: count,
        conflict_count: count,
      })
      .strict(),
    assets: z.array(categoryAsset).max(500),
  })
  .strict();

const riskStatusEnum = z.enum(["BLOCK", "CAUTION", "UNKNOWN", "PASS"]);
const candidateStateEnum = z.enum([
  "DISCOVERED",
  "WATCHING",
  "PUMP_WATCH_PROVISIONAL",
  "DUMP_WARNING",
  "BLOCKED_SECURITY",
]);

export const candidateEvaluationSchema = z
  .object({
    data_status: z.enum(["stored_evaluation", "storage_disabled"]),
    mint: key,
    as_of: timestamp,
    token_risk: z.object({
      rule_version: z.literal("solana-token-risk-v1"),
      as_of: timestamp,
      security_status: riskStatusEnum,
      checks: z.object({
        mint_and_extensions: z.object({
          status: riskStatusEnum,
          program: z.string().optional(),
          reason: z.string(),
          mint_authority_status: z.string().optional(),
          freeze_authority_status: z.string().optional(),
          mint_authority: z.string().nullable().optional(),
          freeze_authority: z.string().nullable().optional(),
          extensions: z.array(z.any()).optional(),
          flags: z.array(z.string()),
        }),
        stage_liquidity: z.object({
          status: riskStatusEnum,
          stage: z.string().optional(),
          reason: z.string(),
          dex_liquidity_usd: z.string().nullable().optional(),
          sell_depth_2pct_usd: z.string().nullable().optional(),
          flags: z.array(z.string()),
        }),
        holder_concentration: z.object({
          status: riskStatusEnum,
          reason: z.string(),
          top_1_account_pct: z.string().nullable().optional(),
          top_10_account_pct: z.string().nullable().optional(),
          top_1_unlocked_pct: z.string().nullable().optional(),
          top_10_unlocked_pct: z.string().nullable().optional(),
          flags: z.array(z.string()),
        }),
      }),
      flags: z.array(z.string()),
      vendor_verdict_note: z.literal("vendor_score_never_sufficient_for_pass"),
    }),
    candidate_state: z.object({
      rule_version: z.literal("candidate-state-machine-v1"),
      mint: key,
      as_of: timestamp,
      window_end: timestamp,
      state: candidateStateEnum,
      security_status: riskStatusEnum,
      pump_score: z.string().nullable(),
      dump_score: z.string().nullable(),
      dump_warning_groups: z.union([z.number().int().nonnegative(), z.array(z.any()), z.null()]),
      blocking_gates: z.array(z.string()),
      provisional: z.literal(true),
      approved_live_signal: z.literal(false),
      alerts_enabled: z.literal(false),
    }),
  })
  .strict();


export const walletHistoryBatchSchema = z
  .object({
    batch_id: z.string().regex(/^[0-9a-f]{64}$/),
    provenance: z.object({
      source: z.string(),
      parser_version: z.string(),
      wallet: key,
      window_start: timestamp,
      window_end: timestamp,
      retrieved_at: timestamp,
      raw_sha256: z.string().regex(/^[0-9a-f]{64}$/),
      pagination_exhausted: z.boolean(),
      coverage_verified: z.literal(false),
    }),
    completeness: z.literal("unverified"),
    signals_enabled: z.literal(false),
  })
  .strict();

export const fundingGroupSchema = z
  .object({
    funder: key,
    wallets: z.array(key),
    signatures: z.array(z.string()),
    sources: z.array(z.string()),
    conclusion: z.literal("potential_shared_funding_only"),
  })
  .strict();

export const walletFundingGroupsSchema = z
  .object({
    as_of: z.union([timestamp, z.string()]),
    groups: z.array(fundingGroupSchema),
    ownership_verified: z.literal(false),
    conflicting_wallets: z.array(key),
  })
  .strict();

export const walletHistoryOverviewSchema = z
  .object({
    data_status: z.literal("stored_history"),
    wallet: key,
    as_of: timestamp,
    batches_count: z.number().int().nonnegative(),
    batches: z.array(walletHistoryBatchSchema),
    funding_count: z.number().int().nonnegative(),
    funding_groups: walletFundingGroupsSchema,
    completeness: z.literal("unverified"),
    signals_enabled: z.literal(false),
  })
  .strict();

export type WalletHistoryBatch = z.infer<typeof walletHistoryBatchSchema>;
export type FundingGroup = z.infer<typeof fundingGroupSchema>;
export type WalletFundingGroups = z.infer<typeof walletFundingGroupsSchema>;
export type WalletHistoryOverview = z.infer<typeof walletHistoryOverviewSchema>;
