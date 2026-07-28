import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMoneyManagementConfigurationPayload,
  configurationDraftFromAuthoritative,
  createSafeMoneyManagementStatus,
  MoneyManagementContractError,
  normalizeConfigurationUpdateResponse,
  normalizeMoneyManagementConfiguration,
  normalizeMoneyManagementStatus,
  normalizeRecoveryResponse,
  validateMoneyManagementConfigurationDraft,
} from "./moneyManagementContracts.js";
import {
  validConfiguration,
  validRecoveryResponse,
  validStatus,
  validUpdateResponse,
} from "./moneyManagementFixtures.js";

test("valid status preserves Decimal strings, reason order, and revisions", () => {
  const raw = validStatus({
    riskState: "CAUTION",
    warningReasons: [
      "WEEKLY_LOSS_WARNING",
      "DAILY_LOSS_WARNING",
    ],
    metrics: {
      ...validStatus().metrics,
      dailyPnl: "-12.50",
      equity: null,
      availableCapital: null,
      exposureLimit: null,
    },
  });
  const status = normalizeMoneyManagementStatus(raw);
  assert.equal(status.metrics.dailyPnl, "-12.50");
  assert.equal(status.metrics.equity, null);
  assert.equal(status.metrics.availableCapital, null);
  assert.equal(status.metrics.exposureLimit, null);
  assert.deepEqual(status.warningReasons, [
    "WEEKLY_LOSS_WARNING",
    "DAILY_LOSS_WARNING",
  ]);
  assert.equal(status.revision, 11);
  assert.equal(status.sequence, 12);
  assert.equal(typeof status.metrics.dailyPnl, "string");
});

test("unknown enum is retained as UNKNOWN with diagnostics and fail closed", () => {
  const raw = normalizeMoneyManagementStatus(
    validStatus({ riskState: "FUTURE_RISK_STATE" }),
  );
  assert.equal(raw.riskState, "UNKNOWN");
  assert.ok(raw.diagnosticReasons.includes("UNKNOWN_RISK_STATE"));
  const safe = createSafeMoneyManagementStatus(raw, {
    pollingState: "RUNNING",
  });
  assert.equal(safe.available, false);
  assert.equal(safe.executionEntryAllowed, false);
});

test("missing required fields, invalid timestamps, and reason shapes reject", () => {
  const missing = validStatus();
  delete missing.available;
  for (const raw of [
    missing,
    validStatus({ generatedAt: "2026-02-30T00:00:00Z" }),
    validStatus({ warningReasons: "DAILY_LOSS_WARNING" }),
    validStatus({
      metrics: {
        ...validStatus().metrics,
        dailyPnl: 0,
      },
    }),
  ]) {
    assert.throws(
      () => normalizeMoneyManagementStatus(raw),
      MoneyManagementContractError,
    );
  }
});

test("unavailable, inconsistent, stale, and polling stop states fail closed", () => {
  const cases = [
    normalizeMoneyManagementStatus(
      validStatus({ metrics: null }),
    ),
    normalizeMoneyManagementStatus(
      validStatus({
        metricsStatus: "PARTIAL",
        metrics: {
          ...validStatus().metrics,
          status: "PARTIAL",
          equity: null,
        },
      }),
    ),
    normalizeMoneyManagementStatus(
      validStatus({
        configurationRevision: 8,
      }),
    ),
    normalizeMoneyManagementStatus(
      validStatus({ enabled: false }),
    ),
    normalizeMoneyManagementStatus(
      validStatus({ lifecycleState: "STOPPED" }),
    ),
    normalizeMoneyManagementStatus(
      validStatus({
        riskState: "LOCKED",
        executionEntryAllowed: true,
      }),
    ),
    normalizeMoneyManagementStatus(
      validStatus({
        riskState: "LOCKED",
        recommendedAction: "CONTINUE",
        executionEntryAllowed: false,
        projectionStatus: "BLOCK",
      }),
    ),
  ];
  for (const raw of cases) {
    const safe = createSafeMoneyManagementStatus(raw, {
      pollingState: "RUNNING",
    });
    assert.equal(safe.executionEntryAllowed, false);
  }
  const valid = normalizeMoneyManagementStatus(validStatus());
  for (const client of [
    { pollingState: "RUNNING", clientStale: true },
    { pollingState: "RUNNING", requestFailed: true },
    { pollingState: "STOPPED" },
    { pollingState: "RUNNING", configurationUpdating: true },
    { pollingState: "RUNNING", recoveryRunning: true },
    { pollingState: "RUNNING", configurationConflict: true },
  ]) {
    const safe = createSafeMoneyManagementStatus(valid, client);
    assert.equal(safe.riskState, "UNKNOWN");
    assert.equal(safe.executionEntryAllowed, false);
  }
});

test("configuration normalization and payload retain string decimals", () => {
  const configuration = normalizeMoneyManagementConfiguration(
    validConfiguration(),
  );
  const draft = configurationDraftFromAuthoritative(configuration);
  const payload = buildMoneyManagementConfigurationPayload(
    draft,
    configuration.revision,
  );
  assert.equal(payload.dailyWarningPercent, "1.00");
  assert.equal(payload.maximumDrawdownPercent, "5.00");
  assert.equal(payload.totalExposurePercent, "20.00");
  assert.equal(typeof payload.dailyWarningPercent, "string");
  assert.equal(payload.expectedRevision, 7);
});

test("configuration validation matches Backend strict threshold contract", () => {
  const valid = configurationDraftFromAuthoritative(
    normalizeMoneyManagementConfiguration(validConfiguration()),
  );
  const invalidValues = [
    "",
    " ",
    "-1",
    "101",
    "NaN",
    "Infinity",
    "1e2",
    1,
  ];
  for (const value of invalidValues) {
    assert.equal(
      validateMoneyManagementConfigurationDraft(
        { ...valid, dailyWarningPercent: value },
        7,
      ).valid,
      false,
    );
  }
  for (const dailyWarningPercent of ["1.50", "2.00"]) {
    assert.equal(
      validateMoneyManagementConfigurationDraft(
        {
          ...valid,
          dailyWarningPercent,
          dailyBlockPercent: "1.50",
        },
        7,
      ).valid,
      false,
    );
  }
  assert.equal(
    validateMoneyManagementConfigurationDraft(valid, null).valid,
    false,
  );
  assert.equal(
    validateMoneyManagementConfigurationDraft(valid, 7).valid,
    true,
  );
});

test("update and recovery response contracts distinguish no-op recovery", () => {
  const update = normalizeConfigurationUpdateResponse(
    validUpdateResponse(),
  );
  assert.equal(update.configuration.revision, 8);
  const recovered = normalizeRecoveryResponse(validRecoveryResponse());
  assert.equal(recovered.outcome, "RECOVERED");
  const noOp = normalizeRecoveryResponse(
    validRecoveryResponse({ safeReason: "ALREADY_EVALUATED" }),
  );
  assert.equal(noOp.outcome, "ALREADY_EVALUATED");
});
