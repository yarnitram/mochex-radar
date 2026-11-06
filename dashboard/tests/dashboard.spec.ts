import { test, expect } from "@playwright/test";
import { catalog, polls } from "./discovery-fixture.mjs";
import { authorities } from "./authority-fixture.mjs";
const snapshot = {
  authorities: { status: "available", data: authorities },
  catalog: { status: "available", data: catalog },
  profilePolls: { status: "available", data: polls },
  fetched_at: "2026-01-01T12:00:00Z",
  outbox: {
    status: "available",
    data: {
      status: "stored_outbox",
      states: {
        pending: 3,
        processing: 0,
        sent: 5,
        failed: 1,
        uncertain: 2,
        expired: 4,
      },
    },
  },
  core: {
    status: "available",
    data: {
      data_status: "stored_observations",
      interval: "15m",
      as_of: "2026-01-01T12:00:00Z",
      markets: ["SOL", "XRP", "DOGE", "LINK", "SUI", "AVAX", "ADA"].map(
        (base, i) => ({
          base,
          quote: "USDT",
          market_id: `${base}_USDT`,
          asset_id: `fixture:${base}`,
          status: i === 0 ? "stale" : "missing",
          close: i === 0 ? "150" : null,
          candle_return: i === 0 ? "-0.01" : null,
          close_time: i === 0 ? "2026-01-01T10:00:00Z" : null,
          retrieved_at: null,
        }),
      ),
    },
  },
  btc: {
    status: "available",
    data: {
      state: "unknown",
      reason: "insufficient_data",
      rule_version: "btc-context-v1",
      provisional: true,
      return_1h: null,
      data_as_of: null,
      input_open_times: [],
    },
  },
  collector: {
    status: "available",
    data: { status: "disabled", last_cycle: null },
  },
  scans: {
    status: "available",
    data: {
      status: "stored_scans",
      scans: [
        {
          id: "fixture-scan",
          mint: "A".repeat(32),
          categories: ["meme"],
          category_source: "operator:fixture",
          finished_at: "2026-01-01T12:00:00Z",
          status: "provider_error",
          pool_count: 0,
        },
      ],
    },
  },
};

test("stored observations show stale and missing data and filter categorized scans", async ({
  page,
}) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Market overview" }),
  ).toBeVisible();
  const core = page.locator("#core");
  await expect(core.getByRole("row")).toHaveCount(8);
  await expect(core.getByText("stale", { exact: true })).toBeVisible();
  await expect(core.getByText("missing", { exact: true })).toHaveCount(6);
  await expect(page.getByText("operator:fixture")).toBeVisible();
  await page.screenshot({ path: "test-results/overview.png", fullPage: true });
  await page.getByRole("button", { name: "AI", exact: true }).click();
  await expect(page.getByText("No recorded scans tagged AI.")).toBeVisible();
  await page.getByRole("button", { name: "Meme", exact: true }).click();
  await expect(page.getByText("operator:fixture")).toBeVisible();
});

test("failed refresh retains prior observations and labels them outdated", async ({
  page,
}) => {
  let fail = false;
  await page.route("**/api/dashboard", (route) =>
    fail ? route.fulfill({ status: 503 }) : route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Refresh data" }),
  ).toBeEnabled();
  fail = true;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "last successful snapshot",
  );
  await expect(
    page.locator("#core").getByText("outdated", { exact: true }),
  ).toHaveCount(7);
});

test("mobile view remains within viewport and unavailable services are explicit", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        fetched_at: snapshot.fetched_at,
        ...Object.fromEntries(
          [
            "core",
            "btc",
            "collector",
            "scans",
            "outbox",
            "catalog",
            "profilePolls",
            "authorities",
          ].map((key) => [key, { status: "unavailable", data: null }]),
        ),
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("Core feed unavailable")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Discovery catalog unavailable" }),
  ).toBeVisible();
  await expect(
    page.locator("#alerts").getByText("unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Scan history unavailable" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("alert counts show uncertain holds and remain labeled when refresh fails", async ({
  page,
}) => {
  let fail = false;
  await page.route("**/api/dashboard", (route) =>
    fail ? route.fulfill({ status: 503 }) : route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  const alerts = page.locator("#alerts");
  await expect(
    alerts.getByRole("group", { name: "uncertain notices" }),
  ).toContainText("2");
  await expect(
    alerts.getByRole("group", { name: "sent notices" }),
  ).toContainText("5");
  await expect(
    alerts.getByText("Uncertain deliveries need review.", { exact: false }),
  ).toBeVisible();
  await expect(alerts.getByRole("button")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Refresh data" }),
  ).toBeEnabled();
  await alerts.screenshot({ path: "test-results/alert-health.png" });
  fail = true;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(alerts.getByText("outdated", { exact: true })).toBeVisible();
  await expect(
    alerts.getByRole("group", { name: "sent notices" }),
  ).toContainText("5");
});

test("disabled alert storage is not displayed as an empty working outbox", async ({
  page,
}) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        outbox: {
          status: "available",
          data: { status: "storage_disabled", states: {} },
        },
      },
    }),
  );
  await page.goto("/");
  await expect(
    page.locator("#alerts").getByText("Alert storage is not configured."),
  ).toBeVisible();
  await expect(page.locator("#alerts dd")).toHaveText([
    "—",
    "—",
    "—",
    "—",
    "—",
    "—",
  ]);
});

test("alert service failure leaves core observations usable", async ({
  page,
}) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: { ...snapshot, outbox: { status: "unavailable", data: null } },
    }),
  );
  await page.goto("/");
  await expect(
    page.locator("#alerts").getByText("unavailable", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("#alerts dd")).toHaveText([
    "—",
    "—",
    "—",
    "—",
    "—",
    "—",
  ]);
  await expect(page.locator("#core").getByRole("row")).toHaveCount(8);
  await expect(
    page.locator("#core").getByText("stale", { exact: true }),
  ).toBeVisible();
});

test("discovery catalog filters case-sensitive mint identities and attempted scans", async ({
  page,
}) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  const panel = page.locator("#discovery");
  await expect(panel.getByText("A".repeat(32), { exact: true })).toBeVisible();
  await expect(panel.getByText("B".repeat(32), { exact: true })).toBeVisible();
  await expect(
    panel.getByText("security is UNKNOWN", { exact: false }),
  ).toBeVisible();
  const history = panel.getByRole("table").nth(1);
  await expect(
    history.getByRole("row").nth(1).getByRole("cell").nth(2),
  ).toHaveText("0");
  await expect(
    history.getByRole("row").nth(2).getByRole("cell").nth(2),
  ).toHaveText("—");
  await panel.getByRole("button", { name: "No attempt", exact: true }).click();
  await expect(panel.getByText("B".repeat(32), { exact: true })).toHaveCount(0);
  await panel
    .getByRole("button", { name: "Attempt recorded", exact: true })
    .click();
  await expect(panel.getByText("B".repeat(32), { exact: true })).toBeVisible();
  await panel
    .getByRole("searchbox", { name: "Search observed mint" })
    .fill("b".repeat(32));
  await expect(
    panel.getByRole("heading", { name: "No matching loaded records" }),
  ).toBeVisible();
  await panel.getByRole("searchbox").fill("B".repeat(32));
  await expect(panel.getByText("B".repeat(32), { exact: true })).toBeVisible();
  await panel.screenshot({ path: "test-results/discovery-catalog.png" });
});

test("catalog outage does not hide poll history and retained data is marked outdated", async ({
  page,
}) => {
  let outage = false;
  let fail = false;
  await page.route("**/api/dashboard", (route) =>
    fail
      ? route.fulfill({ status: 503 })
      : route.fulfill({
          json: outage
            ? { ...snapshot, catalog: { status: "unavailable", data: null } }
            : snapshot,
        }),
  );
  await page.goto("/");
  const panel = page.locator("#discovery");
  await expect(panel.getByText("2 loaded", { exact: true })).toBeVisible();
  fail = true;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(panel.getByText("outdated", { exact: true })).toBeVisible();
  await expect(panel.getByText("A".repeat(32), { exact: true })).toBeVisible();
  fail = false;
  outage = true;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", { name: "Discovery catalog unavailable" }),
  ).toBeVisible();
  await expect(
    panel.getByText("provider error", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("#core").getByRole("row")).toHaveCount(8);
});

test("disabled discovery storage differs from an empty observed catalog", async ({
  page,
}) => {
  let empty = false;
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        catalog: {
          status: "available",
          data: empty
            ? { ...catalog, mints: [] }
            : { status: "storage_disabled", mints: [] },
        },
        profilePolls: {
          status: "available",
          data: empty
            ? { ...polls, polls: [] }
            : { status: "storage_disabled", polls: [] },
        },
      },
    }),
  );
  await page.goto("/");
  const panel = page.locator("#discovery");
  await expect(
    panel.getByRole("heading", { name: "Discovery storage is not configured" }),
  ).toBeVisible();
  empty = true;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", { name: "No profiles observed yet" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "No discovery polls recorded" }),
  ).toBeVisible();
});

test("stored authority permissions remain separate from safety and filter without RPC", async ({
  page,
}) => {
  const liveCalls: string[] = [];
  page.on("request", (request) => {
    if (
      request.url().includes("api.mainnet") ||
      request.url().includes("/security/solana/")
    )
      liveCalls.push(request.url());
  });
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  const panel = page.locator("#authorities");
  await expect(panel.getByRole("row")).toHaveCount(4);
  await expect(
    panel.getByRole("row").nth(1).getByText("absent", { exact: true }),
  ).toHaveCount(2);
  await expect(
    panel.getByText("Overall security: UNKNOWN.", { exact: false }),
  ).toBeVisible();
  await expect(
    panel.getByText("Token-2022 extensions not evaluated", { exact: true }),
  ).toBeVisible();
  await panel.screenshot({ path: "test-results/authority-evidence.png" });
  await panel.getByRole("button", { name: "Stale", exact: true }).click();
  await expect(panel.getByRole("row")).toHaveCount(2);
  await expect(panel.getByText("present", { exact: true })).toBeVisible();
  await panel
    .getByRole("searchbox", { name: "Search authority mint" })
    .fill("z".repeat(44));
  await expect(
    panel.getByRole("heading", { name: "No matching loaded readings" }),
  ).toBeVisible();
  expect(liveCalls).toEqual([]);
  await expect(
    panel.getByRole("button", { name: /check|approve|send/i }),
  ).toHaveCount(0);
});

test("failed refresh keeps authority readings under an outdated label", async ({
  page,
}) => {
  let fail = false;
  await page.route("**/api/dashboard", (route) =>
    fail ? route.fulfill({ status: 503 }) : route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  const panel = page.locator("#authorities");
  await expect(panel.getByText("3 readings", { exact: true })).toBeVisible();
  fail = true;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(panel.getByText("outdated", { exact: true })).toHaveCount(4);
  await expect(panel.getByRole("row")).toHaveCount(4);
});

test("authority storage states differ from no readings and do not hide core markets", async ({
  page,
}) => {
  let mode = "disabled";
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        authorities:
          mode === "unavailable"
            ? { status: "unavailable", data: null }
            : {
                status: "available",
                data:
                  mode === "disabled"
                    ? { status: "storage_disabled", observations: [] }
                    : { ...authorities, observations: [] },
              },
      },
    }),
  );
  await page.goto("/");
  const panel = page.locator("#authorities");
  await expect(
    panel.getByRole("heading", { name: "Authority storage is not configured" }),
  ).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", { name: "No stored authority evidence" }),
  ).toBeVisible();
  mode = "unavailable";
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", { name: "Authority evidence unavailable" }),
  ).toBeVisible();
  await expect(page.locator("#core").getByRole("row")).toHaveCount(8);
});

test("core feature service outage is explicit without hiding core pairs", async ({
  page,
}) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Core market features" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Feature data unavailable. Stored candle history is required.",
    ),
  ).toBeVisible();
});

test("forward research progress displays configured plans, isolates unavailable plans, and distinguishes disabled/unavailable states", async ({
  page,
}) => {
  const planId =
    "41244a7a15e3b5b220d4e0eb9c819d87247d622d82c4684e8f4e60d14081e7a7";
  const missingId = "b".repeat(64);
  let mode = "configured";
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        research:
          mode === "unavailable"
            ? { status: "unavailable", data: null }
            : mode === "disabled"
              ? {
                  status: "available",
                  data: { status: "disabled", research_only: true, plans: [] },
                }
              : {
                  status: "available",
                  data: {
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
                  },
                },
      },
    }),
  );
  await page.goto("/");
  const panel = page.locator("#research");
  await expect(panel.getByText("2 plans", { exact: true })).toBeVisible();
  await expect(panel.getByRole("row")).toHaveCount(3);
  await expect(panel.getByText("SOL_USDT · 15m")).toBeVisible();
  await expect(panel.getByText("97 total slots")).toBeVisible();
  await expect(
    panel.getByText("1 complete · 0 excluded · 1 pending"),
  ).toBeVisible();
  await expect(panel.getByText("2 ok · 0 unavailable")).toBeVisible();
  await expect(panel.getByText("Journal unavailable")).toBeVisible();

  mode = "disabled";
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", {
      name: "Forward research status is not configured",
    }),
  ).toBeVisible();

  mode = "unavailable";
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", {
      name: "Forward research status unavailable",
    }),
  ).toBeVisible();
  await expect(page.locator("#core").getByRole("row")).toHaveCount(8);
});

test("category coverage panel filters overlapping Meme/AI tags, exposes coverage gaps, and isolates service unavailability", async ({
  page,
}) => {
  let available = true;
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        categories: available
          ? {
              status: "available",
              data: {
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
                    asset_id: `solana:mint:${"C".repeat(32)}`,
                    asset_class: "solana_dex",
                    risk_model: "solana_spl_token",
                    categories: ["ai", "meme"],
                    category_sources: ["operator:solana-watchlist-v1"],
                    assigned_at: "2026-11-01T00:00:00+00:00",
                    rationale: "Overlapping AI+Meme Solana token",
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
              },
            }
          : { status: "unavailable", data: null },
      },
    }),
  );
  await page.goto("/");
  const panel = page.locator("#categories");
  await expect(
    panel.getByRole("heading", { name: "Meme and AI category coverage" }),
  ).toBeVisible();
  await expect(panel.getByRole("row")).toHaveCount(4);
  await expect(panel.getByText("ai · meme")).toBeVisible();
  await expect(panel.getByText("coverage gap", { exact: true })).toBeVisible();

  await panel.getByRole("button", { name: "AI sector", exact: true }).click();
  await expect(panel.getByRole("row")).toHaveCount(2);
  await expect(panel.getByText(`solana:mint:${"C".repeat(32)}`)).toBeVisible();

  await panel
    .getByRole("button", { name: "Coverage gaps", exact: true })
    .click();
  await expect(panel.getByRole("row")).toHaveCount(2);
  await expect(
    panel.getByText("cex:mexc-usdt-futures:SOL_USDT"),
  ).toBeVisible();

  available = false;
  await page.getByRole("button", { name: "Refresh data" }).click();
  await expect(
    panel.getByRole("heading", { name: "Category registry unavailable" }),
  ).toBeVisible();
  await expect(page.locator("#core").getByRole("row")).toHaveCount(8);
});


test("candidate inspector displays point-in-time state machine and risk dimensions", async ({
  page,
}) => {
  const mint = "A".repeat(32);
  const now = "2026-11-06T12:00:00+00:00";
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/candidate*", (route) =>
    route.fulfill({
      json: {
        status: "available",
        data: {
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
                reason: "evaluated",
                mint_authority_status: "DISABLED",
                freeze_authority_status: "DISABLED",
                flags: [],
              },
              stage_liquidity: {
                status: "BLOCK",
                reason: "critical_low_dex_liquidity",
                dex_liquidity_usd: "500",
                sell_depth_2pct_usd: "100",
                flags: ["critical_low_dex_liquidity"],
              },
              holder_concentration: {
                status: "CAUTION",
                reason: "elevated_top_1_concentration",
                top_1_unlocked_pct: "25",
                top_10_unlocked_pct: "55",
                flags: ["elevated_top_1_concentration"],
              },
            },
            flags: ["critical_low_dex_liquidity"],
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
        },
      },
    }),
  );
  await page.goto("/");
  const panel = page.locator("#candidate");
  await expect(
    panel.getByRole("heading", {
      name: "Solana candidate risk & state inspector",
    }),
  ).toBeVisible();
  await panel
    .getByRole("searchbox", { name: "Solana mint address to inspect" })
    .fill(mint);
  await panel.getByRole("button", { name: "Inspect candidate" }).click();
  await expect(
    panel.getByText("BLOCKED SECURITY", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("security blocked", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("critical low dex liquidity").first(),
  ).toBeVisible();
});
