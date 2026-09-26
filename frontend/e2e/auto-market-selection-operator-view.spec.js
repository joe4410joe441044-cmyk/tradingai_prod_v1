import { test, expect } from "@playwright/test";

const HARNESS = "/e2e/support/ams-operator-view-harness.html";
const EVIDENCE_DIR = process.env.G5_EVIDENCE_DIR || "/tmp/opencode";

const overflowedCriticalValues = (page) => page.evaluate(() => (
    Array.from(document.querySelectorAll(".ams-field--wrap .ams-field-value"))
        .filter((element) => element.scrollWidth > element.clientWidth + 1)
        .map((element) => element.textContent)
));

test.describe("AUTO MARKET SELECTION operator view", () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(HARNESS);
    });

    test("essential view shows full critical values with diagnostics collapsed", async ({ page }) => {
        const essential = page.getByTestId("auto-market-selection-essential");
        await expect(essential).toBeVisible();
        await expect(essential.getByText("ACTIVE SYMBOL")).toBeVisible();
        await expect(essential.getByText("DYMUSDT").first()).toBeVisible();
        await expect(essential.getByText("TOP CANDIDATE · PREVIEW")).toBeVisible();
        await expect(essential.getByText("MEWUSDT")).toBeVisible();
        await expect(essential.getByText("OBSERVING")).toBeVisible();
        await expect(essential.getByText("LAST EVALUATED")).toBeVisible();
        await expect(page.getByTestId("auto-market-selection-reselect")).toBeVisible();
        await expect(page.getByTestId("auto-market-selection-capital-summary")).toContainText("7.9184");
        await expect(page.getByTestId("auto-market-selection-capital-summary")).toContainText("0.0396");
        await expect(page.getByTestId("auto-market-selection-current-reasons")).toBeVisible();

        await expect(page.getByTestId("auto-market-selection-details")).toHaveCount(0);
        await expect(page.getByText("SCANNER", { exact: true })).toHaveCount(0);
        await expect(page.getByText("SYMBOL SWITCH", { exact: true })).toHaveCount(0);
        await expect(page.getByText("LAST CYCLE REASONS", { exact: true })).toHaveCount(0);

        expect(await overflowedCriticalValues(page)).toEqual([]);
        const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(pageOverflow).toBeLessThanOrEqual(1);

        await page.screenshot({ path: `${EVIDENCE_DIR}/g5-essential-collapsed.png`, fullPage: true });
    });

    test("details expand to reveal full runtime, scanner, ranking, capital, switch, freshness and history", async ({ page }) => {
        await page.getByTestId("auto-market-selection-details-toggle").click();
        const details = page.getByTestId("auto-market-selection-details");
        await expect(details).toBeVisible();
        await expect(details.getByText("NEXT REQUESTED SYMBOL")).toBeVisible();
        await expect(details.getByText("XRPUSDTM")).toBeVisible();
        await expect(details.getByText("LIVE_READ_ONLY")).toBeVisible();
        await expect(details.getByText("CAPITAL_PROTECTION_STANDARD")).toBeVisible();
        await expect(details.getByText("SCANNER", { exact: true })).toBeVisible();
        await expect(details.getByText("RANKING", { exact: true })).toBeVisible();
        await expect(details.getByText("CAPITAL DETAILS", { exact: true })).toBeVisible();
        await expect(details.getByText("SYMBOL SWITCH", { exact: true })).toBeVisible();
        await expect(details.getByText("LAST CYCLE REASONS", { exact: true })).toBeVisible();

        expect(await overflowedCriticalValues(page)).toEqual([]);
        await page.screenshot({ path: `${EVIDENCE_DIR}/g5-details-expanded.png`, fullPage: true });

        await page.getByTestId("auto-market-selection-details-toggle").click();
        await expect(page.getByTestId("auto-market-selection-details")).toHaveCount(0);
    });

    test("critical symbol and mode values are not CSS-ellipsized", async ({ page }) => {
        await page.getByTestId("auto-market-selection-details-toggle").click();
        const targets = ["DYMUSDT", "MEWUSDT", "XRPUSDTM", "LIVE_READ_ONLY", "CAPITAL_PROTECTION_STANDARD"];
        for (const value of targets) {
            const clipped = await page.evaluate((needle) => {
                const candidates = Array.from(document.querySelectorAll(".ams-field--wrap .ams-field-value"));
                const match = candidates.find((element) => element.textContent === needle);
                if (!match) return null;
                const style = getComputedStyle(match);
                return {
                    ellipsis: style.textOverflow,
                    content: match.scrollWidth > match.clientWidth + 1,
                };
            }, value);
            expect(clipped, `${value} must render in a critical wrap field`).not.toBeNull();
            expect(clipped.content, `${value} must not be visually truncated`).toBe(false);
        }
    });
});
