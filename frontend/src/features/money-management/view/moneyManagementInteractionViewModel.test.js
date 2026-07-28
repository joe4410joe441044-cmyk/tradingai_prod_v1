import assert from "node:assert/strict";
import test from "node:test";

import {
  createMoneyManagementInteractionViewModel,
  MONEY_MANAGEMENT_CONFIGURATION_FIELDS,
} from "./moneyManagementInteractionViewModel.js";

const configuration = Object.freeze({
  available: true,
  enabled: true,
  dailyWarningPercent: "1.0000",
  dailyBlockPercent: "2.0000",
  weeklyWarningPercent: "3.0000",
  weeklyBlockPercent: "4.0000",
  monthlyWarningPercent: "5.0000",
  monthlyBlockPercent: "6.0000",
  maximumDrawdownPercent: "7.0000",
  totalExposurePercent: "20.0000",
  revision: 12,
  source: "DEFAULT",
  updatedAt: "2026-07-26T14:32:08Z",
});

const draft = Object.freeze({
  enabled: true,
  dailyWarningPercent: "1.0000",
  dailyBlockPercent: "2.0000",
  weeklyWarningPercent: "3.0000",
  weeklyBlockPercent: "4.0000",
  monthlyWarningPercent: "5.0000",
  monthlyBlockPercent: "6.0000",
  maximumDrawdownPercent: "7.0000",
  totalExposurePercent: "20.0000",
});

const safeStatus = Object.freeze({
  available: true,
  lifecycleState: "RUNNING",
  riskState: "NORMAL",
  projectionStatus: "ALLOW",
  executionEntryAllowed: true,
  revision: 5,
});

const base = Object.freeze({
  configuration,
  configurationDraft: draft,
  pollingState: "RUNNING",
  status: safeStatus,
});

test("configuration fields exactly match the backend editable contract", () => {
  assert.deepEqual(
    MONEY_MANAGEMENT_CONFIGURATION_FIELDS.map(({ key }) => key),
    [
      "enabled",
      "dailyWarningPercent",
      "dailyBlockPercent",
      "weeklyWarningPercent",
      "weeklyBlockPercent",
      "monthlyWarningPercent",
      "monthlyBlockPercent",
      "maximumDrawdownPercent",
      "totalExposurePercent",
    ],
  );
});

test("draft comparison is exact and preserves decimal strings", () => {
  const exact = createMoneyManagementInteractionViewModel(base);
  assert.equal(exact.configuration.draftStatus, "SAVED");
  assert.match(
    exact.configuration.saveDisabledReason,
    /no unsaved changes/,
  );

  const changed = createMoneyManagementInteractionViewModel({
    ...base,
    configurationDraft: {
      ...draft,
      dailyWarningPercent: "1.00000",
    },
  });
  assert.equal(changed.configuration.draftStatus, "UNSAVED CHANGES");
  assert.equal(changed.configuration.saveDisabledReason, null);
});

test("invalid decimal and missing revision disable save without coercion", () => {
  for (const value of [
    "",
    "-1234.5000",
    "0",
    "9007199254740993.123456789",
  ]) {
    const model = createMoneyManagementInteractionViewModel({
      ...base,
      configurationDraft: {
        ...draft,
        dailyWarningPercent: value,
      },
    });
    assert.match(
      model.configuration.fieldErrors.dailyWarningPercent,
      /decimal|Warning/,
    );
    assert.match(model.configuration.saveDisabledReason, /invalid/);
  }

  const missingRevision = createMoneyManagementInteractionViewModel({
    ...base,
    configuration: { ...configuration, revision: null },
  });
  assert.match(
    missingRevision.configuration.saveDisabledReason,
    /revision is unknown/,
  );
});

test("configuration conflict preserves and compares exact draft values", () => {
  const model = createMoneyManagementInteractionViewModel({
    ...base,
    configurationDraft: {
      ...draft,
      maximumDrawdownPercent: "6.5000",
    },
    configurationConflict: { active: true },
  });
  assert.equal(model.configuration.conflict.rows.length, 1);
  assert.deepEqual(model.configuration.conflict.rows[0], {
    key: "maximumDrawdownPercent",
    label: "Maximum Drawdown",
    backendValue: "7.0000",
    draftValue: "6.5000",
  });
});

test("save, recovery, and refresh are mutually exclusive", () => {
  for (const flag of [
    "isUpdatingConfiguration",
    "isRecovering",
    "isManualRefreshing",
  ]) {
    const model = createMoneyManagementInteractionViewModel({
      ...base,
      configurationDraft: {
        ...draft,
        maximumDrawdownPercent: "8.0000",
      },
      [flag]: true,
    });
    assert.ok(model.configuration.saveDisabledReason);
    assert.ok(model.recovery.disabledReason);
    assert.ok(model.refresh.disabledReason);
  }
});

test("stale and stopped status disable recovery fail closed", () => {
  const stale = createMoneyManagementInteractionViewModel({
    ...base,
    isClientStale: true,
  });
  assert.match(stale.recovery.disabledReason, /stale/);

  const stopped = createMoneyManagementInteractionViewModel({
    ...base,
    pollingState: "STOPPED",
  });
  assert.match(stopped.recovery.disabledReason, /polling is stopped/);
});

test("recovery result keeps backend safeReason without success coercion", () => {
  const model = createMoneyManagementInteractionViewModel({
    ...base,
    recoveryResult: {
      accepted: true,
      recovered: false,
      safeReason: "PARTIAL",
      generatedAt: "2026-07-26T14:32:08Z",
    },
  });
  assert.equal(model.recovery.result.result, "PARTIAL");
  assert.equal(model.recovery.result.recovered, "NO");
  assert.equal(model.recovery.result.updated, "14:32:08");
});
