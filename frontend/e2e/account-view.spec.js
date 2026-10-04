import { test, expect } from "@playwright/test";

const widths = [1920, 1440, 700];

for (const width of widths) {
    test(`account view switch PAPER/REAL ${width}`, async ({ page }) => {
        const apiRequests = [];
        await page.route(url => url.pathname.startsWith("/api/"), route => {
            apiRequests.push({ url: route.request().url(), method: route.request().method() });
            return route.abort();
        });
        await page.setViewportSize({ width, height: 1400 });
        await page.goto("/e2e/support/account-view-harness.html");

        const switchNode = page.getByTestId("account-view-switch");
        await expect(switchNode).toBeVisible();
        const paperOption = page.getByTestId("account-view-option-paper");
        const realOption = page.getByTestId("account-view-option-live");
        await expect(paperOption).toHaveText("PAPER");
        await expect(realOption).toHaveText("REAL");
        await expect(realOption).not.toHaveText("LIVE");

        // PAPER view is the initial default (selectedMode = PAPER).
        await expect(paperOption).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByTestId("account-view-header")).toContainText("PAPER ACCOUNT");
        await expect(page.getByTestId("financial-equity-value")).toHaveText("10,000.00");
        await expect(page.getByTestId("current-position-card")).toContainText("PAPERPOSUSDT");
        await expect(page.getByTestId("last-position-event-card")).toContainText("PAPEREVENT");

        // Switch to REAL — display only.
        await realOption.click();
        await expect(realOption).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByTestId("account-view-header")).toContainText("REAL / LIVE ACCOUNT");
        await expect(page.getByTestId("financial-equity-value")).toHaveText("7.92");
        await expect(page.getByTestId("current-position-card")).toContainText("REALPOSUSDTM");
        await expect(page.getByTestId("last-position-event-card")).toContainText("REALEVENT");

        // Global runtime/context never switch with ACCOUNT VIEW.
        await expect(page.getByTestId("runtime-mode")).toHaveText("PAPER");
        await expect(page.getByTestId("live-context-mode")).toHaveText("PAPER");
        await expect(page.getByTestId("live-context-execution")).toHaveText("NOT ALLOWED");

        // Switch back to PAPER.
        await paperOption.click();
        await expect(page.getByTestId("account-view-header")).toContainText("PAPER ACCOUNT");
        await expect(page.getByTestId("financial-equity-value")).toHaveText("10,000.00");

        // Layout: no horizontal scroll, switch inside the viewport, no overlap
        // with the READ ONLY badge / page header.
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
        const switchBox = await switchNode.boundingBox();
        const badgeBox = await page.locator(".as-page-badge").boundingBox();
        expect(switchBox.x).toBeGreaterThanOrEqual(0);
        expect(switchBox.x + switchBox.width).toBeLessThanOrEqual(width);
        if (width > 560) {
            expect(switchBox.y).toBeGreaterThanOrEqual(badgeBox.y + badgeBox.height - 1);
        }

        // No mutation on switch; the harness performs no API traffic at all.
        expect(apiRequests.filter(request => ["POST", "PUT", "PATCH", "DELETE"].includes(request.method))).toEqual([]);
        expect(apiRequests).toEqual([]);

        await page.screenshot({ path: `/tmp/cp63-account-view-${width}.png`, fullPage: true });
    });
}
