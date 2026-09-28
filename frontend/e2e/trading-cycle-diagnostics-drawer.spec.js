import { test, expect } from "@playwright/test";

const HARNESS = "/e2e/support/trading-cycle-diagnostics-harness.html";
const EVIDENCE_DIR = globalThis.process?.env?.G4_EVIDENCE_DIR || "/tmp/opencode";

const box = (locator) => locator.boundingBox();

// Geometry is measured only after the complete cycle and fonts are ready.
const waitForCycle = async (page) => {
    await expect(page.locator(".trading-cycle-stage-wrapper")).toHaveCount(15);
    await page.getByTestId("trading-cycle-step-14-toggle").waitFor();
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
};

const captureGeometry = async (page, testInfo, label) => {
    const geometry = await page.evaluate(() => {
        const rect = (node) => {
            const { x, y, width, height, right } = node.getBoundingClientRect();
            return { x, y, width, height, right };
        };
        const cells = Array.from(document.querySelectorAll(".trading-cycle-stage-wrapper"))
            .map((node) => ({ step: Number(node.dataset.stepIndex), ...rect(node) }));
        return {
            viewportWidth: window.innerWidth,
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
            fontStatus: document.fonts.status,
            cycle: rect(document.querySelector(".trading-cycle-flow")),
            rightmostStep: cells.reduce((a, b) => b.right > a.right ? b : a),
            cells,
        };
    });
    await testInfo.attach(label, { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
    console.log(`${label}: ${JSON.stringify(geometry)}`);
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1);
    return geometry;
};

test.describe("Trading Cycle diagnostics overlay drawer", () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(HARNESS);
        await waitForCycle(page);
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

test.describe("Trading Cycle left-aligned four-column layout", () => {
    const STEP_INDICES = Array.from({ length: 15 }, (_, index) => index);

    const stepWrapper = (page, index) => page.locator(`.trading-cycle-stage-wrapper[data-step-index="${index}"]`);

    for (const width of [1920, 1440, 1024]) {
        test(`rows are 0-3/4-7/8-11/12-14, left-aligned, no horizontal scroll at ${width}px`, async ({ page }) => {
            await page.setViewportSize({ width, height: 1000 });
            await page.goto(HARNESS);
            await waitForCycle(page);

            const rowOrder = await page.locator(".trading-cycle-row").evaluateAll((rows) =>
                rows.map((row) => Array.from(row.querySelectorAll(".trading-cycle-stage-wrapper"))
                    .map((node) => Number(node.dataset.stepIndex))),
            );
            expect(rowOrder).toEqual([
                [0, 1, 2, 3],
                [4, 5, 6, 7],
                [8, 9, 10, 11],
                [12, 13, 14],
            ]);

            // Same DOM order 0..14 as the canonical cycle.
            const domOrder = await page.locator(".trading-cycle-stage-wrapper").evaluateAll((nodes) =>
                nodes.map((node) => Number(node.dataset.stepIndex)),
            );
            expect(domOrder).toEqual(STEP_INDICES);

            // Left-aligned: STEP 0 sits near the panel's left inset and the
            // first column of every row shares the same x coordinate.
            const firstColumn = [];
            for (const first of [0, 4, 8, 12]) {
                const b = await stepWrapper(page, first).boundingBox();
                expect(b).not.toBeNull();
                firstColumn.push(b.x);
            }
            firstColumn.forEach((x) => expect(Math.abs(x - firstColumn[0])).toBeLessThanOrEqual(1));
            expect(firstColumn[0]).toBeLessThan(80);

            // Within a row x increases left-to-right; rows stack top-to-bottom.
            for (const row of rowOrder) {
                const boxes = await Promise.all(row.map((index) => stepWrapper(page, index).boundingBox()));
                for (let i = 1; i < boxes.length; i += 1) {
                    expect(boxes[i].x).toBeGreaterThan(boxes[i - 1].x + boxes[i - 1].width - 1);
                }
            }
            const rowTops = [];
            for (const first of [0, 4, 8, 12]) {
                const b = await stepWrapper(page, first).boundingBox();
                rowTops.push(b.y);
            }
            for (let i = 1; i < rowTops.length; i += 1) {
                expect(rowTops[i]).toBeGreaterThan(rowTops[i - 1]);
            }

            const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
            expect(overflow).toBeLessThanOrEqual(1);

            await page.screenshot({ path: `${EVIDENCE_DIR}/j4-E-${width}-4col-closed.png`, fullPage: true });
        });
    }

    test("STEP card coordinates never shift when the drawer opens and closes", async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(HARNESS);
        await waitForCycle(page);

        const indices = [0, 3, 4, 7, 8, 11, 12, 14];
        const measure = async () => {
            const result = {};
            for (const index of indices) {
                result[index] = await stepWrapper(page, index).boundingBox();
            }
            return result;
        };

        const before = await measure();
        await page.getByTestId("trading-cycle-step-4-toggle").click();
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toBeVisible();
        const open = await measure();
        await page.screenshot({ path: `${EVIDENCE_DIR}/j4-F-1440-step4-open.png`, fullPage: true });

        await page.keyboard.press("Escape");
        await expect(page.getByTestId("trading-cycle-diagnostics-drawer")).toHaveCount(0);
        const closed = await measure();

        for (const index of indices) {
            expect(Math.abs(open[index].x - before[index].x)).toBeLessThanOrEqual(1);
            expect(Math.abs(open[index].y - before[index].y)).toBeLessThanOrEqual(1);
            expect(Math.abs(closed[index].x - before[index].x)).toBeLessThanOrEqual(1);
            expect(Math.abs(closed[index].y - before[index].y)).toBeLessThanOrEqual(1);
        }
    });

    test("the rightmost STEP DETAILS clear the open drawer at 1920 and 1440", async ({ page }, testInfo) => {
        for (const width of [1920, 1440]) {
            await page.setViewportSize({ width, height: 1000 });
            await page.goto(HARNESS);
            await waitForCycle(page);
            await page.getByTestId("trading-cycle-step-4-toggle").click();
            const drawer = page.getByTestId("trading-cycle-diagnostics-drawer");
            await expect(drawer).toBeVisible();
            const drawerBox = await drawer.boundingBox();
            const geometry = await captureGeometry(page, testInfo, `clearance-${width}`);
            console.log(`clearance-${width}: drawerLeft=${drawerBox.x}, gap=${drawerBox.x - geometry.rightmostStep.right}`);
            await page.screenshot({ path: `${EVIDENCE_DIR}/j4-clearance-${width}.png`, fullPage: true });

            for (const index of [3, 7, 11, 14]) {
                const b = await stepWrapper(page, index).boundingBox();
                expect(b.x + b.width).toBeLessThanOrEqual(drawerBox.x + 1);
                await page.getByTestId(`trading-cycle-step-${index}-toggle`).click({ trial: true });
            }

            await page.keyboard.press("Escape");
            await expect(drawer).toHaveCount(0);
        }
    });

    test("narrower viewports wrap without horizontal scroll and keep STEP order", async ({ page }, testInfo) => {
        for (const width of [820, 700, 560]) {
            await page.setViewportSize({ width, height: 900 });
            await page.goto(HARNESS);
            await waitForCycle(page);

            const domOrder = await page.locator(".trading-cycle-stage-wrapper").evaluateAll((nodes) =>
                nodes.map((node) => Number(node.dataset.stepIndex)),
            );
            expect(domOrder).toEqual(STEP_INDICES);

            await captureGeometry(page, testInfo, `narrow-${width}`);
            await page.screenshot({ path: `${EVIDENCE_DIR}/j4-narrow-${width}.png`, fullPage: true });
        }
    });
});


test('historical evidence is labeled and does not move the four-column cycle', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${HARNESS}?historical=1`);
    await waitForCycle(page);
    const flow = page.locator('.trading-cycle-flow');
    const before = await box(flow);
    await page.getByTestId('trading-cycle-step-4-toggle').click();
    const drawer = page.getByTestId('trading-cycle-diagnostics-drawer');
    await expect(drawer).toContainText('EVALUATION: HISTORICAL');
    await expect(drawer).toContainText('CYCLE_A');
    await expect(drawer).toContainText('STALE (32400s)');
    const retained = page.getByTestId('retained-evaluation');
    await expect(retained).toContainText('LIQUIDITY_INSTABILITY');
    await expect(retained).toContainText('liquiditySafe: false / priceDifference: 0');
    await expect(retained).toContainText('expected: true');
    await expect(drawer.locator('.step-diagnostics__reason')).not.toContainText('LIQUIDITY');
    await expect(drawer).not.toContainText('THIS STEP (ROOT BLOCKER)');
    expect(await box(flow)).toEqual(before);
});
