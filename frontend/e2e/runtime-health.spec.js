import { expect, test } from "@playwright/test";

const waitForBotState = async (request, expected) => {
    await expect.poll(async () => {
        const response = await request.get("/api/bot/status");
        expect(response.ok()).toBeTruthy();
        const status = await response.json();
        return status.runtime_health?.bot?.status;
    }).toBe(expected);
};

const expectMonitorValue = async (page, testId, expected) => {
    await expect(page.getByTestId(testId)).toHaveText(expected);
};

test.describe("Runtime Health Monitor lifecycle", () => {
    test.beforeEach(async ({ request }) => {
        const response = await request.post("/api/bot/stop");
        expect(response.ok()).toBeTruthy();
        await waitForBotState(request, "STOPPED");
    });

    test.afterEach(async ({ request }) => {
        await request.post("/api/bot/stop");
        await waitForBotState(request, "STOPPED");
    });

    test("shows STOP, START, and STOP current runtime health", async ({ page }) => {
        await page.goto("/");

        await expect(page).toHaveTitle("react_dashboard");
        const monitor = page.getByTestId("runtime-health-monitor");
        await expect(monitor).toBeVisible();
        await expect(page.getByText("2 | Runtime Health", { exact: true })).toBeVisible();
        await expect(page.getByText("Paper Balance:（模擬残高）", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("Paper Equity:（模擬純資産）", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("Paper Position:（模擬ポジション）", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("Paper PnL:（模擬損益）", { exact: true })).toBeVisible();
        await expect(page.getByTestId("paper-balance")).not.toHaveText("--");
        await expect(page.getByTestId("real-balance")).toHaveText("NOT CONNECTED");
        await expect(page.getByTestId("real-position")).toHaveText("NOT CONNECTED");
        await expect(page.getByTestId("exchange-auth")).toHaveText("NOT_VERIFIED");
        await expect(page.getByTestId("account-source")).toHaveText("PAPER_SIMULATION");
        await expect(page.getByTestId("real-order-allowed")).toHaveText("false");
        await expect(page.getByTestId("execution-mode")).toHaveText("SIMULATION");

        await expectMonitorValue(page, "bot-state", "STOPPED");
        await expectMonitorValue(page, "trading-runtime", "STOPPED");
        await expectMonitorValue(page, "pipeline-status", "SUSPENDED_BY_BOT_STOP");
        await expectMonitorValue(page, "execution-engine", "UNAVAILABLE_BY_BOT_STOP");
        await expectMonitorValue(page, "current-decision", "N/A");
        await expectMonitorValue(page, "trading-action", "NONE_BY_BOT_STOP");
        await expectMonitorValue(page, "action-reason", "BOT_STOPPED");

        const startResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith("/api/bot/start")
            && response.request().method() === "POST"
        ));
        await page.getByTestId("bot-start-button").click();
        expect((await startResponsePromise).ok()).toBeTruthy();

        await expectMonitorValue(page, "bot-state", "RUNNING");
        await expectMonitorValue(page, "exchange-ws", "LIVE");
        await expectMonitorValue(page, "trading-runtime", "ACTIVE");
        await expectMonitorValue(page, "pipeline-status", "OK");

        const stopResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith("/api/bot/stop")
            && response.request().method() === "POST"
        ));
        await page.getByTestId("bot-stop-button").click();
        expect((await stopResponsePromise).ok()).toBeTruthy();

        await expectMonitorValue(page, "bot-state", "STOPPED");
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
