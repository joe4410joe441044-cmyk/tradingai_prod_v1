import { expect, test } from "@playwright/test";

import { createEmergencyMock, ENDPOINTS } from "./support/emergencyMock.js";

const liveDialog = (page) => page.getByRole("dialog", { name: "Confirm LIVE start" });
const modeGroup = (page) => page.getByRole("group", { name: "Trading mode" });
const startButton = (page) => page.getByRole("button", { name: "START BOT" });

const expectNetworkClean = (mock) => {
    expect(mock.getExternalRequests()).toEqual([]);
    expect(mock.getUnexpectedApiRequests()).toEqual([]);
};

const waitForDashboard = async (page, mock, { paperStartEnabled = true } = {}) => {
    await page.goto("/");
    await expect(modeGroup(page)).toBeVisible();
    await expect(page.getByTestId("ready-start-step").getByText("BOT STOPPED", { exact: true })).toBeVisible();
    await expect(page.getByText("MM RUNTIME").locator("..")).toContainText("RUNNING");
    await expect(page.getByText("CAPITAL AUTHORITY").locator("..")).toContainText("AVAILABLE");
    await expect.poll(() => mock.getCallCount(ENDPOINTS.status)).toBeGreaterThan(0);
    await expect.poll(() => mock.getCallCount(ENDPOINTS.mmConfig)).toBeGreaterThan(0);
    await expect.poll(() => mock.getCallCount(ENDPOINTS.mmStatus)).toBeGreaterThan(0);
    await expect(startButton(page))[paperStartEnabled ? "toBeEnabled" : "toBeDisabled"]();
    expectNetworkClean(mock);
};

const chooseMode = async (page, mode) => {
    const button = modeGroup(page).getByRole("button", { name: mode, exact: true });
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
};

const openLiveDialog = async (page, mock) => {
    await chooseMode(page, "LIVE");
    await startButton(page).click();
    await expect(liveDialog(page)).toBeVisible();
    expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
};

test.describe.configure({ mode: "serial" });

test.describe("LIVE Start Confirmation Modal local-only E2E", () => {
    let mock;
    let pageErrors;

    test.beforeEach(async ({ page }) => {
        mock = createEmergencyMock();
        pageErrors = [];
        page.on("pageerror", (error) => pageErrors.push(error.message));
        await mock.install(page);
    });

    test.afterEach(async () => {
        expect(pageErrors).toEqual([]);
        expectNetworkClean(mock);
    });

    test("1 PAPER START is direct and sends exactly one request", async ({ page }) => {
        await waitForDashboard(page, mock);
        await chooseMode(page, "PAPER");
        await startButton(page).click();
        await expect(liveDialog(page)).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(1);
    });

    test("2 LIVE click opens modal and sends zero requests", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
    });

    test("LIVE BLOCKED keeps trigger enabled and exposes formal block reason", async ({ page }) => {
        mock.setLiveAuthorityAllowed(false);
        await waitForDashboard(page, mock);
        await chooseMode(page, "LIVE");
        await expect(startButton(page)).toBeEnabled();
        await startButton(page).click();
        const dialog = liveDialog(page);
        await expect(dialog).toBeVisible();
        await expect(dialog.getByText("START READINESS:").locator("..")).toContainText("BLOCKED");
        await expect(dialog.getByText("LIVE AUTHORITY: BLOCKED")).toBeVisible();
        await expect(dialog.getByText("現在はLIVEを開始できません。")).toBeVisible();
        await expect(dialog.getByRole("button", { name: "LIVEを開始" })).toBeDisabled();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
        await dialog.getByRole("button", { name: "キャンセル" }).click();
        await expect(dialog).toBeHidden();
    });

    test("3 cancel closes modal and sends zero requests", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        await liveDialog(page).getByRole("button", { name: "キャンセル" }).click();
        await expect(liveDialog(page)).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("4 Escape closes modal and sends zero requests", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        await page.keyboard.press("Escape");
        await expect(liveDialog(page)).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("5 backdrop closes modal and sends zero requests", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        await liveDialog(page).click({ position: { x: 4, y: 4 } });
        await expect(liveDialog(page)).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("6 Enter alone never confirms LIVE START", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        await expect(liveDialog(page).getByRole("button", { name: "キャンセル" })).toBeFocused();
        await page.keyboard.press("Enter");
        await expect(liveDialog(page)).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("7 explicit confirm sends authoritative LIVE payload once", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        await liveDialog(page).getByRole("button", { name: "LIVEを開始" }).click();
        await expect.poll(() => mock.getCallCount(ENDPOINTS.botStart)).toBe(1);
        const [request] = mock.getRequests(ENDPOINTS.botStart);
        expect(request.method).toBe("POST");
        expect(request.path).toBe(ENDPOINTS.botStart);
        expect(request.body).toMatchObject({
            mode: "live",
            selection_mode: "AUTO",
            symbol: "XRPUSDTM",
            risk_percent: 0.5,
            leverage: 5,
        });
        await expect(liveDialog(page)).toBeHidden();
    });

    test("8 double confirm remains single-flight", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        await liveDialog(page).getByRole("button", { name: "LIVEを開始" }).dblclick();
        await expect.poll(() => mock.getCallCount(ENDPOINTS.botStart)).toBe(1);
    });

    test("9 authority change after open fails closed", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        const statusCount = mock.getCallCount(ENDPOINTS.status);
        mock.setEmergencyUnsafe();
        await expect.poll(() => mock.getCallCount(ENDPOINTS.status)).toBeGreaterThan(statusCount);
        await expect(
            liveDialog(page).getByRole("button", { name: "LIVEを開始" }),
        ).toBeDisabled();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("10 LIVE to PAPER closes modal without request", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        const paperButton = modeGroup(page).getByRole("button", { name: "PAPER", exact: true });
        await paperButton.evaluate((button) => button.click());
        await expect(paperButton).toHaveAttribute("aria-pressed", "true");
        await expect(liveDialog(page)).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("11 bot RUNNING closes an open modal", async ({ page }) => {
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        const statusCount = mock.getCallCount(ENDPOINTS.status);
        mock.setBotRunning();
        await expect.poll(() => mock.getCallCount(ENDPOINTS.status)).toBeGreaterThan(statusCount);
        await expect(liveDialog(page)).toBeHidden();
    });

    test("authority BLOCKED to READY updates confirm without request", async ({ page }) => {
        mock.setLiveAuthorityAllowed(false);
        await waitForDashboard(page, mock);
        await openLiveDialog(page, mock);
        const confirm = liveDialog(page).getByRole("button", { name: "LIVEを開始" });
        await expect(confirm).toBeDisabled();
        const statusCount = mock.getCallCount(ENDPOINTS.status);
        mock.setLiveAuthorityAllowed(true);
        await expect.poll(() => mock.getCallCount(ENDPOINTS.status)).toBeGreaterThan(statusCount);
        await expect(confirm).toBeEnabled();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("12 emergency lock prevents confirm request", async ({ page }) => {
        mock.setEmergencyUnsafe();
        await waitForDashboard(page, mock, { paperStartEnabled: false });
        await openLiveDialog(page, mock);
        await expect(
            liveDialog(page).getByRole("button", { name: "LIVEを開始" }),
        ).toBeDisabled();
        await expect(liveDialog(page).getByText("EMERGENCY: BLOCKED")).toBeVisible();
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });

    test("13 STOP remains direct and never opens LIVE modal", async ({ page }) => {
        await waitForDashboard(page, mock);
        await startButton(page).click();
        await expect(page.getByRole("button", { name: "STOP BOT" })).toBeVisible();
        await page.getByRole("button", { name: "STOP BOT" }).click();
        await expect.poll(() => mock.getCallCount(ENDPOINTS.botStop)).toBe(1);
        await expect(liveDialog(page)).toBeHidden();
    });

    test("14 Emergency and LIVE modals keep state and requests separate", async ({ page }) => {
        await waitForDashboard(page, mock);
        await page.getByRole("button", { name: "EMERGENCY STOP" }).click();
        const emergencyDialog = page.getByRole("dialog", { name: "Confirm emergency stop" });
        await expect(emergencyDialog).toBeVisible();
        await expect(liveDialog(page)).toBeHidden();
        await emergencyDialog.getByRole("button", { name: "CANCEL" }).click();
        await openLiveDialog(page, mock);
        await expect(emergencyDialog).toBeHidden();
        expect(mock.getCallCount(ENDPOINTS.emergency)).toBe(0);
        expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    });
});
