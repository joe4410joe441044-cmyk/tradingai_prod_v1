export default function executionGateEngine({

  derivedIntel = {},

  executionData = {},

  riskData = {},

  strategyData = {},

}) {

  // =========================
  // INPUT EXTRACTION
  // =========================

  const {

    spreadExplosion = false,

    executionAnomaly = false,

    spoofDanger = false,

    noTradeZone = false,

    unstableMarket = false,

    emergencyExit = false,

    marketDanger = "LOW",

    confidenceScore = 0,

    marketPhase = "RANGING",

    signal = "WAIT",

    direction = "NONE",

    executionAllowed = false,

  } = derivedIntel;

  const {

    cooldown = false,

    liquidityGrab = false,

    breakoutLong = false,

    breakoutShort = false,

  } = strategyData;

  const {

    latency = 0,

    wsStatus = "CONNECTED",

    engineStatus = "READY",

    orderStatus = "IDLE",

  } = executionData;

  const {

    killSwitch = false,

    riskLevel = "LOW",

    currentDD = 0,

    dailyLoss = 0,

    lossStreak = 0,

  } = riskData;

  // =========================
  // BLOCK STATE
  // =========================

  let shouldExecute = true;

  let executionBlocked = false;

  let blockReason = "NONE";

  let riskOverride = false;

  let emergencyBlock = false;

  // =========================
  // EXECUTION BLOCKERS
  // =========================

  // EMERGENCY EXIT

  if (emergencyExit) {

    shouldExecute = false;

    executionBlocked = true;

    emergencyBlock = true;

    blockReason =
      "EMERGENCY_EXIT";

  }

  // KILL SWITCH

  if (killSwitch) {

    shouldExecute = false;

    executionBlocked = true;

    emergencyBlock = true;

    blockReason =
      "KILL_SWITCH";

  }

  // NO TRADE ZONE

  if (noTradeZone) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "NO_TRADE_ZONE";

  }

  // SPOOF DANGER

  if (spoofDanger) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "SPOOF_DANGER";

  }

  // EXECUTION ANOMALY

  if (executionAnomaly) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "EXECUTION_ANOMALY";

  }

  // SPREAD EXPLOSION

  if (spreadExplosion) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "SPREAD_EXPLOSION";

  }

  // COOLDOWN

  if (cooldown) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "COOLDOWN_ACTIVE";

  }

  // UNSTABLE MARKET

  if (unstableMarket) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "UNSTABLE_MARKET";

  }

  // LATENCY SPIKE

  if (latency >= 250) {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "LATENCY_SPIKE";

  }

  // WS DISCONNECTED

  if (wsStatus !== "CONNECTED") {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "WS_DISCONNECTED";

  }

  // ENGINE NOT READY

  if (engineStatus !== "READY") {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "ENGINE_NOT_READY";

  }

  // HIGH MARKET DANGER

  if (marketDanger === "HIGH") {

    shouldExecute = false;

    executionBlocked = true;

    blockReason =
      "HIGH_MARKET_DANGER";

  }

  // HIGH DRAWDOWN

  if (currentDD >= 10) {

    shouldExecute = false;

    executionBlocked = true;

    riskOverride = true;

    blockReason =
      "MAX_DRAWDOWN_EXCEEDED";

  }

  // DAILY LOSS LOCK

  if (dailyLoss >= 5) {

    shouldExecute = false;

    executionBlocked = true;

    riskOverride = true;

    blockReason =
      "DAILY_LOSS_LIMIT";

  }

  // LOSS STREAK LOCK

  if (lossStreak >= 5) {

    shouldExecute = false;

    executionBlocked = true;

    riskOverride = true;

    blockReason =
      "LOSS_STREAK_LIMIT";

  }

  // =========================
  // EXECUTION CONFIDENCE
  // =========================

  const executionConfidence = Math.max(

    0,

    Math.min(

      100,

      Math.round(

        confidenceScore

      )

    )

  );

  // =========================
  // EXECUTION MODE
  // =========================

  const executionMode =

    executionConfidence >= 80
      ? "AGGRESSIVE"

      : executionConfidence >= 60
      ? "NORMAL"

      : executionConfidence >= 40
      ? "DEFENSIVE"

      : "SURVIVAL";

  // =========================
  // EXECUTION PRIORITY
  // =========================

  const executionPriority =

    signal === "ENTER_LONG" &&
    breakoutLong
      ? "HIGH"

      : signal === "ENTER_SHORT" &&
        breakoutShort
      ? "HIGH"

      : liquidityGrab
      ? "MEDIUM"

      : "LOW";

  // =========================
  // FINAL EXECUTION STATE
  // =========================

  return {

    shouldExecute,

    executionBlocked,

    blockReason,

    riskOverride,

    emergencyBlock,

    executionAllowed:
      shouldExecute &&
      executionAllowed,

    executionConfidence,

    executionMode,

    executionPriority,

    marketPhase,

    signal,

    direction,

    orderStatus,

    riskLevel,

    latency,

  };

}