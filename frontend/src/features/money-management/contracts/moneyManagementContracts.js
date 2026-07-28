import {
  compareDecimalStrings,
  isBackendPercentage,
  isStrictDecimalString,
} from "../utils/moneyManagementDecimal.js";
import { isValidUtcIsoTimestamp } from "../utils/moneyManagementTime.js";

export const MONEY_MANAGEMENT_RISK_STATE = Object.freeze([
  "NORMAL",
  "CAUTION",
  "DEFENSIVE",
  "LOCKED",
  "RECOVERY_25",
  "RECOVERY_50",
  "UNKNOWN",
]);

export const MONEY_MANAGEMENT_RECOMMENDED_ACTION = Object.freeze([
  "CONTINUE",
  "REDUCE_RISK",
  "HOLD_NEW_ENTRIES",
  "BLOCK_EXECUTION",
  "UNKNOWN",
]);

export const MONEY_MANAGEMENT_LIFECYCLE_STATE = Object.freeze([
  "CREATED",
  "STARTING",
  "RUNNING",
  "STOPPING",
  "STOPPED",
  "FAILED",
  "RECOVERY_REQUIRED",
  "UNAVAILABLE",
  "UNKNOWN",
]);

export const MONEY_MANAGEMENT_METRICS_STATUS = Object.freeze([
  "AVAILABLE",
  "PARTIAL",
  "UNAVAILABLE",
  "STALE",
  "INCONSISTENT",
  "FAILED",
  "UNKNOWN",
]);

export const MONEY_MANAGEMENT_PROJECTION_STATUS = Object.freeze([
  "ALLOW",
  "BLOCK",
  "RECOVERY_REQUIRED",
  "UNKNOWN",
]);

const WARNING_REASONS = new Set([
  "DAILY_LOSS_WARNING",
  "WEEKLY_LOSS_WARNING",
  "MONTHLY_LOSS_WARNING",
  "DRAWDOWN_WARNING",
]);
const HOLD_REASONS = new Set([
  "MULTIPLE_LOSS_WARNINGS",
  "LOSS_LIMIT_DEFENSIVE_STATE",
]);
const BLOCK_REASONS = new Set([
  "DAILY_LOSS_BLOCK",
  "WEEKLY_LOSS_BLOCK",
  "MONTHLY_LOSS_BLOCK",
  "DRAWDOWN_BLOCK",
  "NEGATIVE_EQUITY",
  "DRAWDOWN_PERCENT_UNKNOWN",
  "CASH_FLOW_DETECTED",
  "INCOMPLETE_INPUT",
  "UNSAFE_STATE",
  "UNKNOWN_STATE",
]);
const DIAGNOSTIC_REASONS = new Set([
  "STARTING_EQUITY_ZERO",
  "HIGH_WATER_MARK_ZERO",
  "CASH_FLOW_PRESENT",
  "METRIC_UNAVAILABLE",
  "MONEY_MANAGEMENT_DISABLED",
  "MONEY_MANAGEMENT_NOT_REGISTERED",
  "MONEY_MANAGEMENT_UNAVAILABLE",
  "AUTHORITATIVE_METRICS_INCOMPLETE",
  "INTERNAL_STATE_UNAVAILABLE",
]);

export class MoneyManagementContractError extends TypeError {
  constructor(reason) {
    super("Money Management response is invalid.");
    this.name = "MoneyManagementContractError";
    this.reason = reason;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new MoneyManagementContractError(`${field} must be an object`);
  }
  return value;
}

function bool(value, field) {
  if (typeof value !== "boolean") {
    throw new MoneyManagementContractError(`${field} must be boolean`);
  }
  return value;
}

function text(value, field, nullable = false) {
  if (value === null && nullable) return null;
  if (typeof value !== "string" || value.length === 0) {
    throw new MoneyManagementContractError(`${field} must be text`);
  }
  return value;
}

function positiveInteger(value, field, nullable = false) {
  if (value === null && nullable) return null;
  if (!Number.isInteger(value) || value < 1) {
    throw new MoneyManagementContractError(
      `${field} must be a positive integer`,
    );
  }
  return value;
}

function nullableCount(value, field) {
  if (value === null) return null;
  if (!Number.isInteger(value) || value < 0) {
    throw new MoneyManagementContractError(`${field} must be a count`);
  }
  return value;
}

function decimal(value, field, nullable = false) {
  if (value === null && nullable) return null;
  if (!isStrictDecimalString(value)) {
    throw new MoneyManagementContractError(
      `${field} must be a decimal string`,
    );
  }
  return value;
}

function utcTimestamp(value, field, nullable = false) {
  if (value === null && nullable) return null;
  if (!isValidUtcIsoTimestamp(value)) {
    throw new MoneyManagementContractError(
      `${field} must be a UTC timestamp`,
    );
  }
  return value;
}

function enumValue(value, allowed, field, diagnostics) {
  if (typeof value === "string" && allowed.includes(value)) {
    return value;
  }
  diagnostics.push(`UNKNOWN_${field.replace(/([a-z])([A-Z])/g, "$1_$2").toUpperCase()}`);
  return "UNKNOWN";
}

function reasons(value, allowed, field, diagnostics) {
  if (!Array.isArray(value)) {
    throw new MoneyManagementContractError(`${field} must be an array`);
  }
  return Object.freeze(
    value.map((item) => {
      if (typeof item !== "string" || item.length === 0) {
        throw new MoneyManagementContractError(
          `${field} entries must be text`,
        );
      }
      if (!allowed.has(item)) {
        diagnostics.push(`UNKNOWN_${field.toUpperCase()}`);
        return "UNKNOWN";
      }
      return item;
    }),
  );
}

export function normalizeMoneyManagementMetrics(raw) {
  if (raw === null) return null;
  const value = object(raw, "metrics");
  const diagnostics = [];
  const status = enumValue(
    value.status,
    MONEY_MANAGEMENT_METRICS_STATUS,
    "metricsStatus",
    diagnostics,
  );
  return Object.freeze({
    status,
    equity: decimal(value.equity, "metrics.equity", true),
    availableCapital: decimal(
      value.availableCapital,
      "metrics.availableCapital",
      true,
    ),
    peakEquity: decimal(value.peakEquity, "metrics.peakEquity", true),
    drawdownAmount: decimal(
      value.drawdownAmount,
      "metrics.drawdownAmount",
      true,
    ),
    drawdownPercent: decimal(
      value.drawdownPercent,
      "metrics.drawdownPercent",
      true,
    ),
    dailyPnl: decimal(value.dailyPnl, "metrics.dailyPnl", true),
    weeklyPnl: decimal(value.weeklyPnl, "metrics.weeklyPnl", true),
    monthlyPnl: decimal(value.monthlyPnl, "metrics.monthlyPnl", true),
    dailyTradeCount: nullableCount(
      value.dailyTradeCount,
      "metrics.dailyTradeCount",
    ),
    weeklyTradeCount: nullableCount(
      value.weeklyTradeCount,
      "metrics.weeklyTradeCount",
    ),
    monthlyTradeCount: nullableCount(
      value.monthlyTradeCount,
      "metrics.monthlyTradeCount",
    ),
    openExposure: decimal(
      value.openExposure,
      "metrics.openExposure",
      true,
    ),
    metricsGeneratedAt: utcTimestamp(
      value.metricsGeneratedAt,
      "metrics.metricsGeneratedAt",
      true,
    ),
    diagnostics: Object.freeze(diagnostics),
  });
}

export function normalizeMoneyManagementConfiguration(raw) {
  const value = object(raw, "configuration");
  const source = text(value.source, "configuration.source");
  if (!["DEFAULT", "RUNTIME_OVERRIDE"].includes(source)) {
    throw new MoneyManagementContractError(
      "configuration.source is invalid",
    );
  }
  return Object.freeze({
    available: bool(value.available, "configuration.available"),
    enabled: bool(value.enabled, "configuration.enabled"),
    dailyWarningPercent: decimal(
      value.dailyWarningPercent,
      "configuration.dailyWarningPercent",
    ),
    dailyBlockPercent: decimal(
      value.dailyBlockPercent,
      "configuration.dailyBlockPercent",
    ),
    weeklyWarningPercent: decimal(
      value.weeklyWarningPercent,
      "configuration.weeklyWarningPercent",
    ),
    weeklyBlockPercent: decimal(
      value.weeklyBlockPercent,
      "configuration.weeklyBlockPercent",
    ),
    monthlyWarningPercent: decimal(
      value.monthlyWarningPercent,
      "configuration.monthlyWarningPercent",
    ),
    monthlyBlockPercent: decimal(
      value.monthlyBlockPercent,
      "configuration.monthlyBlockPercent",
    ),
    maximumDrawdownPercent: decimal(
      value.maximumDrawdownPercent,
      "configuration.maximumDrawdownPercent",
    ),
    revision: positiveInteger(
      value.revision,
      "configuration.revision",
    ),
    source,
    updatedAt: utcTimestamp(
      value.updatedAt,
      "configuration.updatedAt",
    ),
  });
}

export function normalizeMoneyManagementStatus(raw) {
  const value = object(raw, "status");
  const diagnostics = [];
  const available = bool(value.available, "status.available");
  const enabled = bool(value.enabled, "status.enabled");
  const lifecycleState = enumValue(
    value.lifecycleState,
    MONEY_MANAGEMENT_LIFECYCLE_STATE,
    "lifecycleState",
    diagnostics,
  );
  const riskState = enumValue(
    value.riskState,
    MONEY_MANAGEMENT_RISK_STATE,
    "riskState",
    diagnostics,
  );
  const recommendedAction = enumValue(
    value.recommendedAction,
    MONEY_MANAGEMENT_RECOMMENDED_ACTION,
    "recommendedAction",
    diagnostics,
  );
  const metricsStatus = enumValue(
    value.metricsStatus,
    MONEY_MANAGEMENT_METRICS_STATUS,
    "metricsStatus",
    diagnostics,
  );
  const projectionStatus = enumValue(
    value.projectionStatus,
    MONEY_MANAGEMENT_PROJECTION_STATUS,
    "projectionStatus",
    diagnostics,
  );
  const revision = positiveInteger(value.revision, "status.revision", true);
  const sequence = positiveInteger(value.sequence, "status.sequence", true);
  if ((revision === null) !== (sequence === null)) {
    diagnostics.push("RUNTIME_REVISION_SEQUENCE_MISMATCH");
  }
  const metrics = normalizeMoneyManagementMetrics(value.metrics);
  if (metrics === null) {
    diagnostics.push("METRICS_MISSING");
  }
  if (metrics && metrics.status !== metricsStatus) {
    diagnostics.push("METRICS_STATUS_MISMATCH");
  }
  const configuration = normalizeMoneyManagementConfiguration(
    value.configuration,
  );
  const configurationRevision = positiveInteger(
    value.configurationRevision,
    "status.configurationRevision",
  );
  if (configuration.revision !== configurationRevision) {
    diagnostics.push("CONFIGURATION_REVISION_MISMATCH");
  }
  if (available && revision === null) {
    diagnostics.push("RUNTIME_REVISION_MISSING");
  }
  const normalizedDiagnostics = reasons(
    value.diagnosticReasons,
    DIAGNOSTIC_REASONS,
    "diagnosticReasons",
    diagnostics,
  );
  return Object.freeze({
    schemaVersion: text(value.schemaVersion, "status.schemaVersion"),
    available,
    enabled,
    lifecycleState,
    riskState,
    recommendedAction,
    executionEntryAllowed: bool(
      value.executionEntryAllowed,
      "status.executionEntryAllowed",
    ),
    warningReasons: reasons(
      value.warningReasons,
      WARNING_REASONS,
      "warningReasons",
      diagnostics,
    ),
    holdReasons: reasons(
      value.holdReasons,
      HOLD_REASONS,
      "holdReasons",
      diagnostics,
    ),
    blockReasons: reasons(
      value.blockReasons,
      BLOCK_REASONS,
      "blockReasons",
      diagnostics,
    ),
    diagnosticReasons: Object.freeze([
      ...normalizedDiagnostics,
      ...diagnostics,
      ...(metrics?.diagnostics ?? []),
    ]),
    metricsStatus,
    projectionStatus,
    recoveryRequired: bool(
      value.recoveryRequired,
      "status.recoveryRequired",
    ),
    safeReason: text(value.safeReason, "status.safeReason", true),
    generatedAt: utcTimestamp(value.generatedAt, "status.generatedAt"),
    revision,
    sequence,
    configurationRevision,
    metrics,
    configuration,
  });
}

export function createFailClosedMoneyManagementStatus(
  rawStatus = null,
  reason = "CLIENT_UNAVAILABLE",
) {
  return Object.freeze({
    ...(rawStatus ?? {}),
    available: false,
    riskState: "UNKNOWN",
    recommendedAction: "UNKNOWN",
    executionEntryAllowed: false,
    clientSafeReason: reason,
  });
}

export function createSafeMoneyManagementStatus(rawStatus, client = {}) {
  let unsafeReason = null;

  if (!rawStatus) {
    unsafeReason = "STATUS_MISSING";
  } else if (!rawStatus.available || !rawStatus.enabled) {
    unsafeReason = "BACKEND_UNAVAILABLE";
  } else if (rawStatus.lifecycleState !== "RUNNING") {
    unsafeReason = "LIFECYCLE_NOT_RUNNING";
  } else if (rawStatus.metricsStatus !== "AVAILABLE") {
    unsafeReason = "METRICS_NOT_AVAILABLE";
  } else if (rawStatus.riskState === "UNKNOWN") {
    unsafeReason = "RISK_STATE_UNKNOWN";
  } else if (rawStatus.projectionStatus === "UNKNOWN") {
    unsafeReason = "PROJECTION_UNKNOWN";
  } else if (
    rawStatus.riskState === "LOCKED" &&
    rawStatus.recommendedAction !== "BLOCK_EXECUTION"
  ) {
    unsafeReason = "PROJECTION_INCONSISTENT";
  } else if (
    rawStatus.executionEntryAllowed &&
    (rawStatus.projectionStatus !== "ALLOW" ||
      rawStatus.riskState === "LOCKED")
  ) {
    unsafeReason = "PROJECTION_INCONSISTENT";
  } else if (
    rawStatus.diagnosticReasons.some(
      (item) =>
        item.endsWith("_MISMATCH") ||
        item.startsWith("UNKNOWN_") ||
        item === "METRICS_MISSING" ||
        item === "RUNTIME_REVISION_MISSING",
    )
  ) {
    unsafeReason = "CONTRACT_INCONSISTENT";
  } else if (client.clientStale) {
    unsafeReason = "CLIENT_STALE";
  } else if (client.requestFailed) {
    unsafeReason = "REQUEST_FAILED";
  } else if (client.pollingState !== "RUNNING") {
    unsafeReason = "POLLING_NOT_RUNNING";
  } else if (client.configurationUpdating) {
    unsafeReason = "CONFIGURATION_UPDATING";
  } else if (client.recoveryRunning) {
    unsafeReason = "RECOVERY_RUNNING";
  } else if (client.manualRefreshing) {
    unsafeReason = "MANUAL_REFRESH_RUNNING";
  } else if (client.configurationConflict) {
    unsafeReason = "CONFIGURATION_CONFLICT";
  } else if (client.configurationInvalid) {
    unsafeReason = "CONFIGURATION_INVALID";
  } else if (client.configurationUnavailable) {
    unsafeReason = "CONFIGURATION_UNAVAILABLE";
  }

  return unsafeReason
    ? createFailClosedMoneyManagementStatus(rawStatus, unsafeReason)
    : Object.freeze({
        ...rawStatus,
        clientSafeReason: null,
      });
}

export function configurationDraftFromAuthoritative(configuration) {
  if (!configuration) return null;
  return Object.freeze({
    enabled: configuration.enabled,
    dailyWarningPercent: configuration.dailyWarningPercent,
    dailyBlockPercent: configuration.dailyBlockPercent,
    weeklyWarningPercent: configuration.weeklyWarningPercent,
    weeklyBlockPercent: configuration.weeklyBlockPercent,
    monthlyWarningPercent: configuration.monthlyWarningPercent,
    monthlyBlockPercent: configuration.monthlyBlockPercent,
    maximumDrawdownPercent: configuration.maximumDrawdownPercent,
  });
}

const PERCENTAGE_FIELDS = Object.freeze([
  "dailyWarningPercent",
  "dailyBlockPercent",
  "weeklyWarningPercent",
  "weeklyBlockPercent",
  "monthlyWarningPercent",
  "monthlyBlockPercent",
  "maximumDrawdownPercent",
]);

export function validateMoneyManagementConfigurationDraft(
  draft,
  expectedRevision,
) {
  const errors = {};
  if (!draft || typeof draft !== "object" || Array.isArray(draft)) {
    return Object.freeze({
      valid: false,
      errors: Object.freeze({ draft: "MISSING" }),
    });
  }
  if (typeof draft.enabled !== "boolean") {
    errors.enabled = "INVALID_BOOLEAN";
  }
  for (const field of PERCENTAGE_FIELDS) {
    if (!isBackendPercentage(draft[field])) {
      errors[field] = "INVALID_PERCENTAGE";
    }
  }
  for (const [warning, block] of [
    ["dailyWarningPercent", "dailyBlockPercent"],
    ["weeklyWarningPercent", "weeklyBlockPercent"],
    ["monthlyWarningPercent", "monthlyBlockPercent"],
  ]) {
    if (
      !errors[warning] &&
      !errors[block] &&
      compareDecimalStrings(draft[warning], draft[block]) >= 0
    ) {
      errors[warning] = "WARNING_MUST_BE_BELOW_BLOCK";
    }
  }
  if (
    !errors.dailyBlockPercent &&
    !errors.weeklyBlockPercent &&
    compareDecimalStrings(
      draft.dailyBlockPercent,
      draft.weeklyBlockPercent,
    ) >= 0
  ) {
    errors.dailyBlockPercent = "DAILY_BLOCK_MUST_BE_BELOW_WEEKLY";
  }
  if (
    !errors.weeklyBlockPercent &&
    !errors.monthlyBlockPercent &&
    compareDecimalStrings(
      draft.weeklyBlockPercent,
      draft.monthlyBlockPercent,
    ) > 0
  ) {
    errors.weeklyBlockPercent = "WEEKLY_BLOCK_EXCEEDS_MONTHLY";
  }
  if (
    !errors.monthlyBlockPercent &&
    !errors.maximumDrawdownPercent &&
    compareDecimalStrings(
      draft.monthlyBlockPercent,
      draft.maximumDrawdownPercent,
    ) >= 0
  ) {
    errors.monthlyBlockPercent = "MONTHLY_BLOCK_MUST_BE_BELOW_DRAWDOWN";
  }
  if (!Number.isInteger(expectedRevision) || expectedRevision < 1) {
    errors.expectedRevision = "MISSING";
  }
  return Object.freeze({
    valid: Object.keys(errors).length === 0,
    errors: Object.freeze(errors),
  });
}

export function buildMoneyManagementConfigurationPayload(
  draft,
  expectedRevision,
) {
  const validation = validateMoneyManagementConfigurationDraft(
    draft,
    expectedRevision,
  );
  if (!validation.valid) {
    throw new MoneyManagementContractError(
      "configuration draft is invalid",
    );
  }
  return Object.freeze({
    enabled: draft.enabled,
    dailyWarningPercent: draft.dailyWarningPercent,
    dailyBlockPercent: draft.dailyBlockPercent,
    weeklyWarningPercent: draft.weeklyWarningPercent,
    weeklyBlockPercent: draft.weeklyBlockPercent,
    monthlyWarningPercent: draft.monthlyWarningPercent,
    monthlyBlockPercent: draft.monthlyBlockPercent,
    maximumDrawdownPercent: draft.maximumDrawdownPercent,
    expectedRevision,
  });
}

export function normalizeConfigurationUpdateResponse(raw) {
  const value = object(raw, "configuration update");
  return Object.freeze({
    applied: bool(value.applied, "update.applied"),
    reevaluated: bool(value.reevaluated, "update.reevaluated"),
    safeReason: text(value.safeReason, "update.safeReason"),
    configuration: normalizeMoneyManagementConfiguration(
      value.configuration,
    ),
    status: normalizeMoneyManagementStatus(value.status),
  });
}

export function normalizeRecoveryResponse(raw) {
  const value = object(raw, "recovery");
  const accepted = bool(value.accepted, "recovery.accepted");
  const recovered = bool(value.recovered, "recovery.recovered");
  const safeReason = text(value.safeReason, "recovery.safeReason");
  const outcome =
    safeReason === "ALREADY_EVALUATED"
      ? "ALREADY_EVALUATED"
      : recovered
        ? "RECOVERED"
        : accepted
          ? "NOT_RECOVERED"
          : "UNKNOWN";
  return Object.freeze({
    accepted,
    recovered,
    outcome,
    previousState: text(value.previousState, "recovery.previousState"),
    currentState: text(value.currentState, "recovery.currentState"),
    recommendedAction: text(
      value.recommendedAction,
      "recovery.recommendedAction",
    ),
    executionEntryAllowed: bool(
      value.executionEntryAllowed,
      "recovery.executionEntryAllowed",
    ),
    safeReason,
    generatedAt: utcTimestamp(
      value.generatedAt,
      "recovery.generatedAt",
    ),
    revision: positiveInteger(
      value.revision,
      "recovery.revision",
      true,
    ),
    sequence: positiveInteger(
      value.sequence,
      "recovery.sequence",
      true,
    ),
  });
}
