import {
  validateMoneyManagementConfigurationDraft,
} from "../contracts/moneyManagementContracts.js";
import {
  MONEY_MANAGEMENT_ERROR_CODE,
} from "../utils/moneyManagementErrors.js";
import { formatMoneyManagementTime } from "./moneyManagementViewModel.js";

export const MONEY_MANAGEMENT_CONFIGURATION_FIELDS = Object.freeze([
  Object.freeze({
    key: "enabled",
    label: "Money Management Enabled",
    type: "boolean",
  }),
  Object.freeze({
    key: "dailyWarningPercent",
    label: "Daily Warning",
    type: "decimal",
  }),
  Object.freeze({
    key: "dailyBlockPercent",
    label: "Daily Block",
    type: "decimal",
  }),
  Object.freeze({
    key: "weeklyWarningPercent",
    label: "Weekly Warning",
    type: "decimal",
  }),
  Object.freeze({
    key: "weeklyBlockPercent",
    label: "Weekly Block",
    type: "decimal",
  }),
  Object.freeze({
    key: "monthlyWarningPercent",
    label: "Monthly Warning",
    type: "decimal",
  }),
  Object.freeze({
    key: "monthlyBlockPercent",
    label: "Monthly Block",
    type: "decimal",
  }),
  Object.freeze({
    key: "maximumDrawdownPercent",
    label: "Maximum Drawdown",
    type: "decimal",
  }),
  Object.freeze({
    key: "totalExposurePercent",
    label: "Total Exposure Limit",
    type: "decimal",
  }),
]);

const VALIDATION_MESSAGES = Object.freeze({
  INVALID_BOOLEAN: "A boolean value is required.",
  INVALID_PERCENTAGE: "Enter a decimal greater than 0 and at most 100.",
  WARNING_MUST_BE_BELOW_BLOCK:
    "Warning must be below the corresponding block value.",
  DAILY_BLOCK_MUST_BE_BELOW_WEEKLY:
    "Daily block must be below weekly block.",
  WEEKLY_BLOCK_EXCEEDS_MONTHLY:
    "Weekly block must not exceed monthly block.",
  MONTHLY_BLOCK_MUST_BE_BELOW_DRAWDOWN:
    "Monthly block must be below maximum drawdown.",
});

const displayValue = (value) => {
  if (value === null || value === undefined) return "Not reported";
  if (typeof value === "boolean") return value ? "Enabled" : "Disabled";
  return String(value);
};

const displayBoolean = (value) => value === true ? "YES" : "NO";

function draftIsDirty(configuration, draft) {
  if (!configuration || !draft) return false;
  return MONEY_MANAGEMENT_CONFIGURATION_FIELDS.some(
    ({ key }) => configuration[key] !== draft[key],
  );
}

function operationReason(input) {
  if (input.isUpdatingConfiguration) {
    return "configuration update is in progress";
  }
  if (input.isRecovering) return "recovery is in progress";
  if (input.isManualRefreshing) return "refresh is in progress";
  return null;
}

function statusSafetyReason(input) {
  if (input.statusError) return "status is unavailable";
  if (input.isClientStale) return "status data is stale";
  if (input.pollingState !== "RUNNING") return "polling is stopped";
  if (!input.status?.available) return "backend status is unavailable";
  if (input.status.lifecycleState !== "RUNNING") {
    return "lifecycle is not running";
  }
  if (input.status.riskState === "UNKNOWN") return "risk state is unknown";
  if (input.status.projectionStatus === "UNKNOWN") {
    return "projection is unknown";
  }
  return null;
}

function conflictRows(configuration, draft) {
  if (!configuration || !draft) return Object.freeze([]);
  return Object.freeze(
    MONEY_MANAGEMENT_CONFIGURATION_FIELDS
      .filter(({ key }) => configuration[key] !== draft[key])
      .map(({ key, label }) => Object.freeze({
        key,
        label,
        backendValue: displayValue(configuration[key]),
        draftValue: displayValue(draft[key]),
      })),
  );
}

export function createMoneyManagementInteractionViewModel(input = {}) {
  const configuration = input.configuration ?? null;
  const draft = input.configurationDraft ?? null;
  const revision = configuration?.revision ?? null;
  const validation = validateMoneyManagementConfigurationDraft(
    draft,
    revision,
  );
  const dirty = draftIsDirty(configuration, draft);
  const activeOperationReason = operationReason(input);
  const safetyReason = statusSafetyReason(input);
  const configurationUnavailable =
    !configuration || !draft || Boolean(input.configurationError);
  const revisionUnavailable = !Number.isInteger(revision) || revision < 1;

  let saveDisabledReason = null;
  if (activeOperationReason) {
    saveDisabledReason = `Save unavailable: ${activeOperationReason}`;
  } else if (configurationUnavailable) {
    saveDisabledReason = "Save unavailable: configuration is unavailable";
  } else if (revisionUnavailable) {
    saveDisabledReason = "Save unavailable: revision is unknown";
  } else if (!validation.valid) {
    saveDisabledReason = "Save unavailable: configuration is invalid";
  } else if (!dirty) {
    saveDisabledReason = "Save unavailable: there are no unsaved changes";
  }

  let recoveryDisabledReason = null;
  if (activeOperationReason) {
    recoveryDisabledReason =
      `Recovery unavailable: ${activeOperationReason}`;
  } else if (input.configurationConflict) {
    recoveryDisabledReason =
      "Recovery unavailable: configuration conflict requires review";
  } else if (safetyReason) {
    recoveryDisabledReason = `Recovery unavailable: ${safetyReason}`;
  } else if (
    input.recoveryError?.code === MONEY_MANAGEMENT_ERROR_CODE.NOT_FOUND
  ) {
    recoveryDisabledReason =
      "Recovery unavailable: endpoint is unavailable";
  } else if (
    input.status?.revision === null ||
    input.status?.revision === undefined
  ) {
    recoveryDisabledReason =
      "Recovery unavailable: runtime revision is unknown";
  }

  const refreshDisabledReason = activeOperationReason
    ? `Refresh unavailable: ${activeOperationReason}`
    : null;
  const fieldErrors = Object.freeze(
    Object.fromEntries(
      Object.entries(validation.errors)
        .filter(([key]) => key !== "expectedRevision")
        .map(([key, code]) => [
          key,
          VALIDATION_MESSAGES[code] ?? "Invalid value.",
        ]),
    ),
  );
  const recoveryResult = input.recoveryResult
    ? Object.freeze({
        accepted: displayBoolean(input.recoveryResult.accepted),
        recovered: displayBoolean(input.recoveryResult.recovered),
        result: input.recoveryResult.safeReason ?? "UNKNOWN",
        updated: formatMoneyManagementTime(
          input.recoveryResult.generatedAt,
        ),
      })
    : null;

  return Object.freeze({
    configuration: Object.freeze({
      revision: revision ?? "Revision unavailable",
      draftStatus: input.isUpdatingConfiguration
        ? "SAVING CONFIGURATION"
        : configurationUnavailable
          ? "UNAVAILABLE"
          : dirty
            ? "UNSAVED CHANGES"
            : "SAVED",
      fields: MONEY_MANAGEMENT_CONFIGURATION_FIELDS,
      fieldErrors,
      dirty,
      saveDisabledReason,
      resetDisabledReason: activeOperationReason
        ? `Reset unavailable: ${activeOperationReason}`
        : !dirty && !input.configurationConflict
          ? "Reset unavailable: there are no unsaved changes"
          : null,
      errorMessage:
        input.updateError?.message ??
        input.configurationError?.message ??
        null,
      conflict: input.configurationConflict
        ? Object.freeze({
            active: true,
            rows: conflictRows(configuration, draft),
          })
        : null,
    }),
    recovery: Object.freeze({
      availability: recoveryDisabledReason ? "UNAVAILABLE" : "AVAILABLE",
      currentRiskState: input.status?.riskState ?? "UNKNOWN",
      entryPermission:
        input.status?.executionEntryAllowed === true
          ? "ENTRY ALLOWED"
          : "ENTRY BLOCKED",
      preconditions: "Not reported",
      disabledReason: recoveryDisabledReason,
      errorCode: input.recoveryError?.code ?? null,
      errorMessage: input.recoveryError?.message ?? null,
      result: recoveryResult,
    }),
    refresh: Object.freeze({
      disabledReason: refreshDisabledReason,
      label: input.isManualRefreshing ? "REFRESHING" : "Refresh",
    }),
  });
}
