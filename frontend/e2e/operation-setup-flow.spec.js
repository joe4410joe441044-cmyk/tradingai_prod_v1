import { expect, test } from "@playwright/test";
import { createEmergencyMock, ENDPOINTS } from "./support/emergencyMock.js";

test("Operation presents five-step setup before current runtime state without mutations", async ({ page }) => {
    const mock = createEmergencyMock();
    await mock.install(page);
    await page.goto("/");
    const flow = page.getByTestId("operation-setup-flow");
    await expect(flow).toBeVisible();
    const headings = flow.locator(".operation-step-heading");
    await expect(headings).toHaveCount(5);
    await expect(headings).toHaveText(["1TRADING MODE", "2MARKET SELECTION", "3RISK SETTINGS", "4AUTOMATION", "5READY / START"]);
    await expect(flow.getByRole("button", { name: "START BOT" })).toHaveCount(1);
    await expect(page.getByText("CURRENT RUNTIME STATE", { exact: false })).toBeVisible();
    await expect(page.getByText("EMERGENCY", { exact: true })).toBeVisible();
    await expect(page.getByRole("switch", { name: "Toggle trading loop" })).toBeDisabled();
    await expect(page.getByRole("switch", { name: "Toggle automatic trading" })).toBeDisabled();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    expect(mock.getCallCount(ENDPOINTS.botStart)).toBe(0);
    expect(mock.getCallCount(ENDPOINTS.execution)).toBe(0);
    expect(mock.getExternalRequests()).toEqual([]);
    expect(mock.getUnexpectedApiRequests()).toEqual([]);
});
