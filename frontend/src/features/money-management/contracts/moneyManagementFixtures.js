export function validConfiguration(overrides = {}) {
  return {
    available: true,
    enabled: true,
    dailyWarningPercent: "1.00",
    dailyBlockPercent: "1.50",
    weeklyWarningPercent: "2.00",
    weeklyBlockPercent: "3.00",
    monthlyWarningPercent: "3.50",
    monthlyBlockPercent: "4.00",
    maximumDrawdownPercent: "5.00",
    totalExposurePercent: "20.00",
    riskPerTradePercent: "0.50",
    maximumPositionNotional: "100.00",
    singleSymbolExposurePercent: "10.00",
    maximumLeverage: "5",
    revision: 7,
    source: "DEFAULT",
    updatedAt: "2026-07-26T12:00:00Z",
    ...overrides,
  };
}

export function validMetrics(overrides = {}) {
  return {
    status: "AVAILABLE",
    equity: "1000.25",
    availableCapital: "900.25",
    peakEquity: "1025.40",
    drawdownAmount: "25.15",
    drawdownPercent: "2.4527",
    dailyPnl: "-12.50",
    weeklyPnl: "-3.10",
    monthlyPnl: "25.40",
    dailyTradeCount: 2,
    weeklyTradeCount: 5,
    monthlyTradeCount: 8,
    openExposure: "200.00",
    exposureLimit: "25.00",
    exposureUtilization: "80.00",
    openPositionState: "OPEN",
    riskUtilization: null,
    riskLimitAmount: "4.50",
    currentRiskAmount: null,
    reservedRiskAmount: null,
    riskBudgetRemaining: null,
    recommendedPositionNotional: null,
    recommendedPositionQuantity: null,
    metricsGeneratedAt: "2026-07-26T12:00:00Z",
    ...overrides,
  };
}

export function validStatus(overrides = {}) {
  return {
    schemaVersion: "money-management-http/v1",
    available: true,
    enabled: true,
    lifecycleState: "RUNNING",
    riskState: "NORMAL",
    recommendedAction: "CONTINUE",
    executionEntryAllowed: true,
    warningReasons: [],
    holdReasons: [],
    blockReasons: [],
    diagnosticReasons: [],
    metricsStatus: "AVAILABLE",
    projectionStatus: "ALLOW",
    recoveryRequired: false,
    safeReason: null,
    generatedAt: "2026-07-26T12:00:00Z",
    revision: 11,
    sequence: 12,
    configurationRevision: 7,
    metrics: validMetrics(),
    configuration: validConfiguration(),
    ...overrides,
  };
}

export function validUpdateResponse(overrides = {}) {
  return {
    applied: true,
    reevaluated: true,
    safeReason: "CONFIGURATION_APPLIED",
    configuration: validConfiguration({ revision: 8 }),
    status: validStatus({
      configurationRevision: 8,
      configuration: validConfiguration({ revision: 8 }),
    }),
    ...overrides,
  };
}

export function validRecoveryResponse(overrides = {}) {
  return {
    accepted: true,
    recovered: true,
    previousState: "UNKNOWN",
    currentState: "NORMAL",
    recommendedAction: "CONTINUE",
    executionEntryAllowed: true,
    safeReason: "RECOVERY_COMPLETED",
    generatedAt: "2026-07-26T12:00:00Z",
    revision: 12,
    sequence: 13,
    ...overrides,
  };
}
