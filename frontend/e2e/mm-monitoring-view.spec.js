import { test, expect } from "@playwright/test";
import { validStatus, validConfiguration } from "../src/features/money-management/contracts/moneyManagementFixtures.js";
import { monitoringFixture, historyFixture, legacyFixture } from "../src/features/money-management/contracts/moneyManagementMonitoringFixtures.js";

async function setup(page, { mode = "PAPER", freshness = "LAST_KNOWN", unavailable = null, delayed = false, statusError = false, monitoringError = false, emptyHistory = false } = {}) {
    const requests = [];
    const settings = { mode, freshness, unavailable, delayed, statusError, monitoringError, emptyHistory };
    await page.route(url => url.pathname.startsWith("/api/"), async route => {
        const request = route.request();
        const url = new URL(request.url());
        requests.push({ path: url.pathname, query: Object.fromEntries(url.searchParams), method: request.method() });
        if (request.method() !== "GET") return route.fulfill({ status: 405, body: "{}" });
        let body;
        if (url.pathname.endsWith("/status")) {
            if (settings.statusError) return route.fulfill({ status: 503, body: "{}" });
            body = validStatus({ mode: settings.mode, lifecycleState: settings.mode === "UNKNOWN" ? "STOPPED" : "RUNNING" });
        } else if (url.pathname.endsWith("/configuration")) body = validConfiguration();
        else if (url.pathname.endsWith("/monitoring")) {
            if (settings.monitoringError) return route.fulfill({ status: 503, body: "{}" });
            const authority = url.searchParams.get("viewAuthority");
            if (settings.delayed && authority === "LIVE") await new Promise(resolve => setTimeout(resolve, 500));
            body = monitoringFixture(authority, settings.unavailable === authority ? "UNAVAILABLE" : settings.freshness);
        } else if (url.pathname.endsWith("/history")) {
            const authority = url.searchParams.get("authority") ?? "ALL";
            const events = [historyFixture("PAPER", 1, new Date().toISOString()), historyFixture("LIVE", 2, new Date().toISOString()), legacyFixture];
            body = { events: settings.emptyHistory ? [] : authority === "ALL" ? events : events.filter(e => e.authority === authority), hasMore: false, nextCursor: null };
        } else return route.fulfill({ status: 404, body: "{}" });
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/e2e/support/mm-monitoring-harness.html");
    return { requests, settings };
}
const selector = page => page.getByRole("group", { name: "Monitoring View authority", exact: true });
const summary = page => page.getByRole("region", { name: "Money Management summary", exact: true });

for (const mode of ["PAPER", "LIVE", "UNKNOWN"]) {
    test(`initial runtime ${mode}, independent View switching and GET-only requests`, async ({ page }) => {
        const { requests, settings } = await setup(page, { mode });
        const initial = mode === "LIVE" ? "LIVE" : "PAPER";
        await expect(selector(page).getByRole("button", { name: initial, exact: true })).toHaveAttribute("aria-pressed", "true");
        await expect(summary(page)).toContainText(initial === "PAPER" ? "101.25" : "202.50");
        const other = initial === "PAPER" ? "LIVE" : "PAPER";
        await selector(page).getByRole("button", { name: other, exact: true }).click();
        await expect(summary(page)).toContainText(other === "PAPER" ? "101.25" : "202.50");
        if (mode === "UNKNOWN") await expect(page.getByRole("region", { name: "Monitoring View", exact: true })).toContainText("UNKNOWN / STOPPED");
        settings.mode = initial;
        await expect.poll(() => requests.filter(r => r.path.endsWith("/status")).length).toBeGreaterThan(1);
        await expect(selector(page).getByRole("button", { name: other, exact: true })).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByRole("region", { name: "Monitoring View", exact: true })).toContainText(`Actual Runtime（実稼働）: ${initial}`);
        for (const authority of [initial, other]) {
            expect(requests.some(r => r.path.endsWith("/monitoring") && r.query.viewAuthority === authority)).toBeTruthy();
            expect(requests.some(r => r.path.endsWith("/history") && r.query.authority === authority)).toBeTruthy();
        }
        expect(requests.every(r => r.method === "GET")).toBeTruthy();
        expect(requests.every(r => /^\/api\/money-management\/(status|configuration|monitoring|history)$/.test(r.path))).toBeTruthy();
        await expect(selector(page).getByRole("button")).toHaveCount(2);
    });
}
test("unresolved runtime uses PAPER and monitoring remains inspectable", async ({ page }) => {
    await setup(page, { statusError: true });
    await expect(selector(page).getByRole("button", { name: "PAPER", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(summary(page)).toContainText("101.25");
});
for (const authority of ["PAPER", "LIVE"]) {
    test(`${authority} unavailable never shows opposite runtime values`, async ({ page }) => {
        await setup(page, { mode: authority === "LIVE" ? "PAPER" : "LIVE", unavailable: authority });
        await expect(summary(page)).toContainText(authority === "LIVE" ? "101.25" : "202.50");
        await selector(page).getByRole("button", { name: authority, exact: true }).click();
        await expect(page.getByRole("region", { name: "Monitoring View", exact: true })).toContainText(`${authority} Monitoring — UNAVAILABLE`);
        await expect(summary(page)).not.toContainText("101.25");
        await expect(summary(page)).not.toContainText("202.50");
        await expect(summary(page)).not.toContainText("1000.25");
    });
}
for (const freshness of ["LAST_KNOWN", "STALE"]) {
    test(`${freshness} displays metadata, retained snapshot values and truthful labels`, async ({ page }) => {
        await setup(page, { mode: "LIVE", freshness });
        const view = page.getByRole("region", { name: "Monitoring View", exact: true });
        await expect(view).toContainText(`LIVE Monitoring — ${freshness}`);
        await expect(view).toContainText("2026-09-12T00:00:00Z");
        await expect(view).toContainText("REAL_LIVE_ACCOUNT_EQUITY");
        await expect(summary(page)).toContainText("Realized PnL Today");
        await expect(summary(page)).toContainText("22.50");
        await expect(page.getByText("Maximum Drawdown Limit", { exact: true })).toBeVisible();
        await expect(summary(page)).not.toContainText("ENTRY ALLOWED");
        await selector(page).getByRole("button", { name: "PAPER", exact: true }).click();
        await expect(summary(page)).toContainText("Realized PnL (Engine Reported)");
        await expect(summary(page)).toContainText("11.25");
        await expect(page.locator("main")).not.toContainText("Cumulative");
    });
}
test("delayed LIVE transition clears PAPER and rapid switching cannot cross-populate", async ({ page }) => {
    await setup(page, { delayed: true });
    await expect(summary(page)).toContainText("101.25");
    await selector(page).getByRole("button", { name: "LIVE", exact: true }).click();
    await expect(summary(page)).not.toContainText("101.25");
    await expect(page.getByRole("region", { name: "Monitoring View", exact: true })).toContainText("LIVE Monitoring — LOADING");
    await selector(page).getByRole("button", { name: "PAPER", exact: true }).click();
    await expect(summary(page)).toContainText("101.25");
    await page.waitForTimeout(650);
    await expect(summary(page)).not.toContainText("202.50");
    await expect(selector(page).getByRole("button", { name: "PAPER", exact: true })).toHaveAttribute("aria-pressed", "true");
});
test("audit UNKNOWN is independent and retains legacy event; periods preserve View", async ({ page }) => {
    const { requests } = await setup(page);
    await expect(summary(page)).toContainText("101.25");
    await page.locator("summary").filter({ hasText: "Runtime History（実行履歴）" }).click();
    const audit = page.getByRole("group", { name: "Runtime History authority", exact: true });
    await expect(audit.getByRole("button", { name: "ALL", exact: true })).toHaveAttribute("aria-pressed", "true");
    await audit.getByRole("button", { name: "UNKNOWN / LEGACY", exact: true }).click();
    await expect.poll(() => requests.some(r => r.query.authority === "UNKNOWN")).toBeTruthy();
    await expect(page.locator(".mm-runtime-timeline")).toContainText("UNKNOWN / LEGACY");
    await expect(page.locator(".mm-runtime-timeline li")).toHaveCount(1);
    await selector(page).getByRole("button", { name: "LIVE", exact: true }).click();
    await expect(summary(page)).toContainText("202.50");
    for (const period of ["7D", "30D", "ALL"]) {
        await page.getByRole("group", { name: "Graph period", exact: true }).getByRole("button", { name: period, exact: true }).click();
        await expect(selector(page).getByRole("button", { name: "LIVE", exact: true })).toHaveAttribute("aria-pressed", "true");
    }
    await expect(audit.getByRole("button", { name: "UNKNOWN / LEGACY", exact: true })).toHaveAttribute("aria-pressed", "true");
});
for (const width of [390, 760, 1100]) {
    test(`selector and graph controls remain separate at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await setup(page);
        await expect(summary(page)).toContainText("101.25");
        const view = await selector(page).boundingBox();
        const periods = await page.getByRole("group", { name: "Graph period", exact: true }).boundingBox();
        expect(view.x).toBeGreaterThanOrEqual(0); expect(view.x + view.width).toBeLessThanOrEqual(width);
        expect(periods.y).toBeGreaterThan(view.y + view.height);
        await selector(page).getByRole("button", { name: "LIVE", exact: true }).click();
        await expect(summary(page)).toContainText("202.50");
    });
}

test("empty LIVE history shows an explicit empty state without synthetic charts", async ({ page }) => {
    await setup(page, { mode: "LIVE", emptyHistory: true });
    await expect(summary(page)).toContainText("202.50");
    const graphs = page.getByRole("region", { name: "Capital / Performance Graphs", exact: true });
    await expect(graphs.getByText("No LIVE MM history available（履歴データなし）", { exact: true })).toHaveCount(4);
    await expect(graphs.locator(".recharts-line")).toHaveCount(0);
});
test("monitoring request failure is distinct from unavailable and clears values", async ({ page }) => {
    await setup(page, { mode: "LIVE", monitoringError: true });
    await expect(page.getByRole("region", { name: "Monitoring View", exact: true })).toContainText("LIVE Monitoring — REQUEST ERROR");
    await expect(summary(page)).not.toContainText("101.25");
    await expect(summary(page)).not.toContainText("202.50");
    await expect(summary(page)).not.toContainText("1000.25");
});

test("manual refresh keeps selected View and preserves the header result contract", async ({ page }) => {
    const { requests } = await setup(page);
    await expect(summary(page)).toContainText("101.25");
    await selector(page).getByRole("button", { name: "LIVE", exact: true }).click();
    await expect(summary(page)).toContainText("202.50");
    const previous = requests.filter(r => r.path.endsWith("/monitoring")).length;
    await page.locator(".mm-header__refresh").click();
    await expect.poll(() => requests.filter(r => r.path.endsWith("/monitoring")).length).toBeGreaterThan(previous);
    await expect(summary(page)).toContainText("202.50");
    await expect(page.locator(".mm-header__refresh-error")).toHaveCount(0);
    expect(requests.filter(r => r.path.endsWith("/monitoring")).at(-1).query.viewAuthority).toBe("LIVE");
    expect(requests.every(r => r.method === "GET")).toBeTruthy();
});

for (const authority of ["PAPER", "LIVE"]) {
    test(`stopped runtime retains inspectable ${authority} observations`, async ({ page }) => {
        const { requests } = await setup(page, { mode: "UNKNOWN" });
        await selector(page).getByRole("button", { name: authority, exact: true }).click();
        await expect(summary(page)).toContainText(authority === "PAPER" ? "101.25" : "202.50");
        await expect(page.getByRole("region", { name: "Monitoring View", exact: true })).toContainText("UNKNOWN / STOPPED");
        expect(requests.every(r => r.method === "GET")).toBeTruthy();
    });
}

test("obsolete refresh completion cannot schedule a second monitoring poll chain", async ({ page }) => {
    const { requests } = await setup(page);
    await expect(summary(page)).toContainText("101.25");
    let held;
    let intercept = true;
    await page.route("**/api/money-management/monitoring?*", async route => {
        if (intercept) {
            intercept = false;
            held = route;
            return;
        }
        await route.fallback();
    });
    await page.locator(".mm-header__refresh").click();
    await expect.poll(() => Boolean(held)).toBeTruthy();
    // Changing authority cancels the held refresh and starts the active chain.
    await selector(page).getByRole("button", { name: "LIVE", exact: true }).click();
    await expect(summary(page)).toContainText("202.50");
    const before = requests.filter(r => r.path.endsWith("/monitoring")).length;
    await held.fulfill({ contentType: "application/json", body: JSON.stringify(monitoringFixture("PAPER")) }).catch(() => {});
    await page.waitForTimeout(3500);
    const subsequent = requests.filter(r => r.path.endsWith("/monitoring")).slice(before);
    expect(subsequent).toHaveLength(1);
    expect(subsequent[0].query.viewAuthority).toBe("LIVE");
    await expect(summary(page)).toContainText("202.50");
    await expect(summary(page)).not.toContainText("101.25");
});

test("history request failure clears graphs without opposite-authority fallback", async ({ page }) => {
    await setup(page);
    await expect(summary(page)).toContainText("101.25");
    await page.route("**/api/money-management/history?*", route => route.fulfill({ status: 503, body: "{}" }));
    await selector(page).getByRole("button", { name: "LIVE", exact: true }).click();
    const graphs = page.getByRole("region", { name: "Capital / Performance Graphs", exact: true });
    await expect(graphs.getByRole("alert")).toBeVisible();
    await expect(graphs.locator(".recharts-line")).toHaveCount(0);
    await expect(summary(page)).toContainText("202.50");
});
