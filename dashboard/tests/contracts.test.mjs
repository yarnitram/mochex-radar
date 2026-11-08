import { test } from "node:test";
import assert from "node:assert/strict";
import {
  outboxSchema,
  catalogSchema,
  profilePollsSchema,
  authoritiesSchema,
  featuresSchema,
  researchSchema,
  categoriesSchema,
  candidateEvaluationSchema,
  walletHistoryOverviewSchema,
} from "../lib/contracts.ts";
import { catalog, polls } from "./discovery-fixture.mjs";
import { authorities } from "./authority-fixture.mjs";

test("outbox contract fills omitted stored states with zero and strips unrelated data", () => {
  const data = outboxSchema.parse({
    status: "stored_outbox",
    states: { sent: 2 },
    body: "must not reach dashboard",
    chat_id: "private-example",
  });
  assert.equal(data.states.sent, 2);
  assert.equal(data.states.uncertain, 0);
  assert.equal("body" in data, false);
  assert.equal("chat_id" in data, false);
});

test("authority evidence cannot imply approval or confuse absent, present and unknown", () => {
  assert.equal(authoritiesSchema.parse(authorities).observations.length, 3);
  const replaceEvidence = (mutation) => ({
    ...authorities,
    observations: [
      {
        ...authorities.observations[0],
        evidence: { ...authorities.observations[0].evidence, ...mutation },
      },
    ],
  });
  for (const mutation of [
    { security_status: "PASS" },
    { approved_pump_watch: true },
    { mint_authority_status: "PRESENT" },
    { mint_authority: "1".repeat(32) },
    { reason: "token_2022_extensions_not_evaluated" },
  ]) {
    assert.equal(
      authoritiesSchema.safeParse(replaceEvidence(mutation)).success,
      false,
    );
  }
});

test("authority freshness rejects future knowledge and stale data marked current", () => {
  const row = authorities.observations[1];
  for (const mutation of [
    { freshness: "current" },
    { ingested_at: "2026-01-01T13:00:00Z" },
    { expires_at: "2026-01-02T11:15:00Z" },
  ]) {
    assert.equal(
      authoritiesSchema.safeParse({
        ...authorities,
        observations: [{ ...row, ...mutation }],
      }).success,
      false,
    );
  }
});

test("catalog accepts observation evidence but rejects accidental safety approval", () => {
  assert.equal(catalogSchema.parse(catalog).mints.length, 2);
  for (const mutation of [
    { approved_pump_watch: true },
    { security_status: "PASS" },
    { category: "ai" },
  ]) {
    assert.equal(
      catalogSchema.safeParse({ ...catalog, ...mutation }).success,
      false,
    );
  }
  assert.equal(
    catalogSchema.safeParse({
      ...catalog,
      mints: [{ ...catalog.mints[0], first_known_at: "not-a-time" }],
    }).success,
    false,
  );
});

test("poll schema distinguishes failed unknown counts from successful zero counts", () => {
  assert.equal(profilePollsSchema.parse(polls).polls[0].discovered_count, 0);
  assert.equal(profilePollsSchema.parse(polls).polls[1].discovered_count, null);
  for (const row of [
    { ...polls.polls[1], input_count: 0 },
    { ...polls.polls[0], discovered_count: null },
    { ...polls.polls[0], discovered_count: 1 },
  ]) {
    assert.equal(
      profilePollsSchema.safeParse({ ...polls, polls: [row] }).success,
      false,
    );
  }
});

test("invalid counts or unknown states cannot masquerade as valid delivery health", () => {
  for (const states of [
    { sent: -1 },
    { pending: 1.5 },
    { new_state: 4 },
    { sent: "2" },
  ]) {
    assert.equal(
      outboxSchema.safeParse({ status: "stored_outbox", states }).success,
      false,
    );
  }
});

test("core features preserve unknowns and prohibit enabled signals", () => {
  const data = {
    data_status: "storage_disabled",
    as_of: "2026-01-01T12:00:00Z",
    interval: "15m",
    research_only: true,
    signals_enabled: false,
    markets: ["SOL", "XRP", "DOGE", "LINK", "SUI", "AVAX", "ADA"].map(
      (base) => ({
        base,
        status: "unavailable",
        reason: "insufficient_lookback",
        feature_version: "core-features-v1",
        provisional: true,
        data_as_of: null,
        relative_strength_reason: null,
        features: {
          atr: null,
          atr_pct: null,
          range_atr: null,
          relative_volume: null,
          relative_strength: null,
          volatility_state: null,
          structure_state: null,
        },
      }),
    ),
  };
  assert.equal(
    featuresSchema.parse(data).markets[0].features.relative_volume,
    null,
  );
  assert.equal(
    featuresSchema.safeParse({ ...data, signals_enabled: true }).success,
    false,
  );
  assert.equal(
    featuresSchema.safeParse({ ...data, markets: [] }).success,
    false,
  );
});

test("research status contract enforces count invariants, isolates unavailable plans, and rejects extra fields", () => {
  const planId = "4".repeat(64);
  const missingId = "b".repeat(64);
  const valid = {
    status: "configured",
    research_only: true,
    plans: [
      {
        plan_id: planId,
        status: "available",
        asset_id: "cex:mexc-usdt-futures:SOL_USDT",
        interval: "15m",
        decision_start: "2026-11-06T08:45:00+00:00",
        decision_end: "2026-11-07T08:45:00+00:00",
        total_slots: 97,
        as_of: "2026-11-06T09:05:00+00:00",
        status_counts: {
          scheduled: 95,
          awaiting_capture: 0,
          pending_outcome: 1,
          complete: 1,
          complete_excluded: 0,
          missed_capture: 0,
          incomplete_capture: 0,
          incomplete_outcome: 0,
        },
        feature_status_counts: {
          ok: 2,
          unavailable: 0,
        },
      },
      {
        plan_id: missingId,
        status: "unavailable",
        asset_id: null,
        interval: null,
        decision_start: null,
        decision_end: null,
        total_slots: null,
        as_of: null,
        status_counts: null,
        feature_status_counts: null,
      },
    ],
  };
  assert.equal(researchSchema.parse(valid).plans.length, 2);
  assert.equal(
    researchSchema.parse({ status: "disabled", research_only: true, plans: [] })
      .status,
    "disabled",
  );
  for (const invalid of [
    { ...valid, research_only: false },
    { ...valid, plans: [valid.plans[0], valid.plans[0]] },
    {
      ...valid,
      plans: [{ ...valid.plans[0], total_slots: 99 }],
    },
    {
      ...valid,
      plans: [
        {
          ...valid.plans[0],
          feature_status_counts: { ok: 1, unavailable: 0 },
        },
      ],
    },
    {
      ...valid,
      plans: [{ ...valid.plans[0], gross_return: "0.01" }],
    },
  ]) {
    assert.equal(researchSchema.safeParse(invalid).success, false);
  }
});

test("category registry contract preserves distinct risk models, overlapping tags, and conflict coverage gaps", () => {
  const valid = {
    registry_version: "category-registry-v1",
    filter: "all",
    research_only: true,
    signals_enabled: false,
    summary: {
      total_assets: 3,
      meme_count: 2,
      ai_count: 1,
      overlapping_meme_ai_count: 1,
      unclassified_count: 1,
      coverage_gap_count: 1,
      conflict_count: 0,
    },
    assets: [
      {
        asset_id: "cex:mexc-usdt-futures:DOGE_USDT",
        asset_class: "cex_futures",
        risk_model: "cex_usdt_perpetual",
        categories: ["meme"],
        category_sources: ["operator:core-market-taxonomy-v1"],
        assigned_at: "2026-11-01T00:00:00+00:00",
        rationale: "Core meme perpetual",
        coverage_gap: false,
        conflict: false,
      },
      {
        asset_id: `solana:mint:${"A".repeat(32)}`,
        asset_class: "solana_dex",
        risk_model: "solana_spl_token",
        categories: ["ai", "meme"],
        category_sources: ["operator:solana-watchlist-v1"],
        assigned_at: "2026-11-01T00:00:00+00:00",
        rationale: "Overlapping AI+Meme token",
        coverage_gap: false,
        conflict: false,
      },
      {
        asset_id: "cex:mexc-usdt-futures:SOL_USDT",
        asset_class: "cex_futures",
        risk_model: "cex_usdt_perpetual",
        categories: ["unclassified"],
        category_sources: [],
        assigned_at: null,
        rationale: null,
        coverage_gap: true,
        conflict: false,
      },
    ],
  };
  assert.equal(categoriesSchema.parse(valid).assets.length, 3);
  for (const invalid of [
    { ...valid, signals_enabled: true },
    {
      ...valid,
      assets: [
        {
          ...valid.assets[0],
          risk_model: "solana_spl_token",
        },
      ],
    },
    {
      ...valid,
      assets: [
        {
          ...valid.assets[0],
          categories: ["meme", "unclassified"],
        },
      ],
    },
    {
      ...valid,
      assets: [
        {
          ...valid.assets[0],
          conflict: true,
        },
      ],
    },
  ]) {
    assert.equal(categoriesSchema.safeParse(invalid).success, false);
  }
});

test("candidate evaluation contract enforces fail-closed risk and signals disabled", () => {
  const mint = "A".repeat(32);
  const now = "2026-11-06T12:00:00+00:00";
  const valid = {
    data_status: "stored_evaluation",
    mint,
    as_of: now,
    token_risk: {
      rule_version: "solana-token-risk-v1",
      as_of: now,
      security_status: "BLOCK",
      checks: {
        mint_and_extensions: {
          status: "PASS",
          program: "spl-token",
          reason: "evaluated",
          mint_authority_status: "DISABLED",
          freeze_authority_status: "DISABLED",
          mint_authority: null,
          freeze_authority: null,
          extensions: [],
          flags: [],
        },
        stage_liquidity: {
          status: "BLOCK",
          stage: "DEX",
          reason: "evaluated",
          dex_liquidity_usd: "500.0",
          sell_depth_2pct_usd: "100.0",
          flags: ["critical_low_dex_liquidity", "critical_low_sell_depth"],
        },
        holder_concentration: {
          status: "CAUTION",
          reason: "evaluated",
          top_1_account_pct: "25.0",
          top_10_account_pct: "55.0",
          top_1_unlocked_pct: "25.0",
          top_10_unlocked_pct: "55.0",
          flags: ["elevated_top_1_concentration"],
        },
      },
      flags: ["critical_low_dex_liquidity", "critical_low_sell_depth"],
      vendor_verdict_note: "vendor_score_never_sufficient_for_pass",
    },
    candidate_state: {
      rule_version: "candidate-state-machine-v1",
      mint,
      as_of: now,
      window_end: now,
      state: "BLOCKED_SECURITY",
      security_status: "BLOCK",
      pump_score: null,
      dump_score: null,
      dump_warning_groups: [],
      blocking_gates: ["security_blocked", "critical_low_dex_liquidity"],
      provisional: true,
      approved_live_signal: false,
      alerts_enabled: false,
    },
  };
  assert.equal(candidateEvaluationSchema.parse(valid).mint, mint);
  for (const invalid of [
    { ...valid, candidate_state: { ...valid.candidate_state, approved_live_signal: true } },
    { ...valid, candidate_state: { ...valid.candidate_state, alerts_enabled: true } },
    { ...valid, token_risk: { ...valid.token_risk, vendor_verdict_note: "vendor_score_trusted" } },
    { ...valid, candidate_state: { ...valid.candidate_state, state: "INVALID_STATE" } },
  ]) {
    assert.equal(candidateEvaluationSchema.safeParse(invalid).success, false);
  }
});

test("wallet history overview contract enforces completeness unverified and signals disabled", () => {
  const wallet = "1".repeat(32);
  const now = "2026-11-08T00:00:00.000Z";
  const valid = {
    data_status: "stored_history",
    wallet,
    as_of: now,
    batches_count: 1,
    batches: [
      {
        batch_id: "a".repeat(64),
        provenance: {
          source: "solana-rpc",
          parser_version: "v1",
          wallet,
          window_start: "2026-11-07T00:00:00.000Z",
          window_end: now,
          retrieved_at: now,
          raw_sha256: "b".repeat(64),
          pagination_exhausted: true,
          coverage_verified: false,
        },
        completeness: "unverified",
        signals_enabled: false,
      },
    ],
    funding_count: 1,
    funding_groups: {
      as_of: now,
      groups: [
        {
          funder: "2".repeat(32),
          wallets: [wallet, "3".repeat(32)],
          signatures: ["sig1"],
          sources: ["solana-rpc"],
          conclusion: "potential_shared_funding_only",
        },
      ],
      ownership_verified: false,
      conflicting_wallets: [],
    },
    completeness: "unverified",
    signals_enabled: false,
  };

  assert.equal(walletHistoryOverviewSchema.parse(valid).wallet, wallet);

  for (const invalid of [
    { ...valid, signals_enabled: true },
    { ...valid, completeness: "verified" },
    { ...valid, funding_groups: { ...valid.funding_groups, ownership_verified: true } },
    { ...valid, batches: [{ ...valid.batches[0], provenance: { ...valid.batches[0].provenance, coverage_verified: true } }] },
    { ...valid, extra_field: "disallowed" },
  ]) {
    assert.equal(walletHistoryOverviewSchema.safeParse(invalid).success, false);
  }
});
