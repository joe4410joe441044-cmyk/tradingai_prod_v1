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

    test("Emergency locks, permanent Return button unlocks to READY, and trading stays OFF", async ({
        page,
    }) => {
        await waitForDashboard(page);

        const returnButton = page.getByRole(
            "button",
            { name: "通常に戻す" },
        );
        await expect(emergencyStateLabel(page)).toHaveText("READY");
        await expect(returnButton).toBeVisible();
        await expect(returnButton).toBeDisabled();
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

        await expect(emergencyStateLabel(page)).toHaveText("READY");
        await expect(returnButton).toBeVisible();
        await expect(returnButton).toBeDisabled();
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toBeEnabled();
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toHaveAttribute("aria-checked", "false");
        await expect(
            page.getByRole("switch", { name: "Toggle automatic trading" }),
        ).toHaveAttribute("aria-checked", "false");

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

        await waitForDashboard(page);

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
        await expect(emergencyStateLabel(page)).toHaveText("READY");
        await expect(returnButton).toBeDisabled();
        expect(mock.getCallCount(ENDPOINTS.unlock)).toBe(2);
        expect(mock.getStatus()).toMatchObject({
            loopEnabled: false,
            autoTradeEnabled: false,
            executionEnabled: false,
        });
    });
});
