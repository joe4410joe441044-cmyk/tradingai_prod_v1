import { isStrictDecimalString } from "../utils/moneyManagementDecimal.js";

const KNOWN_RISK_STATES = new Set([
  "NORMAL",
  "CAUTION",
  "DEFENSIVE",
  "LOCKED",
  "UNKNOWN",
]);
const KNOWN_ACTIONS = new Set([
  "CONTINUE",
  "REDUCE_RISK",
  "HOLD_NEW_ENTRIES",
  "BLOCK_EXECUTION",
  "UNKNOWN",
]);

const unavailableValue = (label = "—") =>
  Object.freeze({
    text: label,
    unavailable: true,
    unit: null,
  });

const displayValue = (value, unit = null) => {
  if (value === null || value === undefined || value === "") {
    return unavailableValue();
  }
  return Object.freeze({
    text: String(value),
    unavailable: false,
    unit,
  });
};

export function displayDecimal(value, unit = null) {
  if (!isStrictDecimalString(value)) return unavailableValue();
  return Object.freeze({
    text: value,
    unavailable: false,
    unit,
  });
}

export function formatMoneyManagementTime(value) {
  if (typeof value !== "string") return "—";
  const match = value.match(/T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$/);
  return match?.[1] ?? "—";
}

function riskVariant(state) {
  if (state === "NORMAL") return "safe";
  if (state === "CAUTION" || state === "DEFENSIVE") return "warning";
  if (state === "LOCKED" || state === "UNKNOWN") return "danger";
  return "danger";
}

function permission(status) {
  if (status?.executionEntryAllowed === true) {
    return Object.freeze({
      text: "ENTRY ALLOWED",
      variant: "safe",
    });
  }
  if (
    status?.executionEntryAllowed === false &&
    (status.riskState === "DEFENSIVE" ||
      status.recommendedAction === "HOLD_NEW_ENTRIES")
  ) {
    return Object.freeze({
      text: "NEW ENTRIES ON HOLD",
      variant: "warning",
    });
  }
  if (
    status?.executionEntryAllowed === false &&
    status.riskState !== "UNKNOWN"
  ) {
    return Object.freeze({
      text: "ENTRY BLOCKED",
      variant: "danger",
    });
  }
  return Object.freeze({
    text: "ENTRY STATUS UNKNOWN",
    variant: "danger",
  });
}

function pollingDisplay(pollingState, consecutiveFailures) {
  if (pollingState === "RUNNING" && consecutiveFailures > 0) {
    return "BACKOFF";
  }
  if (pollingState === "RUNNING") return "ACTIVE";
  if (pollingState === "SUSPENDED") return "PAUSED";
  return "STOPPED";
}

function pageDisplayState({
  configurationConflict,
  isClientStale,
  isInitialLoading,
  isManualRefreshing,
  isRecovering,
  isUpdatingConfiguration,
  pollingState,
  status,
  statusError,
}) {
  if (isInitialLoading) return "LOADING";
  if (
    statusError ||
    !status ||
    pollingState === "STOPPED"
  ) {
    return "UNAVAILABLE";
  }
  if (isClientStale) return "STALE";
  if (
    isUpdatingConfiguration ||
    isRecovering ||
    isManualRefreshing ||
    configurationConflict
  ) {
    return "UPDATING";
  }
  if (!status.available) return "UNAVAILABLE";
  return "READY";
}

function connectionDisplay({
  consecutiveFailures,
  isClientStale,
  pollingState,
  status,
  statusError,
}) {
  if (
    statusError ||
    !status ||
    !status.available ||
    isClientStale ||
    pollingState === "STOPPED"
  ) {
    return Object.freeze({
      text: "UNAVAILABLE",
      variant: "danger",
    });
  }
  if (
    consecutiveFailures > 0 ||
    pollingState === "SUSPENDED" ||
    status.diagnosticReasons.length > 0
  ) {
    return Object.freeze({
      text: "DEGRADED",
      variant: "warning",
    });
  }
  return Object.freeze({
    text: "CONNECTED",
    variant: "safe",
  });
}

function normalizedReasons(status) {
  const available = Boolean(status);
  const group = (key, emptyLabel) => Object.freeze({
    available,
    emptyLabel,
    items: Object.freeze(
      Array.isArray(status?.[key]) ? [...status[key]] : [],
    ),
  });
  return Object.freeze({
    warning: group("warningReasons", "No active warnings"),
    hold: group("holdReasons", "None"),
    block: group("blockReasons", "None"),
    diagnostic: group("diagnosticReasons", "None"),
  });
}

function primaryReason(reasons) {
  for (const group of [
    reasons.block,
    reasons.hold,
    reasons.warning,
    reasons.diagnostic,
  ]) {
    if (group.items.length > 0) return group.items[0];
  }
  return reasons.block.available ? "None" : "Reason data unavailable";
}

function metricQuality(metrics) {
  if (!metrics) return "UNKNOWN";
  const required = [
    metrics.equity,
    metrics.peakEquity,
    metrics.drawdownPercent,
    metrics.dailyPnl,
    metrics.weeklyPnl,
    metrics.monthlyPnl,
  ];
  if (
    metrics.status === "AVAILABLE" &&
    required.every((value) => value !== null)
  ) {
    return "COMPLETE";
  }
  if (
    metrics.status === "PARTIAL" ||
    required.some((value) => value !== null)
  ) {
    return "PARTIAL";
  }
  return "UNKNOWN";
}

function row(label, value, options = {}) {
  return Object.freeze({
    label,
    value,
    ...options,
  });
}

function capitalState(reasons) {
  if (
    reasons.block.items.includes("NEGATIVE_EQUITY") ||
    reasons.block.items.includes("CASH_FLOW_DETECTED")
  ) {
    return displayValue("BLOCKED");
  }
  return unavailableValue("Not reported");
}

function cashFlowState(reasons) {
  if (
    reasons.block.items.includes("CASH_FLOW_DETECTED") ||
    reasons.diagnostic.items.includes("CASH_FLOW_PRESENT")
  ) {
    return displayValue("DETECTED");
  }
  return unavailableValue("Not reported");
}

function protectionLevel(status) {
  if (
    status?.clientSafeReason === "CONTRACT_INCONSISTENT" ||
    status?.clientSafeReason === "PROJECTION_INCONSISTENT"
  ) {
    return "CONTRACT CONFLICT";
  }
  if (status?.riskState === "UNKNOWN") return "FAIL CLOSED";
  return status?.riskState ?? "UNKNOWN";
}

export function createMoneyManagementViewModel(input = {}) {
  const {
    configurationConflict = null,
    consecutiveFailures = 0,
    isClientStale = false,
    isInitialLoading = false,
    isManualRefreshing = false,
    isRecovering = false,
    isUpdatingConfiguration = false,
    pollingState = "STOPPED",
    status = null,
    statusError = null,
  } = input;
  const state = pageDisplayState({
    configurationConflict,
    isClientStale,
    isInitialLoading,
    isManualRefreshing,
    isRecovering,
    isUpdatingConfiguration,
    pollingState,
    status,
    statusError,
  });
  const reasons = normalizedReasons(status);
  const metrics = status?.metrics ?? null;
  const displayIsCurrent = state === "READY";
  const riskState =
    displayIsCurrent && KNOWN_RISK_STATES.has(status?.riskState)
    ? status.riskState
    : "UNKNOWN";
  const recommendedAction =
    displayIsCurrent && KNOWN_ACTIONS.has(status?.recommendedAction)
    ? status.recommendedAction
    : "UNKNOWN";
  const safeDisplayStatus = {
    ...status,
    riskState,
    recommendedAction,
    executionEntryAllowed:
      displayIsCurrent && status?.executionEntryAllowed === true,
  };
  const entryPermission = displayIsCurrent
    ? permission(safeDisplayStatus)
    : Object.freeze({
        text: "ENTRY BLOCKED",
        variant: "danger",
      });
  const updatedTime = formatMoneyManagementTime(status?.generatedAt);
  const polling = pollingDisplay(pollingState, consecutiveFailures);
  const lastKnown = ["STALE", "UNAVAILABLE", "UPDATING"].includes(state);

  return Object.freeze({
    state,
    banner:
      configurationConflict
        ? "CONFIGURATION CONFLICT"
        : isUpdatingConfiguration
          ? "CONFIGURATION UPDATE IN PROGRESS"
          : isRecovering
            ? "RECOVERY IN PROGRESS"
            : isManualRefreshing
              ? "REFRESHING MONEY MANAGEMENT STATE"
              : state === "LOADING"
        ? "Loading"
        : state === "STALE"
          ? "STALE DATA — ENTRY BLOCKED"
          : state === "UNAVAILABLE"
            ? "MONEY MANAGEMENT UNAVAILABLE"
            : state === "UPDATING"
              ? "Updating — Last known value"
              : null,
    lastKnown,
    header: Object.freeze({
      mode: Object.freeze({
        text: ["PAPER", "LIVE"].includes(status?.mode)
          ? status.mode
          : "UNKNOWN MODE",
        variant: "muted",
      }),
      connection: connectionDisplay({
        consecutiveFailures,
        isClientStale,
        pollingState,
        status,
        statusError,
      }),
      updated: `Updated ${updatedTime}`,
      refreshLabel: isManualRefreshing ? "REFRESHING" : "Refresh",
      refreshDisabled:
        isManualRefreshing ||
        isUpdatingConfiguration ||
        isRecovering,
    }),
    runtime: Object.freeze([
      row("Lifecycle", displayValue(status?.lifecycleState ?? "UNKNOWN")),
      row(
        "Health",
        displayValue(
          displayIsCurrent && status?.available
            ? "AVAILABLE"
            : "UNAVAILABLE",
        ),
      ),
      row("Polling", displayValue(polling)),
      row("Updated", displayValue(updatedTime)),
    ]),
    riskSummary: Object.freeze({
      state: Object.freeze({
        text: riskState,
        variant: riskVariant(riskState),
      }),
      rows: Object.freeze([
        row("Recommended Action", displayValue(recommendedAction)),
        row("Entry Permission", displayValue(entryPermission.text), {
          variant: entryPermission.variant,
        }),
        row("Primary Reason", displayValue(primaryReason(reasons))),
      ]),
    }),
    exposure: Object.freeze([
      row(
        "Current Exposure",
        displayDecimal(metrics?.openExposure),
      ),
      row("Exposure Limit", unavailableValue()),
      row("Exposure Utilization", unavailableValue()),
      row("Open Position State", unavailableValue("Not reported")),
    ]),
    capital: Object.freeze([
      row("Equity", displayDecimal(metrics?.equity, "USDT")),
      row(
        "Available Capital",
        displayDecimal(metrics?.availableCapital, "USDT"),
      ),
      row("Cash Flow", cashFlowState(reasons)),
      row("Capital State", capitalState(reasons)),
    ]),
    riskState: Object.freeze({
      state: Object.freeze({
        text: riskState,
        variant: riskVariant(riskState),
      }),
      recommendedAction,
      entryPermission,
      protectionLevel: protectionLevel(safeDisplayStatus),
      primaryReason: primaryReason(reasons),
      updated: updatedTime,
      reasons,
    }),
    performance: Object.freeze([
      row("Daily P&L", displayDecimal(metrics?.dailyPnl, "USDT")),
      row("Weekly P&L", displayDecimal(metrics?.weeklyPnl, "USDT")),
      row("Monthly P&L", displayDecimal(metrics?.monthlyPnl, "USDT")),
      row("Drawdown", displayDecimal(metrics?.drawdownPercent, "%")),
      row("Peak Equity", displayDecimal(metrics?.peakEquity, "USDT")),
    ]),
    statistics: Object.freeze([
      row(
        "Current Drawdown",
        displayDecimal(metrics?.drawdownAmount, "USDT"),
      ),
      row(
        "Maximum Drawdown",
        displayDecimal(
          status?.configuration?.maximumDrawdownPercent,
          "%",
        ),
      ),
      row("Loss Period", unavailableValue("Not reported")),
      row("Consecutive Losses", unavailableValue()),
      row("Risk Utilization", unavailableValue()),
      row("Metric Quality", displayValue(metricQuality(metrics))),
    ]),
    projection: Object.freeze({
      current: Object.freeze({
        text:
          displayIsCurrent &&
          status?.projectionStatus &&
          status.projectionStatus !== "UNKNOWN"
            ? status.projectionStatus
            : "Not Available",
        variant:
          status?.projectionStatus === "ALLOW" ? "safe" : "danger",
      }),
      description:
        "Projection analytics will be added in a later phase.",
    }),
  });
}
