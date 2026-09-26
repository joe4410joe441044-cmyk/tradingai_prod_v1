import { test, expect } from "@playwright/test";

const HARNESS = "/e2e/support/mi-bilingual-harness.html";
const EVIDENCE_DIR = globalThis.process?.env?.G6_EVIDENCE_DIR || "/tmp/opencode";

const overflowedCriticalValues = (page) => page.evaluate(() => (
    Array.from(document.querySelectorAll(".ams-field--wrap .ams-field-value"))
        .filter((element) => element.scrollWidth > element.clientWidth + 1)
        .map((element) => element.textContent)
));

test.describe("Market Intelligence bilingual labels", () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(HARNESS);
    });

    test("MARKET VIEW / DOM / RECENT TRADES labels carry Japanese accompaniment", async ({ page }) => {
        const market = page.locator(".mi-market-view");
        for (const label of [
            "MARKET VIEW / 市場情報", "CURRENT PRICE / 現在価格",
            "BEST BID / 最良買値", "BEST ASK / 最良売値", "SPREAD / スプレッド",
            "ORDER BOOK / DOM（板情報）", "RECENT TRADES（約定履歴）",
            "TIME (LOCAL) / 時刻", "Price / 価格", "Size / 数量", "Total / 累積",
            "Marker / マーカー", "ROWS / 行数", "BOTH / 両方", "ASKS / 売板",
        ]) {
            await expect(market.getByText(label, { exact: false }).first()).toBeVisible();
        }
        await expect(market).toContainText("KUCOIN");
        await expect(market).toContainText("XRPUSDTM");

        const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(pageOverflow).toBeLessThanOrEqual(1);
        await page.screenshot({ path: `${EVIDENCE_DIR}/g6-market-view-bilingual.png`, fullPage: true });
    });

    test("AUTO MARKET SELECTION essential and DETAILS / DIAGNOSTICS are bilingual", async ({ page }) => {
        const card = page.getByTestId("auto-market-selection-card");
        for (const label of [
            "AUTO MARKET SELECTION / 自動市場選定",
            "ACTIVE SYMBOL / 現在銘柄",
            "TOP CANDIDATE / 最有力候補 · PREVIEW",
            "LAST EVALUATED / 最終評価",
            "CAPITAL / 資金", "AVAILABLE CAPITAL / 利用可能資金", "RISK BUDGET / リスク予算",
            "CURRENT REASONS / 現在の理由",
            "DETAILS / DIAGNOSTICS / 詳細・診断",
        ]) {
            await expect(card.getByText(label, { exact: false }).first()).toBeVisible();
        }
        await expect(page.getByTestId("auto-market-selection-details")).toHaveCount(0);
        expect(await overflowedCriticalValues(page)).toEqual([]);
        await page.screenshot({ path: `${EVIDENCE_DIR}/g6-ams-collapsed.png`, fullPage: true });

        await page.getByTestId("auto-market-selection-details-toggle").click();
        const details = page.getByTestId("auto-market-selection-details");
        await expect(details).toBeVisible();
        for (const label of [
            "SELECTION MODE / 選定モード", "NEXT REQUESTED SYMBOL / 次回要求銘柄",
            "AUTO RUNTIME MODE / 自動実行モード", "CYCLE STATUS / サイクル状態",
            "SCANNER / スキャナー", "RANKING / ランキング", "CAPITAL DETAILS / 資金詳細",
            "SYMBOL SWITCH / 銘柄切替", "LAST CYCLE REASONS / 前回サイクルの理由",
            "REMAINING EXPOSURE / 残り許容エクスポージャー", "MM REGIME / MM運用状態",
        ]) {
            await expect(details.getByText(label, { exact: false }).first()).toBeVisible();
        }
        await expect(details).toContainText("CAPITAL_PROTECTION_STANDARD");
        await expect(details).toContainText("MM_STALE");
        expect(await overflowedCriticalValues(page)).toEqual([]);
        const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(pageOverflow).toBeLessThanOrEqual(1);
        await page.screenshot({ path: `${EVIDENCE_DIR}/g6-ams-details-expanded.png`, fullPage: true });
    });
});
