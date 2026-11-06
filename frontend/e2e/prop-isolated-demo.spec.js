import { readFile } from "node:fs/promises";
import process from "node:process";

import { expect, test } from "@playwright/test";

import { createNetworkIsolation } from "./support/networkIsolation.js";

const enabled = process.env.EXPECT_PROP_ENABLED === "true";
const fixtureDocument = JSON.parse(await readFile(
    new URL("../src/features/prop-accounts/generatedSyntheticOutcomes.json", import.meta.url),
    "utf8",
));
const passOutcome = fixtureDocument.scenarios.find(({ id }) => id === "calculation_pass").outcome;

const installFakeWebSocket = async (page) => {
    await page.addInitScript(() => {
        class FakeWebSocket {
            static CONNECTING = 0;
            static OPEN = 1;
            static CLOSED = 3;
            constructor(url) {
                this.url = String(url);
                this.readyState = FakeWebSocket.OPEN;
            }
            addEventListener() {}
            removeEventListener() {}
            send() {}
            close() { this.readyState = FakeWebSocket.CLOSED; }
        }
        window.WebSocket = FakeWebSocket;
    });
};

test("default OFF hides navigation and rejects the deep link", async ({ page }) => {
    test.skip(enabled, "OFF-only browser assertion");
    await installFakeWebSocket(page);
    const isolation = createNetworkIsolation({
        apiHandler: async (route) => route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({}),
        }),
    });
    await isolation.install(page);
    await page.goto("/prop-isolated-demo");
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("button", { name: "PROP隔離デモ" })).toHaveCount(0);
    await expect(page.getByTestId("prop-isolated-demo-page")).toHaveCount(0);
    isolation.assertClean(expect);
});

test("flag ON runs isolated same-origin workflow with recovery and responsive layout", async ({ page, context }) => {
    test.skip(!enabled, "ON-only browser assertion");
    await installFakeWebSocket(page);
    await context.addCookies([{
        name: "tradingai_csrf",
        value: "browser-test-csrf",
        domain: "127.0.0.1",
        path: "/",
    }]);
    const apiCalls = [];
    let revision = 1;
    let evaluationCount = 0;
    let evaluationStartedResolve;
    let releaseEvaluationResolve;
    const evaluationStarted = new Promise((resolve) => { evaluationStartedResolve = resolve; });
    const releaseEvaluation = new Promise((resolve) => { releaseEvaluationResolve = resolve; });
    const accountId = "acc_20000000000040008000000000000022";
    const account = (payload) => ({
        label: payload.label,
        currency: payload.currency,
        synthetic: true,
        persisted: false,
        identity: {
            account_id: accountId,
            revision,
            account_type: "PROP",
            execution_mode: "EXTERNAL_SIMULATION",
            execution_venue: "BYBIT_DEMO",
            lifecycle_state: "REGISTERED",
            prop_program: "HYROTRADER",
            prop_phase: payload.phase,
        },
    });
    const isolation = createNetworkIsolation({
        apiHandler: async (route, { path }) => {
            const request = route.request();
            const payload = request.postDataJSON();
            apiCalls.push({
                path,
                method: request.method(),
                csrf: request.headers()["x-tradingai-csrf"],
            });
            expect(request.method()).toBe("POST");
            expect(request.headers().origin).toBe("http://127.0.0.1:4174");
            expect(request.headers()["x-tradingai-csrf"]).toBe("browser-test-csrf");
            if (path.endsWith("/accounts/revise")) revision += 1;
            if (path.endsWith("/accounts") || path.endsWith("/accounts/revise")) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({ ok: true, requestId: payload.requestId, account: account(payload) }),
                });
                return;
            }
            if (path.endsWith("/evaluate")) {
                evaluationCount += 1;
                if (evaluationCount === 1) {
                    evaluationStartedResolve();
                    await releaseEvaluation;
                    await route.fulfill({
                        status: 200,
                        contentType: "application/json",
                        body: JSON.stringify({
                            ok: false,
                            error: { code: "INVALID_INPUT", message: "synthetic validation failed", fields: {} },
                        }),
                    });
                    return;
                }
                const outcome = structuredClone(passOutcome);
                outcome.accountScope.accountId = accountId;
                outcome.accountScope.identityRevision = revision;
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        ok: true,
                        requestId: payload.requestId,
                        accountId,
                        identityRevision: revision,
                        outcome,
                        authority: {
                            executionAuthorityGranted: false,
                            runtimeReady: false,
                            tradeReady: false,
                        },
                    }),
                });
                return;
            }
            throw new Error(`unexpected API path ${path}`);
        },
    });
    const consoleErrors = [];
    page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
    });
    await isolation.install(page);
    await page.goto("/prop-isolated-demo");
    await expect(page.getByRole("heading", { name: "PROP隔離デモ" })).toBeVisible();
    await expect(page.getByText("SYNTHETIC / NOT OFFICIAL / NO EXECUTION AUTHORITY")).toBeVisible();
    await expect(page.getByRole("button", { name: "PROP隔離デモ" })).toHaveAttribute("aria-current", "page");
    await page.getByRole("button", { name: "新しいサンプル口座を作成" }).click();
    await expect(page.getByTestId("offline-account-identity")).toContainText(accountId);

    const submit = page.locator(".cc-prop-offline__submit");
    const firstSubmission = submit.click();
    await evaluationStarted;
    await expect(submit).toBeDisabled();
    releaseEvaluationResolve();
    await firstSubmission;
    await expect(page.getByTestId("offline-error")).toContainText("INVALID_INPUT");
    await expect(page.getByTestId("offline-result")).toHaveCount(0);
    await submit.click();
    await expect(page.getByTestId("offline-result")).toContainText("計算結果 — PASS");
    await expect(page.getByTestId("offline-result")).toContainText("DISABLED");

    await page.getByRole("button", { name: "同じ口座をrevision更新" }).click();
    await expect(page.getByTestId("offline-account-identity")).toContainText("2");
    await page.screenshot({ path: "../tmp/cc4d-prop-demo-desktop.png", fullPage: true });

    for (const viewport of [
        { width: 1024, height: 768 },
        { width: 390, height: 844 },
    ]) {
        await page.setViewportSize(viewport);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await expect(page.getByTestId("prop-isolated-demo-page")).toBeVisible();
    }
    await page.screenshot({ path: "../tmp/cc4d-prop-demo-mobile.png", fullPage: true });
    expect(apiCalls.map(({ path }) => path)).toEqual([
        "/api/prop-accounts/synthetic/accounts",
        "/api/prop-accounts/synthetic/evaluate",
        "/api/prop-accounts/synthetic/evaluate",
        "/api/prop-accounts/synthetic/accounts/revise",
    ]);
    expect(consoleErrors).toEqual([]);
    isolation.assertClean(expect);
});
