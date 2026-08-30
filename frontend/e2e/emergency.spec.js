import { expect, test } from "@playwright/test";

import {
    createEmergencyMock,
    ENDPOINTS,
} from "./support/emergencyMock.js";

const waitForDashboard = async (page, mock, { emergencyReady = true } = {}) => {
    await page.goto("/");
    await expect(page.getByRole("group", { name: "Trading mode" })).toBeVisible();
    await expect(page.getByText("BOT STOPPED", { exact: true })).toBeVisible();
    await expect(page.getByText("MM RUNTIME").locator("..")).toContainText("RUNNING");
    await expect(page.getByText("CAPITAL AUTHORITY").locator("..")).toContainText("AVAILABLE");
    await expect(page.getByRole("button", { name: "EMERGENCY STOP" }))[
        emergencyReady ? "toBeEnabled" : "toBeDisabled"
    ]();
    await expect.poll(() => mock.getCallCount(ENDPOINTS.status)).toBeGreaterThan(0);
    await expect.poll(() => mock.getCallCount(ENDPOINTS.mmConfig)).toBeGreaterThan(0);
    await expect.poll(() => mock.getCallCount(ENDPOINTS.mmStatus)).toBeGreaterThan(0);
    expectNoUnsafeRequests(mock);
};

const emergencyStateLabel = (page) => (
    page.locator(".operation-emergency-status__state")
);

const expectNoUnsafeRequests = (mock) => {
    expect(mock.getExternalRequests()).toEqual([]);
    expect(mock.getUnexpectedApiRequests()).toEqual([]);
};

const clickEmergencyConfirm = async (page) => {
    await page.getByRole(
        "button",
        { name: /EMERGENCY STOP/ },
    ).click();
    const dialog = page.getByRole(
        "dialog",
        { name: "Confirm emergency stop" },
    );
    await expect(dialog).toBeVisible();
    await dialog.getByRole(
        "button",
        { name: "CONFIRM EMERGENCY" },
    ).click();
};

const clickEmergencyCancel = async (page) => {
    await page.getByRole(
        "button",
        { name: /EMERGENCY STOP/ },
    ).click();
    const dialog = page.getByRole(
        "dialog",
        { name: "Confirm emergency stop" },
    );
    await expect(dialog).toBeVisible();
    await dialog.getByRole(
        "button",
        { name: "CANCEL" },
    ).click();
};

test.describe.configure({
    mode: "serial",
});
test.describe("Emergency Stop / Return to Normal local-only E2E", () => {
    let mock;

    test.beforeEach(async ({ page }) => {
        mock = createEmergencyMock();
        await mock.install(page);
    });

    test.afterEach(async () => {
        expectNoUnsafeRequests(mock);
    });

    test("Emergency confirmation cancel sends no request and closes modal", async ({
        page,
    }) => {
        await waitForDashboard(page, mock);

        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(0);

        await clickEmergencyCancel(page);

        await expect(
            page.getByRole("dialog", { name: "Confirm emergency stop" }),
        ).toBeHidden();

        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(0);
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
        expect(mock.getCallCount(ENDPOINTS.botStop)).toBe(0);

        await expect(page.getByText("Emergency（緊急停止）").locator("..")).toContainText("READY");
    });

    test("Emergency confirmation sends one orchestrate request and refreshes", async ({
        page,
    }) => {
        await waitForDashboard(page, mock);

        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(0);
        const statusCountBefore = mock.getCallCount(ENDPOINTS.status);

        const emergencyResponse = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.emergency)
            && response.request().method() === "POST"
        ));
        await clickEmergencyConfirm(page);
        expect((await emergencyResponse).ok()).toBeTruthy();

        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(1);
        await expect.poll(() => mock.getCallCount(ENDPOINTS.status)).toBeGreaterThan(statusCountBefore);
        expect(mock.getRequests(ENDPOINTS.emergency)).toEqual([{
            method: "POST",
            path: ENDPOINTS.emergency,
            body: null,
        }]);
        await expect(
            page.getByRole("dialog", { name: "Confirm emergency stop" }),
        ).toBeHidden();

        const lastEmergencyRequest = mock.getState();
        expect(lastEmergencyRequest.emergencyLocked).toBe(true);
        expect(lastEmergencyRequest.emergencyState).not.toBe("READY");
    });

    test("Emergency locks, Return button unlocks to READY, and trading stays OFF", async ({
        page,
    }) => {
        await waitForDashboard(page, mock);

        const returnButton = page.getByRole(
            "button",
            { name: "通常に戻す" },
        );
        await expect(page.getByText("Emergency（緊急停止）").locator("..")).toContainText("READY");
        await expect(returnButton).toBeHidden();
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toHaveCount(0);

        const emergencyResponse = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.emergency)
            && response.request().method() === "POST"
        ));
        await clickEmergencyConfirm(page);
        expect((await emergencyResponse).ok()).toBeTruthy();

        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        await expect(returnButton).toBeVisible();
        await expect(returnButton).toBeEnabled();
        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(1);

        const unlockResponse = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.unlock)
            && response.request().method() === "POST"
        ));
        await returnButton.click();
        expect((await unlockResponse).ok()).toBeTruthy();

        await expect(page.getByText("Emergency（緊急停止）").locator("..")).toContainText("READY");
        await expect(returnButton).toBeHidden();
        await expect(
            page.getByRole("group", { name: "Loop on start" })
                .getByRole("button", { name: "OFF" }),
        ).toHaveAttribute("aria-pressed", "true");
        await expect(
            page.getByRole("group", { name: "Auto Trade on start" })
                .getByRole("button", { name: "OFF" }),
        ).toHaveAttribute("aria-pressed", "true");

        const finalStatus = mock.getStatus();
        expect(finalStatus).toMatchObject({
            emergencyLocked: false,
            emergencyState: "READY",
            loopEnabled: false,
            autoTradeEnabled: false,
            executionEnabled: false,
        });
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(1);
    });

    test("ACTION_REQUIRED can return directly; first unlock failure remains retryable", async ({
        page,
    }) => {
        mock.seedActionRequired({
            errorCode: "SNAPSHOT_STALE",
            stateUnknown: true,
        });
        mock.queueHttpError(
            ENDPOINTS.unlock,
            409,
            "BOT_STOP_FAILED",
        );

        await waitForDashboard(page, mock, { emergencyReady: false });

        const returnButton = page.getByRole(
            "button",
            { name: "通常に戻す" },
        );
        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        await expect(returnButton).toBeVisible();
        await expect(returnButton).toBeEnabled();
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toHaveCount(0);

        await returnButton.click();
        await expect(
            page.getByTestId("emergency-unlock-error"),
        ).toBeVisible();
        await expect(returnButton).toBeVisible();
        await expect(returnButton).toBeEnabled();
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(1);

        await returnButton.click();
        await expect(page.getByText("Emergency（緊急停止）").locator("..")).toContainText("READY");
        await expect(returnButton).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(2);
        expect(mock.getStatus()).toMatchObject({
            loopEnabled: false,
            autoTradeEnabled: false,
            executionEnabled: false,
        });
    });
});
