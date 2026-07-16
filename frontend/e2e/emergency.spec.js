import { expect, test } from "@playwright/test";

import {
    createEmergencyMock,
    ENDPOINTS,
} from "./support/emergencyMock.js";

const waitForDashboard = async (page) => {
    await page.goto("/");
    await expect(page.getByText("EMERGENCY STATUS")).toBeVisible();
};

const emergencyStateLabel = (page) => (
    page.locator(".operation-emergency-status__state")
);

const emergencyTimelineFor = (status, operationId) => (
    status.runtime_health?.timeline ?? []
).filter((event) => (
    event.type === "EMERGENCY"
    && event.operationId === operationId
));

const expectNoUnsafeRequests = (mock) => {
    expect(mock.getExternalRequests()).toEqual([]);
    expect(mock.getUnexpectedApiRequests()).toEqual([]);
};

const clickEmergencyConfirm = async (page) => {
    await page.getByRole(
        "button",
        {
            name: /EMERGENCY STOP/,
        },
    ).click();
    const dialog = page.getByRole(
        "dialog",
        {
            name: "Confirm emergency stop",
        },
    );
    await expect(dialog).toBeVisible();
    await dialog.getByRole(
        "button",
        {
            name: "CONFIRM EMERGENCY",
        },
    ).click();
};

const openRetryDialog = async (page) => {
    await page.getByRole(
        "button",
        {
            name: "安全状態を再確認",
        },
    ).click();
    const dialog = page.getByRole(
        "dialog",
        {
            name: "安全状態を再確認しますか？",
        },
    );
    await expect(dialog).toBeVisible();
    return dialog;
};

const openUnlockDialog = async (page) => {
    await page.getByRole(
        "button",
        {
            name: "緊急状態を解除",
        },
    ).click();
    const dialog = page.getByRole(
        "dialog",
        {
            name: "緊急状態を解除しますか？",
        },
    );
    await expect(dialog).toBeVisible();
    return dialog;
};

test.describe.configure({
    mode: "serial",
});

test.describe("Emergency Stop local-only E2E", () => {
    let mock;

    test.beforeEach(async ({ page }) => {
        mock = createEmergencyMock();
        await mock.install(page);
    });

    test.afterEach(async () => {
        expectNoUnsafeRequests(mock);
    });

    test("stopped paper emergency locks safely, records SUCCESS, and unlocks to READY", async ({
        page,
    }) => {
        await waitForDashboard(page);

        await expect(emergencyStateLabel(page)).toHaveText("READY");
        await expect(page.getByTestId("bot-state")).toHaveText("STOPPED");
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toHaveAttribute("aria-checked", "false");
        await expect(
            page.getByRole("switch", { name: "Toggle automatic trading" }),
        ).toHaveAttribute("aria-checked", "false");
        await expect(page.getByTestId("execution-mode")).toHaveText(
            "SIMULATION",
        );
        await expect(page.getByTestId("selected-mode")).toHaveText("PAPER");
        await expect(page.getByTestId("real-order-allowed")).toHaveText(
            "false",
        );

        const emergencyResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.emergency)
            && response.request().method() === "POST"
        ));
        await clickEmergencyConfirm(page);
        const emergencyResponse = await emergencyResponsePromise;
        expect(emergencyResponse.ok()).toBeTruthy();

        const emergencyResult = await emergencyResponse.json();
        expect(emergencyResult).toMatchObject({
            success: true,
            completed: true,
            partial: false,
            state_unknown: false,
            position_remaining: false,
            emergency_locked: true,
            auto_trade_disabled: true,
            retryable: false,
            path: "paper",
        });
        expect(emergencyResult.cancel.status).toBe("NOT_REQUIRED");
        expect(emergencyResult.flatten.status).toBe("NOT_REQUIRED");
        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(1);

        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        await expect(page.getByText("BOT STOPPED")).toBeVisible();
        await expect(page.getByText("EXECUTION DISABLED")).toBeVisible();
        await expect(page.getByText("OPEN ORDERS NONE")).toBeVisible();
        await expect(page.getByText("Execution path: PAPER")).toBeVisible();
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toHaveCount(0);
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toBeEnabled();

        const lockedStatus = mock.getStatus();
        const operationId = lockedStatus.emergency.lastResult.operationId;
        expect(lockedStatus.emergency).toMatchObject({
            active: true,
            locked: true,
            state: "LOCKED",
        });
        expect(lockedStatus.emergency.lastResult).toMatchObject({
            operationId,
            result: "SUCCESS",
            success: true,
            completed: true,
            stateUnknown: false,
            positionRemaining: false,
            path: "paper",
        });
        expect(lockedStatus.emergency.lastResult.cancelResult.status).toBe(
            "NOT_REQUIRED",
        );
        expect(lockedStatus.emergency.lastResult.flattenResult.status).toBe(
            "NOT_REQUIRED",
        );

        const unlockDialog = await openUnlockDialog(page);
        await expect(unlockDialog).toContainText(
            "解除後もBOTは起動しません。",
        );
        await expect(unlockDialog).toContainText(
            "LOOPとAUTO TRADEもOFFのままです。",
        );

        const unlockResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.unlock)
            && response.request().method() === "POST"
        ));
        await unlockDialog.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        ).click();
        const unlockResponse = await unlockResponsePromise;
        expect(unlockResponse.ok()).toBeTruthy();
        expect(await unlockResponse.json()).toMatchObject({
            success: true,
            unlocked: true,
            emergency_stop: false,
            emergency_state: "READY",
            execution_enabled: false,
        });
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(1);

        await expect(emergencyStateLabel(page)).toHaveText("READY");
        await expect(page.getByTestId("bot-state")).toHaveText("STOPPED");
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toHaveAttribute("aria-checked", "false");
        await expect(
            page.getByRole("switch", { name: "Toggle automatic trading" }),
        ).toHaveAttribute("aria-checked", "false");

        const finalStatus = mock.getStatus();
        expect(finalStatus.executionEnabled).toBe(false);
        expect(finalStatus.loopEnabled).toBe(false);
        expect(finalStatus.autoTradeEnabled).toBe(false);
        expect(finalStatus.status).toBe("STOPPED");
        expect(finalStatus.emergency).toMatchObject({
            active: false,
            locked: false,
            state: "READY",
        });
        expect(finalStatus.emergency.lastResult.operationId).toBe(operationId);
        expect(
            emergencyTimelineFor(finalStatus, operationId)
                .map((event) => event.event),
        ).toEqual([
            "EMERGENCY_STARTED",
            "EMERGENCY_COMPLETED",
            "EMERGENCY_UNLOCKED",
        ]);
    });

    test("emergency confirm cancel sends no API and keeps READY", async ({
        page,
    }) => {
        await waitForDashboard(page);

        await page.getByRole(
            "button",
            {
                name: /EMERGENCY STOP/,
            },
        ).click();
        const dialog = page.getByRole(
            "dialog",
            {
                name: "Confirm emergency stop",
            },
        );
        await expect(dialog).toBeVisible();
        await dialog.getByRole(
            "button",
            {
                name: "CANCEL",
            },
        ).click();

        await expect(dialog).toHaveCount(0);
        await expect(emergencyStateLabel(page)).toHaveText("READY");
        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(0);
        expect(mock.getStatus().runtime_health.timeline).toEqual([]);
    });

    test("PROCESSING state is displayed when backend status is processing", async ({
        page,
    }) => {
        mock.seedProcessing();

        await waitForDashboard(page);

        await expect(emergencyStateLabel(page)).toHaveText("PROCESSING");
        await expect(page.getByText("PROCESSING").first()).toBeVisible();
        await expect(
            page.getByRole("button", { name: /EMERGENCY STOP/ }),
        ).toBeDisabled();
    });

    test("ACTION_REQUIRED shows retry, hides unlock, and blocks emergency rerun", async ({
        page,
    }) => {
        mock.seedActionRequired({
            stateUnknown: true,
            positionRemaining: false,
        });

        await waitForDashboard(page);

        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        await expect(page.getByText("STATE UNKNOWN")).toBeVisible();
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toBeEnabled();
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toHaveCount(0);
        await expect(
            page.getByRole("button", { name: /EMERGENCY STOP/ }),
        ).toBeDisabled();
    });

    test("SNAPSHOT_STALE recheck converges to unlockable LOCKED state", async ({
        page,
    }) => {
        mock.setNextEmergencyOutcome("snapshot_stale");

        await waitForDashboard(page);
        await expect(page.getByTestId("bot-state")).toHaveText("STOPPED");
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toHaveAttribute("aria-checked", "false");
        await expect(
            page.getByRole("switch", { name: "Toggle automatic trading" }),
        ).toHaveAttribute("aria-checked", "false");

        const emergencyResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.emergency)
            && response.request().method() === "POST"
        ));
        await clickEmergencyConfirm(page);
        const emergencyResponse = await emergencyResponsePromise;
        expect(emergencyResponse.ok()).toBeTruthy();
        expect(await emergencyResponse.json()).toMatchObject({
            success: false,
            completed: false,
            partial: true,
            state_unknown: true,
            error_code: "SNAPSHOT_STALE",
            path: "paper",
        });

        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        await expect(page.getByText("SNAPSHOT_STALE")).toBeVisible();
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toBeEnabled();
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toHaveCount(0);

        const dialog = await openRetryDialog(page);
        const retryResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.retry)
            && response.request().method() === "POST"
        ));
        await dialog.getByRole(
            "button",
            {
                name: "再確認",
            },
        ).click();
        const retryResponse = await retryResponsePromise;
        expect(retryResponse.ok()).toBeTruthy();
        expect(await retryResponse.json()).toMatchObject({
            success: true,
            completed: true,
            partial: false,
            state_unknown: false,
            position_remaining: false,
            path: "paper",
        });

        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toHaveCount(0);
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toBeEnabled();
        expect(mock.getCallCount(ENDPOINTS.retry)).toBe(1);

        const unlockDialog = await openUnlockDialog(page);
        const unlockResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.unlock)
            && response.request().method() === "POST"
        ));
        await unlockDialog.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        ).click();
        const unlockResponse = await unlockResponsePromise;
        expect(unlockResponse.ok()).toBeTruthy();
        expect(await unlockResponse.json()).toMatchObject({
            success: true,
            unlocked: true,
            emergency_state: "READY",
            execution_enabled: false,
        });

        await expect(emergencyStateLabel(page)).toHaveText("READY");
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toBeEnabled();
        await expect(
            page.getByRole("switch", { name: "Toggle automatic trading" }),
        ).toBeDisabled();
        await expect(page.getByTestId("auto-trade-disabled-reason")).toContainText(
            "Loop must be running before Auto Trade can be enabled.",
        );
        expect(mock.getStatus().emergency).toMatchObject({
            locked: false,
            state: "READY",
        });
    });

    test("retry confirm cancel keeps ACTION_REQUIRED and operation id", async ({
        page,
    }) => {
        const operationId = mock.seedActionRequired();

        await waitForDashboard(page);

        const dialog = await openRetryDialog(page);
        await expect(dialog).toContainText(
            "注文とポジション状態を再確認し、",
        );
        await expect(dialog).toContainText(
            "必要なら緊急停止処理を再実行します。",
        );
        await expect(dialog).toContainText("BOT");
        await expect(dialog).toContainText("LOOP");
        await expect(dialog).toContainText("AUTO TRADE");
        await expect(dialog).toContainText("はOFFのままです。");
        await dialog.getByRole(
            "button",
            {
                name: "キャンセル",
            },
        ).click();

        await expect(dialog).toHaveCount(0);
        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        expect(mock.getCallCount(ENDPOINTS.retry)).toBe(0);
        expect(mock.getStatus().emergency.lastResult.operationId).toBe(
            operationId,
        );
    });

    test("retry success creates a new operation and converges to LOCKED SUCCESS", async ({
        page,
    }) => {
        const firstOperationId = mock.seedActionRequired();
        mock.setRouteDelay(ENDPOINTS.retry, 200);

        await waitForDashboard(page);
        const dialog = await openRetryDialog(page);

        const retryResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.retry)
            && response.request().method() === "POST"
        ));
        await dialog.getByRole(
            "button",
            {
                name: "再確認",
            },
        ).click();
        await expect(
            dialog.getByRole("button", { name: "再確認" }),
        ).toBeDisabled();
        const retryResponse = await retryResponsePromise;
        expect(retryResponse.ok()).toBeTruthy();
        expect(await retryResponse.json()).toMatchObject({
            success: true,
            completed: true,
            partial: false,
            state_unknown: false,
            position_remaining: false,
            path: "paper",
        });

        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toBeEnabled();
        expect(mock.getCallCount(ENDPOINTS.retry)).toBe(1);

        const lockedStatus = mock.getStatus();
        const retryOperationId = lockedStatus.emergency.lastResult.operationId;
        expect(retryOperationId).not.toBe(firstOperationId);
        expect(lockedStatus.emergency.lastResult).toMatchObject({
            operationId: retryOperationId,
            result: "SUCCESS",
            success: true,
            completed: true,
            stateUnknown: false,
            positionRemaining: false,
        });
        expect(
            emergencyTimelineFor(lockedStatus, firstOperationId)
                .map((event) => event.event),
        ).toEqual([
            "EMERGENCY_STARTED",
            "EMERGENCY_ACTION_REQUIRED",
        ]);
        expect(
            emergencyTimelineFor(lockedStatus, retryOperationId)
                .map((event) => event.event),
        ).toEqual([
            "EMERGENCY_STARTED",
            "EMERGENCY_COMPLETED",
        ]);
    });

    test("retry failure stays ACTION_REQUIRED and never shows unlock", async ({
        page,
    }) => {
        mock.seedActionRequired();
        mock.setNextRetryOutcome("failure");

        await waitForDashboard(page);
        const dialog = await openRetryDialog(page);

        const retryResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith(ENDPOINTS.retry)
            && response.request().method() === "POST"
        ));
        await dialog.getByRole(
            "button",
            {
                name: "再確認",
            },
        ).click();
        const retryResponse = await retryResponsePromise;
        expect(retryResponse.ok()).toBeTruthy();
        expect(await retryResponse.json()).toMatchObject({
            success: false,
            completed: false,
            partial: true,
            state_unknown: true,
            emergency_locked: true,
            retryable: true,
        });

        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toBeEnabled();
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toHaveCount(0);
        expect(mock.getStatus().emergency.state).toBe("ACTION_REQUIRED");
    });

    test("HTTP409 is not treated as success and converges to backend state", async ({
        page,
    }) => {
        mock.seedLockedSuccess();
        mock.queueHttpError(
            ENDPOINTS.unlock,
            409,
            "POSITION_REMAINING",
        );

        await waitForDashboard(page);
        const dialog = await openUnlockDialog(page);
        await dialog.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        ).click();

        await expect(page.getByTestId("emergency-unlock-error")).toContainText(
            "POSITION_REMAINING",
        );
        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(1);
        expect(mock.getStatus().emergency).toMatchObject({
            locked: true,
            state: "LOCKED",
        });
    });

    test("network errors do not fake emergency, retry, or unlock success", async ({
        page,
    }) => {
        mock.queueNetworkError(ENDPOINTS.emergency);
        await waitForDashboard(page);
        await clickEmergencyConfirm(page);

        await expect(page.getByTestId("emergency-error")).toContainText(
            "NETWORK_ERROR",
        );
        await expect(emergencyStateLabel(page)).toHaveText("READY");
        expect(mock.getStatus().emergency.state).toBe("READY");

        mock.reset();
        mock.seedActionRequired();
        mock.queueNetworkError(ENDPOINTS.retry);
        await page.reload();
        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        let dialog = await openRetryDialog(page);
        await dialog.getByRole(
            "button",
            {
                name: "再確認",
            },
        ).click();

        await expect(page.getByTestId("emergency-retry-error")).toContainText(
            "NETWORK_ERROR",
        );
        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        await expect(
            page.getByRole("button", { name: "安全状態を再確認" }),
        ).toBeEnabled();
        expect(mock.getStatus().emergency.state).toBe("ACTION_REQUIRED");

        mock.reset();
        mock.seedLockedSuccess();
        mock.queueNetworkError(ENDPOINTS.unlock);
        await page.reload();
        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        dialog = await openUnlockDialog(page);
        await dialog.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        ).click();

        await expect(page.getByTestId("emergency-unlock-error")).toContainText(
            "NETWORK_ERROR",
        );
        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        expect(mock.getStatus().emergency.state).toBe("LOCKED");
    });

    test("fast double submit is blocked for emergency, retry, and unlock", async ({
        page,
    }) => {
        mock.setRouteDelay(ENDPOINTS.emergency, 200);
        await waitForDashboard(page);
        await page.getByRole(
            "button",
            {
                name: /EMERGENCY STOP/,
            },
        ).click();
        let dialog = page.getByRole(
            "dialog",
            {
                name: "Confirm emergency stop",
            },
        );
        let confirmButton = dialog.getByRole(
            "button",
            {
                name: "CONFIRM EMERGENCY",
            },
        );
        await confirmButton.evaluate((button) => {
            button.click();
            button.click();
        });
        await expect(confirmButton).toBeDisabled();
        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(1);

        mock.reset();
        mock.seedActionRequired();
        mock.setRouteDelay(ENDPOINTS.retry, 200);
        await page.reload();
        await expect(emergencyStateLabel(page)).toHaveText("ACTION REQUIRED");
        dialog = await openRetryDialog(page);
        confirmButton = dialog.getByRole(
            "button",
            {
                name: "再確認",
            },
        );
        await confirmButton.evaluate((button) => {
            button.click();
            button.click();
        });
        await expect(confirmButton).toBeDisabled();
        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        expect(mock.getCallCount(ENDPOINTS.retry)).toBe(1);

        mock.reset();
        mock.seedLockedSuccess();
        mock.setRouteDelay(ENDPOINTS.unlock, 200);
        await page.reload();
        await expect(emergencyStateLabel(page)).toHaveText("STOPPED SAFELY");
        dialog = await openUnlockDialog(page);
        confirmButton = dialog.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        );
        await confirmButton.evaluate((button) => {
            button.click();
            button.click();
        });
        await expect(confirmButton).toBeDisabled();
        await expect(emergencyStateLabel(page)).toHaveText("READY");
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(1);
    });
});
