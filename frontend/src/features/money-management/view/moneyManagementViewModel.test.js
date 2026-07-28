import assert from "node:assert/strict";
import test from "node:test";

import {
  createMoneyManagementViewModel,
  displayDecimal,
  formatMoneyManagementTime,
} from "./moneyManagementViewModel.js";

const status = (overrides = {}) => ({
  available: true,
  clientSafeReason: null,
  diagnosticReasons: [],
  executionEntryAllowed: true,
  generatedAt: "2026-07-26T14:32:08.123456Z",
  holdReasons: [],
  lifecycleState: "RUNNING",
  blockReasons: [],
  metrics: {
    status: "AVAILABLE",
    equity: "9007199254740993.123456789",
    availableCapital: "8007199254740993.123456789",
    peakEquity: "9007199254741000.00000000",
    drawdownAmount: "6.876543211",
    drawdownPercent: "0.00000001",
    dailyPnl: "-1234.5000",
    weeklyPnl: "12.5000",
    monthlyPnl: "40.0000",
    openExposure: "0.00000001",
    exposureLimit: "25.0000",
    exposureUtilization: "12.5000",
    openPositionState: "OPEN",
    riskUtilization: null,
  },
  projectionStatus: "ALLOW",
  recommendedAction: "CONTINUE",
  riskState: "NORMAL",
  warningReasons: [],
  configuration: {
    maximumDrawdownPercent: "5.0000",
    totalExposurePercent: "20.0000",
  },
  ...overrides,
});

const readyInput = (overrides = {}) => ({
  consecutiveFailures: 0,
  isClientStale: false,
  isInitialLoading: false,
  pollingState: "RUNNING",
  status: status(),
  ...overrides,
});

test("Decimal display preserves precision, sign, and scale without Number conversion", () => {
  for (const value of [
    "9007199254740993.123456789",
    "0.00000001",
    "-1234.5000",
  ]) {
    assert.equal(displayDecimal(value, "USDT").text, value);
  }
  for (const value of [null, undefined, 0, "NaN", "1e4"]) {
    const displayed = displayDecimal(value);
    assert.equal(displayed.text, "—");
    assert.equal(displayed.unavailable, true);
  }
});

test("all risk states retain their label and fail-safe visual hierarchy", () => {
  const cases = [
    ["NORMAL", "CONTINUE", true, "safe", "ENTRY ALLOWED"],
    ["CAUTION", "CONTINUE", true, "warning", "ENTRY ALLOWED"],
    [
      "DEFENSIVE",
      "HOLD_NEW_ENTRIES",
      false,
      "warning",
      "NEW ENTRIES ON HOLD",
    ],
    [
      "LOCKED",
      "BLOCK_EXECUTION",
      false,
      "danger",
      "ENTRY BLOCKED",
    ],
    ["UNKNOWN", "UNKNOWN", false, "danger", "ENTRY STATUS UNKNOWN"],
  ];
  for (const [riskState, action, allowed, variant, entry] of cases) {
    const model = createMoneyManagementViewModel(readyInput({
      status: status({
        executionEntryAllowed: allowed,
        projectionStatus: allowed ? "ALLOW" : "BLOCK",
        recommendedAction: action,
        riskState,
      }),
    }));
    assert.equal(model.riskState.state.text, riskState);
    assert.equal(model.riskState.state.variant, variant);
    assert.equal(model.riskState.entryPermission.text, entry);
  }
});

test("stale, stopped, update, recovery, and conflict never display ENTRY ALLOWED", () => {
  const unsafeInputs = [
    { isClientStale: true },
    { pollingState: "STOPPED" },
    { isUpdatingConfiguration: true },
    { isRecovering: true },
    { configurationConflict: { active: true } },
    { statusError: { code: "NETWORK_ERROR" } },
  ];
  for (const unsafe of unsafeInputs) {
    const model = createMoneyManagementViewModel(
      readyInput(unsafe),
    );
    assert.equal(model.riskState.state.text, "UNKNOWN");
    assert.equal(model.riskState.entryPermission.text, "ENTRY BLOCKED");
    assert.notEqual(model.projection.current.text, "ALLOW");
  }
});

test("reason groups remain separate, ordered, and block reason is primary", () => {
  const model = createMoneyManagementViewModel(readyInput({
    status: status({
      warningReasons: [
        "WEEKLY_LOSS_WARNING",
        "DAILY_LOSS_WARNING",
      ],
      holdReasons: ["MULTIPLE_LOSS_WARNINGS"],
      blockReasons: ["DAILY_LOSS_BLOCK", "DRAWDOWN_BLOCK"],
      diagnosticReasons: ["CASH_FLOW_PRESENT"],
    }),
  }));
  assert.deepEqual(model.riskState.reasons.warning.items, [
    "WEEKLY_LOSS_WARNING",
    "DAILY_LOSS_WARNING",
  ]);
  assert.deepEqual(model.riskState.reasons.hold.items, [
    "MULTIPLE_LOSS_WARNINGS",
  ]);
  assert.deepEqual(model.riskState.reasons.block.items, [
    "DAILY_LOSS_BLOCK",
    "DRAWDOWN_BLOCK",
  ]);
  assert.deepEqual(model.riskState.reasons.diagnostic.items, [
    "CASH_FLOW_PRESENT",
  ]);
  assert.equal(model.riskState.primaryReason, "DAILY_LOSS_BLOCK");
});

test("null metrics remain unavailable and never become zero", () => {
  const model = createMoneyManagementViewModel(readyInput({
    status: status({ metrics: null }),
  }));
  for (const metric of [
    ...model.exposure,
    ...model.capital,
    ...model.performance,
    ...model.statistics.slice(0, 5),
  ]) {
    assert.notEqual(metric.value.text, "0");
  }
  assert.equal(model.performance[0].value.text, "—");
  assert.equal(model.statistics.at(-1).value.text, "UNKNOWN");
});

test("actual Backend metrics are mapped without invented projections", () => {
  const model = createMoneyManagementViewModel(readyInput());
  assert.equal(model.exposure[1].value.text, "25.0000");
  assert.equal(model.exposure[1].value.unit, "%");
  assert.equal(model.exposure[2].value.text, "12.5000");
  assert.equal(model.exposure[2].value.unit, "%");
  assert.equal(model.exposure[3].value.text, "OPEN");
  assert.equal(model.capital[0].value.text, "9007199254740993.123456789");
  assert.equal(model.capital[1].value.text, "8007199254740993.123456789");
  assert.equal(model.performance[0].value.text, "-1234.5000");
  assert.equal(model.performance[3].value.text, "0.00000001");
  assert.equal(model.statistics[1].value.text, "5.0000");
  assert.equal(model.statistics[2].value.text, "Not reported");
  assert.equal(model.statistics[4].value.text, "—");
  assert.equal(model.projection.current.text, "ALLOW");
  assert.match(model.projection.description, /later phase/);
});

test("unknown Exposure Limit remains unavailable", () => {
  const model = createMoneyManagementViewModel(readyInput({
    status: status({
      metrics: {
        ...status().metrics,
        exposureLimit: null,
      },
    }),
  }));

  assert.equal(model.exposure[1].value.text, "—");
  assert.equal(model.exposure[1].value.unavailable, true);
  assert.equal(model.exposure[1].value.unit, null);
});

test("runtime metric values and unknowns use safe existing displays", () => {
  const populated = createMoneyManagementViewModel(readyInput({
    status: status({
      metrics: {
        ...status().metrics,
        exposureUtilization: "42.50",
        openPositionState: "FLAT",
        riskUtilization: "37.25",
      },
    }),
  }));
  assert.equal(populated.exposure[2].value.text, "42.50");
  assert.equal(populated.exposure[3].value.text, "FLAT");
  assert.equal(populated.statistics[4].value.text, "37.25");

  const unknown = createMoneyManagementViewModel(readyInput({
    status: status({
      metrics: {
        ...status().metrics,
        exposureUtilization: null,
        openPositionState: "UNKNOWN",
        riskUtilization: null,
      },
    }),
  }));
  assert.equal(unknown.exposure[2].value.text, "—");
  assert.equal(unknown.exposure[3].value.text, "UNKNOWN");
  assert.equal(unknown.statistics[4].value.text, "—");
});

test("unknown Available Capital remains unavailable", () => {
  const model = createMoneyManagementViewModel(readyInput({
    status: status({
      metrics: {
        ...status().metrics,
        availableCapital: null,
      },
    }),
  }));

  assert.equal(model.capital[1].value.text, "—");
  assert.equal(model.capital[1].value.unavailable, true);
});

test("header exposes connection, polling, updated time, and unknown mode safely", () => {
  const model = createMoneyManagementViewModel(readyInput());
  assert.equal(model.header.mode.text, "UNKNOWN MODE");
  assert.equal(model.header.connection.text, "CONNECTED");
  assert.equal(model.header.updated, "Updated 14:32:08");
  assert.equal(model.header.refreshDisabled, false);
  assert.equal(model.runtime[2].value.text, "ACTIVE");
  assert.equal(
    formatMoneyManagementTime("2026-07-26T14:32:08Z"),
    "14:32:08",
  );

  const degraded = createMoneyManagementViewModel(readyInput({
    consecutiveFailures: 1,
  }));
  assert.equal(degraded.header.connection.text, "DEGRADED");
  assert.equal(degraded.runtime[2].value.text, "BACKOFF");
});

test("projection conflict is presented as conflict and blocked", () => {
  const model = createMoneyManagementViewModel(readyInput({
    status: status({
      available: false,
      clientSafeReason: "PROJECTION_INCONSISTENT",
      executionEntryAllowed: false,
      projectionStatus: "BLOCK",
      recommendedAction: "UNKNOWN",
      riskState: "UNKNOWN",
    }),
  }));
  assert.equal(model.riskState.protectionLevel, "CONTRACT CONFLICT");
  assert.equal(model.riskState.entryPermission.text, "ENTRY BLOCKED");
});

test("loading, unavailable, stale, and updating banners are explicit", () => {
  const cases = [
    [{ isInitialLoading: true }, "Loading"],
    [{ statusError: { code: "INVALID_RESPONSE" } }, "MONEY MANAGEMENT UNAVAILABLE"],
    [{ isClientStale: true }, "STALE DATA — ENTRY BLOCKED"],
    [
      { isUpdatingConfiguration: true },
      "CONFIGURATION UPDATE IN PROGRESS",
    ],
  ];
  for (const [input, banner] of cases) {
    const model = createMoneyManagementViewModel(readyInput(input));
    assert.equal(model.banner, banner);
  }
});
