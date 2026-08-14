import { expect, test } from "@playwright/test";

import {
    createEmergencyMock,
    ENDPOINTS,
} from "./support/emergencyMock.js";

const waitForBotState = async (page, expected) => {
    await expect.poll(async () => {
        return await page.evaluate(async () => {
            const response = await fetch("/api/bot/status");

            if (!response.ok) {
                return `HTTP_${response.status}`;
            }

            const status = await response.json();
            return status.runtime_health?.bot?.status;
        });
    }).toBe(expected);
};

const expectMonitorValue = async (page, testId, expected) => {
    await expect(page.getByTestId(testId)).toHaveText(expected);
};

const expandDiagnostics = async (page) => {
    await page.getByRole("button", { name: /RUNTIME & DIAGNOSTICS/i }).click();
};

test.describe("Runtime Health Monitor lifecycle", () => {
    let mock;

    test.beforeEach(async ({ page }) => {
        mock = createEmergencyMock();
        await mock.install(page);
    });

    test.afterEach(async () => {
        mock.assertNetworkClean(expect);
    });

    test("shows STOP, START, and STOP current runtime health", async ({ page }) => {
        await page.goto("/");

        await expect(page).toHaveTitle("react_dashboard");
        await expandDiagnostics(page);
        const monitor = page.getByTestId("runtime-health-monitor");
        await expect(monitor).toBeVisible();
        await expect(page.getByText("2 | Runtime Health", { exact: true })).toBeVisible();
        await expect(page.getByText("Paper Balance:（模擬残高）", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("Paper Equity:（模擬純資産）", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("Paper Position:（模擬ポジション）", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("Paper PnL:（模擬損益）", { exact: true })).toBeVisible();
        await expect(page.getByTestId("paper-balance")).not.toHaveText("--");
        await expect(page.getByTestId("real-balance")).toHaveText(/^(ACCOUNT_NOT_SYNCED|\d[\d,]*\.\d{2})$/);
        await expect(page.getByTestId("real-position")).toHaveText(/^(ACCOUNT_NOT_SYNCED|NO OPEN POSITION)$/);
        await expect(page.getByTestId("exchange-auth")).toHaveText(/^(NOT_VERIFIED|VERIFIED)$/);
        await expect(page.getByTestId("account-source")).toHaveText("PAPER_SIMULATION");
        await expect(page.getByTestId("real-order-allowed")).toHaveText("false");
        await expect(page.getByTestId("execution-mode")).toHaveText("SIMULATION");
        await expect(page.getByTestId("real-account-paper-context")).toContainText("PAPER MODE — LIVE ACCOUNT INACTIVE");

        await expectMonitorValue(page, "bot-state", "STOPPED");
        await expectMonitorValue(page, "trading-runtime", "STOPPED");
        await expectMonitorValue(page, "pipeline-status", "SUSPENDED_BY_BOT_STOP");
        await expectMonitorValue(page, "execution-engine", "UNAVAILABLE_BY_BOT_STOP");
        await expectMonitorValue(page, "current-decision", "N/A");
        await expectMonitorValue(page, "trading-action", "NONE_BY_BOT_STOP");
        await expectMonitorValue(page, "action-reason", "BOT_STOPPED");

        const loopToggle = page.getByRole(
            "switch",
            {
                name: "Toggle trading loop",
            },
        );
        await expect(loopToggle).toHaveAttribute("aria-checked", "false");

        const startResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.botStart)
            && response.request().method() === "POST"
        ));
        await loopToggle.click();
        expect((await startResponsePromise).ok()).toBeTruthy();
        await waitForBotState(page, "RUNNING");

        await expectMonitorValue(page, "bot-state", "RUNNING");
        await expect(loopToggle).toHaveAttribute("aria-checked", "true");
        await expectMonitorValue(page, "exchange-ws", "LIVE");
        await expectMonitorValue(page, "trading-runtime", "ACTIVE");
        await expectMonitorValue(page, "pipeline-status", "OK");
        await expect(page.getByTestId("emergency-bot-state")).toHaveText("Botは稼働中です");
        await expect(page.getByTestId("emergency-bot-state")).not.toContainText("停止中");

        const autoTradeToggle = page.getByRole("switch", {
            name: "Toggle automatic trading",
        });
        await autoTradeToggle.click();
        await expect(page.getByText("WAITING FOR SIGNAL", { exact: true })).toBeVisible();
        await expectMonitorValue(page, "trading-action", "IDLE_BY_AI_HOLD");
        await expectMonitorValue(page, "current-decision", "HOLD");
        await expect(monitor.getByText("1.00 ms", { exact: true })).toBeVisible();

        const stopResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.botStop)
            && response.request().method() === "POST"
        ));
        await loopToggle.click();
        expect((await stopResponsePromise).ok()).toBeTruthy();
        await waitForBotState(page, "STOPPED");

        await expectMonitorValue(page, "bot-state", "STOPPED");
        await expect(loopToggle).toHaveAttribute("aria-checked", "false");
        await expectMonitorValue(page, "exchange-ws", "DISCONNECTED_BY_BOT_STOP");
        await expectMonitorValue(page, "trading-runtime", "STOPPED");
        await expectMonitorValue(page, "current-decision", "N/A");
        await expectMonitorValue(page, "trading-action", "NONE_BY_BOT_STOP");

        await expect(monitor).not.toContainText("IDLE_BY_AI_HOLD");
        await expect(monitor).not.toContainText("Execution Reason: AI_HOLD");
        await expect(page.getByTestId("current-decision")).not.toHaveText("HOLD");
    });

    test("LIVE selection remains clearly identified as simulation", async ({ page }) => {
        await page.goto("/");

        await expandDiagnostics(page);
        await page.locator("select.config-select").first().selectOption("LIVE");

        await expect(page.getByTestId("selected-mode")).toHaveText("LIVE");
        await expect(page.getByTestId("execution-mode")).toHaveText("SIMULATION");
        await expect(page.getByTestId("real-orders")).toHaveText("DISABLED");
        await expect(page.getByTestId("safety-reason")).toHaveText(
            "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE",
        );
        await expect(page.getByTestId("dry-run")).toHaveText("true");
    });
});
