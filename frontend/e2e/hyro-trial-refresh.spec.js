import fs from "node:fs";
import process from "node:process";

import { expect, test } from "@playwright/test";

import { createEmergencyMock } from "./support/emergencyMock.js";

const enabled = process.env.EXPECT_HYRO_TRIAL_ENABLED === "true";
const evidenceUrl = new URL("../../tmp/chatgpt_reviews/cc6s_browser_acceptance.json", import.meta.url);

test.describe("Hyro Trial server-side read-only refresh", () => {
    test.skip(!enabled, "Set EXPECT_HYRO_TRIAL_ENABLED=true to run the Hyro Trial acceptance flow");

    test("authenticated operator can refresh without external or order requests", async ({ page, context }) => {
        test.setTimeout(90_000);
        fs.mkdirSync(new URL(".", evidenceUrl), { recursive: true, mode: 0o700 });

        const evidence = {
            result: "FAIL",
            unauthenticatedRejected: false,
            authenticated: false,
            kucoinVisible: false,
            successfulRefresh: false,
            duplicateSuppressed: false,
            dashboardAccountStatusShared: false,
            failureRetainsStale: false,
            partialUnknownPreserved: false,
            lateResponseDiscarded: false,
            realHyroStartDisabled: false,
            refreshRequests: 0,
            csrfHeadersPresent: true,
            orderMutationRequests: [],
            externalRequests: [],
            pageErrors: [],
        };

        let authenticated = false;
        let responseMode = "SUCCESS";
        let pendingResolve = null;
        const initialTime = "2026-11-15T09:15:25.342619Z";
        const refreshed = (quality = "READY", equity = 25200, time = "2026-11-15T13:00:00Z") => ({
            id: "hyro-issued-trial-redacted",
            accountName: "Hyro Terminal 無料Trial — 25,000 USDT",
            plan: "FREE TRIAL（購入予定のHyro Coreとは別口座）",
            stage: "EVALUATION",
            period: "swing",
            platform: "HYRO TERMINAL",
            updatedAt: time,
            source: "HYRO OFFICIAL MCP / SERVER READ-ONLY REFRESH",
            readKind: "ISSUED_READ_ONLY",
            sample: false,
            readOnly: true,
            status: "ACTIVE",
            dataQuality: quality,
            stagePublicIdVerified: true,
            rules: {
                ruleSheetPresent: true,
                ruleSheetEntryCount: 6,
                adoptedRuleValueCount: 0,
                minimumTradingDays: null,
                minimumTradingDaysUnit: null,
                note: "contract unconfirmed",
            },
            metrics: {
                source: "GET_STAGE_METRICS_AND_GET_STAGE_TRADES",
                observedAt: time,
                initialBalance: 25000,
                currentEquity: equity,
                currentDrawdown: 0,
                currentLoss: 0,
                utcDayStartEquity: null,
                intradayMinimumEquity: null,
                qualifyingTradingDays: quality === "READY" ? 1 : null,
                dailyNetResults: quality === "READY" ? [200] : null,
                tradeHistoryComplete: quality === "READY",
                tradePagesRead: 1,
                tradeMaximumPages: 5,
                periodLabel: "all",
                pnl: null,
                positions: null,
                openOrders: null,
                conditionalOrders: null,
            },
        });

        const emergency = createEmergencyMock();
        await context.addCookies([{ name: "tradingai_csrf", value: "fixture-csrf", domain: "127.0.0.1", path: "/" }]);
        page.on("pageerror", (error) => evidence.pageErrors.push(String(error.message || error)));
        page.on("request", (request) => {
            const url = new URL(request.url());
            if (!["127.0.0.1", "localhost"].includes(url.hostname)) evidence.externalRequests.push(request.url());
            if (/(start|stop|arm|order|cancel|close|flatten|trade|execute)/i.test(url.pathname)
                && request.method().toUpperCase() !== "GET") {
                evidence.orderMutationRequests.push({ method: request.method(), path: url.pathname });
            }
        });

        await emergency.install(page);
        await page.route("**/api/auth/**", async (route) => {
            const path = new URL(route.request().url()).pathname;
            if (path === "/api/auth/status") {
                await route.fulfill({ status: authenticated ? 200 : 401, contentType: "application/json", body: JSON.stringify({ status: authenticated ? "AUTHENTICATED" : "UNAUTHENTICATED" }) });
            } else if (path === "/api/auth/login") {
                authenticated = true;
                await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "AUTHENTICATED" }) });
            } else {
                await route.fulfill({ status: 404, body: "{}" });
            }
        });
        await page.route("**/api/prop-accounts/hyro-trial/refresh", async (route) => {
            evidence.refreshRequests += 1;
            const request = route.request();
            evidence.csrfHeadersPresent = evidence.csrfHeadersPresent
                && request.method() === "POST"
                && request.headers()["x-tradingai-csrf"] === "fixture-csrf"
                && !request.postData();
            if (responseMode === "FAIL") {
                await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ ok: false, error: { code: "HYRO_TRIAL_READ_FAILED" } }) });
                return;
            }
            if (responseMode === "DELAY") {
                await new Promise((resolve) => { pendingResolve = resolve; });
            }
            const challenge = responseMode === "PARTIAL"
                ? refreshed("PARTIAL", 25150, "2026-11-15T14:00:00Z")
                : responseMode === "DELAY"
                    ? refreshed("READY", 25999, "2026-11-15T15:00:00Z")
                    : refreshed();
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, challenge }) });
        });

        await page.goto("/", { waitUntil: "networkidle" });
        await expect(page.locator("#operator-credential")).toBeVisible();
        evidence.unauthenticatedRejected = (await page.getByTestId("trading-account-switch").count()) === 0;

        await page.locator("#operator-credential").fill("offline-operator");
        await page.getByRole("button", { name: "Login", exact: true }).click();
        await expect(page.getByText("Authenticated（認証済み）")).toBeVisible();
        evidence.authenticated = true;
        evidence.kucoinVisible = await page.getByText("PAPER", { exact: true }).first().isVisible();

        await page.getByRole("button", { name: "PROP口座 — HyroTrader" }).click();
        await page.getByRole("button", { name: "チャレンジ選択（一覧取得）" }).click();
        await page.getByTestId("hyro-challenge-select").selectOption("hyro-issued-trial-redacted");
        await expect(page.getByTestId("hyro-refresh-state")).toHaveText("SNAPSHOT_STALE");
        await expect(page.getByTestId("hyro-selected-challenge")).toContainText(initialTime);

        await page.getByTestId("hyro-progress-refresh").getByRole("button").evaluate((button) => {
            button.click();
            button.click();
        });
        await expect(page.getByTestId("hyro-refresh-state")).toHaveText("SUCCESS");
        await expect(page.getByTestId("hyro-selected-challenge")).toContainText("2026-11-15T13:00:00Z");
        await expect(page.getByTestId("hyro-core-reference")).toContainText("200 / 2,500 USDT");
        evidence.successfulRefresh = true;
        evidence.duplicateSuppressed = evidence.refreshRequests === 1;

        await page.getByRole("button", { name: "ACCOUNT STATUS" }).click();
        await expect(page.getByTestId("hyro-trial-account-status")).toContainText("25,200 USDT");
        await expect(page.getByTestId("hyro-trial-account-status")).toContainText("2026-11-15T13:00:00Z");
        evidence.dashboardAccountStatusShared = true;

        responseMode = "FAIL";
        await page.getByTestId("hyro-account-status-refresh").getByRole("button").click();
        await expect(page.getByTestId("hyro-account-status-refresh")).toContainText("FAILED_STALE");
        await expect(page.getByTestId("hyro-trial-account-status")).toContainText("25,200 USDT");
        await expect(page.getByTestId("hyro-account-status-refresh")).toContainText("2026-11-15T13:00:00Z");
        evidence.failureRetainsStale = true;

        await page.getByRole("button", { name: "DASHBOARD" }).click();
        responseMode = "PARTIAL";
        await page.getByTestId("hyro-progress-refresh").getByRole("button").click();
        await expect(page.getByTestId("hyro-refresh-state")).toHaveText("PARTIAL");
        await expect(page.getByTestId("hyro-core-reference")).toContainText("判定不能");
        await expect(page.getByTestId("hyro-selected-challenge")).toContainText("2026-11-15T14:00:00Z");
        evidence.partialUnknownPreserved = true;

        responseMode = "DELAY";
        await page.getByTestId("hyro-progress-refresh").getByRole("button").click();
        await expect(page.getByTestId("hyro-refresh-state")).toHaveText("REFRESHING");
        await page.getByTestId("hyro-challenge-select").selectOption("hyro-sample-free-trial-a");
        pendingResolve();
        await page.waitForTimeout(100);
        await expect(page.getByTestId("hyro-selected-challenge")).toContainText("Sample A");
        await expect(page.getByTestId("hyro-selected-challenge")).not.toContainText("25,999");
        evidence.lateResponseDiscarded = true;

        await expect(page.getByRole("button", { name: "実Hyro START（未確認のため無効）" })).toBeDisabled();
        evidence.realHyroStartDisabled = true;

        evidence.externalRequests.push(...emergency.getExternalRequests());
        evidence.unexpectedApiRequests = emergency.getUnexpectedApiRequests();
        const pass = evidence.unauthenticatedRejected
            && evidence.authenticated
            && evidence.kucoinVisible
            && evidence.successfulRefresh
            && evidence.duplicateSuppressed
            && evidence.dashboardAccountStatusShared
            && evidence.failureRetainsStale
            && evidence.partialUnknownPreserved
            && evidence.lateResponseDiscarded
            && evidence.realHyroStartDisabled
            && evidence.csrfHeadersPresent
            && evidence.orderMutationRequests.length === 0
            && evidence.externalRequests.length === 0
            && evidence.pageErrors.length === 0
            && evidence.unexpectedApiRequests.length === 0;
        evidence.result = pass ? "PASS" : "FAIL";
        fs.writeFileSync(evidenceUrl, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o600 });

        expect(evidence.refreshRequests).toBe(4);
        expect(evidence.duplicateSuppressed).toBe(true);
        expect(evidence.csrfHeadersPresent).toBe(true);
        expect(evidence.orderMutationRequests).toEqual([]);
        expect(evidence.externalRequests).toEqual([]);
        expect(evidence.pageErrors).toEqual([]);
        expect(evidence.unexpectedApiRequests).toEqual([]);
        expect(evidence.result).toBe("PASS");
    });
});
