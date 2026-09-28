import { test, expect } from "@playwright/test";

const HARNESS = "/e2e/support/trading-cycle-diagnostics-harness.html";
const EVIDENCE_DIR = globalThis.process?.env?.G4_EVIDENCE_DIR || "/tmp/opencode";

const box = (locator) => locator.boundingBox();

test.describe("Trading Cycle diagnostics overlay drawer", () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(HARNESS);
        await page.getByTestId("trading-cycle-step-4-toggle").waitFor();
    });

    test("DETAILS opens a right-side overlay without moving the Trading Cycle", async ({ page }) => {
        const flow = page.locator(".trading-cycle-flow");
        const step4 = page.getByTestId("trading-cycle-step-4-toggle");

        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(0);
        const beforeFlow = await box(flow);
        const beforeStep = await box(step4);
        await page.screenshot({ path: `${EVIDENCE_DIR}/j4-A-drawer-closed.png`, fullPage: true });

        await step4.click();
        const drawer = page.getByTestId("trading-cycle-diagnostics-drawer");
        await expect(drawer).toBeVisible();
        await expect(drawer.getByText("TRADING CYCLE DIAGNOSTICS")).toBeVisible();
        await expect(drawer).toContainText("STEP 4");
        await expect(drawer).toContainText("Micro Edge Strategy");
        await expect(drawer).toContainText("STATUS: BLOCKED");
        for (const label of [
            "WHY", "CURRENT", "REQUIRED", "COMPARISON", "ROOT BLOCKER",
            "BLOCKER TYPE", "OPERATOR ACTION", "RELATED PARAMETER",
            "NEXT CONDITION", "NEXT STEP", "SOURCE", "FRESHNESS",
        ]) {
            await expect(drawer.getByText(label, { exact: false }).first()).toBeVisible();
        }
        await expect(drawer).toContainText("THIS STEP (ROOT BLOCKER)");

        // The drawer must clear the sticky app header, not hide under it.
        const headerBox = await box(page.locator(".app-header"));
        const drawerInitial = await box(drawer);
        expect(drawerInitial.y).toBeGreaterThanOrEqual(headerBox.y + headerBox.height - 1);

        await page.screenshot({ path: `${EVIDENCE_DIR}/j4-B-step4-open.png`, fullPage: true });

        const afterFlow = await box(flow);
        const afterStep = await box(step4);
        expect(Math.abs(afterFlow.x - beforeFlow.x)).toBeLessThanOrEqual(1);
        expect(Math.abs(afterFlow.y - beforeFlow.y)).toBeLessThanOrEqual(1);
        expect(Math.abs(afterFlow.width - beforeFlow.width)).toBeLessThanOrEqual(1);
        expect(Math.abs(afterFlow.height - beforeFlow.height)).toBeLessThanOrEqual(1);
        expect(Math.abs(afterStep.x - beforeStep.x)).toBeLessThanOrEqual(1);
        expect(Math.abs(afterStep.y - beforeStep.y)).toBeLessThanOrEqual(1);

        const drawerBox = await box(drawer);
        const viewport = page.viewportSize();
        expect(drawerBox.x).toBeGreaterThan(viewport.width / 2);
        expect(drawerBox.x + drawerBox.width).toBeLessThanOrEqual(viewport.width + 1);

        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow).toBeLessThanOrEqual(1);
    });

    test("STEP 9 switches the same single drawer; Escape and CLOSE reset the cycle", async ({ page }) => {
        await page.getByTestId("trading-cycle-step-4-toggle").click();
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(1);

        await page.getByTestId("trading-cycle-step-9-toggle").click();
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(1);
        await expect(page.locator("#trading-cycle-drawer-title")).toContainText("STEP 9");
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toContainText("WAITING FOR STEP 4");
        await page.screenshot({ path: `${EVIDENCE_DIR}/j4-C-step9-open.png`, fullPage: true });

        await page.keyboard.press("Escape");
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(0);

        await page.getByTestId("trading-cycle-step-4-toggle").click();
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(1);
        await page.getByTestId("trading-cycle-drawer-close").click();
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(0);
        await page.screenshot({ path: `${EVIDENCE_DIR}/j4-D-drawer-closed-again.png`, fullPage: true });
    });
});
