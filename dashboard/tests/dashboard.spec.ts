import { test, expect } from "@playwright/test";
const snapshot = {
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
          ["core", "btc", "collector", "scans", "outbox"].map((key) => [
            key,
            { status: "unavailable", data: null },
          ]),
        ),
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("Core feed unavailable")).toBeVisible();
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
