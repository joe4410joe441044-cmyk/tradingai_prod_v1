import { expect, test } from "@playwright/test";

import { createEmergencyMock } from "./support/emergencyMock.js";

const readiness = {
    available: true,
    schemaVersion: 1,
    strategy: "MicrostructureEdgeStrategy",
    strategyDecision: "HOLD",
    candidateDirection: "SELL",
    executionAllowed: false,
    edgeScore: 0.3322,
    confidence: 0.1661,
    blockingCondition: "LIQUIDITY_QUALITY",
    suppressionReason: "LIQUIDITY_DETERIORATION",
    cycleId: "visual-cycle",
    evaluatedAt: "2026-08-08T12:00:00Z",
    conditions: [
        ["SPREAD", "PASS", 0.00001, 0.0005, "<=", 0, "MEASURED"],
        ["SPREAD_VOLATILITY", "PASS", 0, 0.65, "<=", 0, "MEASURED"],
        ["LIQUIDITY_QUALITY", "FAIL", 0.0936, 0.35, ">=", 0.2564, "MEASURED"],
        ["LIQUIDITY_VOLUME", "FAIL", 9362, 35000, ">=", 25638, "DERIVED"],
        ["MOMENTUM", "FAIL", 0, 0.5, ">=", 0.5, "MEASURED"],
        ["PRESSURE_ALIGNMENT", "PASS", 0.4715, 0.15, ">=", 0, "DERIVED"],
        ["EDGE", "FAIL", 0.3322, 0.55, ">=", null, "DERIVED"],
        ["CONFIDENCE", "FAIL", 0.1661, 0.6, ">=", null, "DERIVED"],
        ["ABSORPTION", "PASS", false, null, null, null, "MEASURED", false],
        ["STAGNANT_FLOW", "PASS", false, null, null, null, "MEASURED", false],
        ["FAKE_PRESSURE", "PASS", false, null, null, null, "MEASURED", false],
        ["LIQUIDITY_SAFETY", "PASS", true, null, null, null, "DERIVED", true],
    ].map(([code, status, currentValue, threshold, operator, delta, sourceStatus, expected]) => ({
        code, status, currentValue, threshold, operator, delta, sourceStatus, expected,
    })),
};

test("entry readiness remains compact and readable at desktop widths", async ({ page }) => {
    const mock = createEmergencyMock();
    mock.setTradingDecision({
        mode: "PAPER", exchange: "KUCOIN", realOrderAllowed: false,
        finalDecision: "HOLD", currentState: "WAITING FOR SIGNAL",
        blockingStage: "PYTHON STRATEGY", blockingReason: "LIQUIDITY_DETERIORATION",
        entryReadinessAvailable: true, entryReadiness: readiness,
        stages: {
            market: { status: "PASS" },
            pythonStrategy: { status: "HOLD", decision: "HOLD", confidence: 0.1661, executionAllowed: false },
            aiReview: { status: "NOT TRIGGERED" }, moneyManagement: { status: "NOT REACHED" },
            governance: { status: "NOT REACHED" },
            execution: { status: "NO ORDER", orderState: "NONE", positionState: "FLAT" },
        },
    });
    await mock.install(page);
    const consoleErrors = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });

    for (const width of [1280, 1440, 1920]) {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto("/");
        const card = page.locator(".trading-decision-card");
        const entry = card.locator(".entry-readiness");
        await expect(card).toBeVisible();
        await expect(entry.getByText(/^Candidate/)).toContainText("SELL");
        await expect(entry.getByText(/^Liquidity$/)).toBeVisible();
        await expect(entry.getByText("0.0936 / >=0.3500", { exact: true })).toBeVisible();
        await expect(entry.getByText(/^Liquidity Safety$/)).toBeVisible();
        const metrics = await card.evaluate((node) => ({ width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height, scrollWidth: node.scrollWidth }));
        expect(metrics.scrollWidth).toBeLessThanOrEqual(Math.ceil(metrics.width));
        expect(metrics.height).toBeLessThan(700);
    }
    expect(consoleErrors).toEqual([]);
    mock.assertNetworkClean(expect);
});
