import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readSource = (name) =>
  readFile(new URL(`./${name}`, import.meta.url), "utf8");

test("configuration card renders accessible string-preserving inputs", async () => {
  const source = await readSource("MoneyManagementConfigurationCard.jsx");
  assert.match(source, /htmlFor=\{inputId\}/);
  assert.match(source, /type="checkbox"/);
  assert.match(source, /type="text"/);
  assert.match(source, /inputMode="decimal"/);
  assert.match(source, /aria-invalid/);
  assert.match(source, /Reset Draft/);
  assert.match(source, /Save Configuration/);
  assert.match(source, /CONFIGURATION CONFLICT/);
  assert.doesNotMatch(
    source,
    /Number\(|parseFloat\(|parseInt\(|valueAsNumber|Math\.round\(/,
  );
});

test("recovery card requires inline confirmation and distinguishes conflict", async () => {
  const source = await readSource("MoneyManagementRecoveryCard.jsx");
  assert.match(source, /Run Recovery Evaluation/);
  assert.match(source, /Confirm Recovery/);
  assert.match(source, /Cancel/);
  assert.match(source, /RECOVERY CONFLICT/);
  assert.match(source, /Last Recovery Result/);
  assert.doesNotMatch(source, /<dialog|modal/iu);
});

test("manual refresh control reports safe failure and disables duplicates", async () => {
  const source = await readSource(
    "MoneyManagementManualRefreshControl.jsx",
  );
  assert.match(source, /disabled=\{Boolean\(disabledReason\)\}/);
  assert.match(source, /Last known values may be outdated/);
  assert.match(source, /Entry is blocked/);
  assert.match(source, /role="alert"/);
});

test("position size preview is explicit and has no order action", async () => {
  const source = await readSource("MoneyManagementPositionSizingCard.jsx");
  assert.match(source, /Calculate Position Size/);
  assert.match(source, /effectiveCostPercent/);
  assert.match(source, /quantityStep/);
  assert.match(source, /contractMultiplier/);
  assert.match(source, /Recommended Notional/);
  assert.match(source, /Preview only（確認のみ）— No order is created\./);
  assert.doesNotMatch(source, /submitOrder|createOrder|placeOrder/);
  assert.doesNotMatch(
    source,
    /Number\(|parseFloat\(|parseInt\(|valueAsNumber|Math\.round\(/,
  );
});

test("simulation renders deterministic inputs, summary, and two charts", async () => {
  const source = await readSource("MoneyManagementSimulationCard.jsx");
  for (const label of [
    "Initial Capital",
    "Number of Trades",
    "Win Rate",
    "Average Win",
    "Average Loss",
    "Risk per Trade",
    "Maximum Drawdown",
    "Fees",
    "Slippage",
    "Compounding",
    "Scenario",
    "Final Capital",
    "Recovery Required",
    "Capital Curve",
    "Drawdown Curve",
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /Not calculated/);
  assert.match(source, /No projection data/);
  assert.match(
    source,
    /Deterministic preview only（決定論的な試算のみ）— No runtime\s+or order changes\./,
  );
});

test("runtime history has filters, pagination, empty state, and four charts", async () => {
  const source = await readSource("MoneyManagementRuntimeHistoryCard.jsx");
  for (const label of [
    "Runtime History",
    "Event Type",
    "State",
    "Display Count",
    "Load More",
    "Refresh",
    "No runtime history yet（実行履歴データはまだありません）",
    "Capital / Equity History",
    "Drawdown History",
    "Exposure Utilization History",
    "Risk Utilization History",
  ]) {
    assert.match(source, new RegExp(label.replace(/[/.]/g, "\\$&")));
  }
  assert.match(source, /connectNulls=\{false\}/);
  assert.match(
    source,
    /Runtime events only（実行イベントのみ）— Simulation excluded\./,
  );
  assert.match(source, /hasChartData/);
});
