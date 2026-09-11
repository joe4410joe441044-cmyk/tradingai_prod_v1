import { expect, test } from "@playwright/test";
import { createEmergencyMock } from "./support/emergencyMock.js";

const ENDPOINT = "/api/bot/paper-account/capital";

test("Account Status submits the confirmed canonical Paper Capital", async ({ page }) => {
    const mock = createEmergencyMock();
    await mock.install(page);

    const status = mock.getStatus();
    status.accountRuntime.paperAccount.balance = 100;
    status.accountRuntime.paperAccount.equity = 100;
    status.accountRuntime.paperAccount.availableBalance = 100;
    status.accountRuntime.realAccount = {
        connected: true,
        authenticated: true,
        stale: false,
        loading: false,
        positions: [],
        balance: 7.91836966,
        equity: 7.91836966,
        availableBalance: 7.91836966,
        positionSummary: "NO_OPEN_POSITION",
    };
    status.realAccountConnected = true;
    status.realAvailableBalance = 7.91836966;

    const requests = [];
    await page.route("**/api/bot/status", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(status),
        });
    });
    await page.route(`**${ENDPOINT}`, async (route) => {
        requests.push({
            body: route.request().postDataJSON(),
            contentType: route.request().headers()["content-type"],
            method: route.request().method(),
            pathname: new URL(route.request().url()).pathname,
        });
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                success: true,
                paperBalance: Number(requests.at(-1).body.capital),
            }),
        });
    });

    await page.goto("/account-status");
    await page.getByRole("button", { name: /SET PAPER CAPITAL/ }).click();

    const input = page.getByLabel(/SIMULATION CAPITAL/);
    const apply = page.getByRole("button", { name: /APPLY PAPER CAPITAL/ });

    await input.fill("100.00");
    await apply.click();
    await expect(page.getByText("New Simulation Capital: 100.00 USDT")).toBeVisible();
    await page.getByRole("button", { name: "Reset Paper Account" }).click();

    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]).toEqual({
        body: { capital: "100.00", source: "DASHBOARD_MANUAL" },
        contentType: "application/json",
        method: "POST",
        pathname: ENDPOINT,
    });

    await page.getByRole("button", { name: /REAL AVAILABLE/ }).click();
    await expect(input).toHaveValue("7.92");
    await apply.click();
    await expect(page.getByText("New Simulation Capital: 7.92 USDT")).toBeVisible();
    await page.getByRole("button", { name: "Reset Paper Account" }).click();

    await expect.poll(() => requests.length).toBe(2);
    expect(requests[1].body).toEqual({
        capital: "7.92",
        source: "REAL_AVAILABLE_PRESET",
    });

    await input.fill("100.001");
    await expect(page.getByText("Enter a valid amount with up to 2 decimal places.")).toBeVisible();
    await expect(apply).toBeDisabled();
    expect(requests).toHaveLength(2);
    expect(requests[0].body.capital).toBe("100.00");
    expect(requests[1].body.capital).toBe("7.92");
    mock.assertNetworkClean(expect);
});
