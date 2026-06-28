export function adaptiveEngine({

  riskPacket = {},
  executionPacket = {},

  spread = 0,
  avgSpread = 0,

}) {

  // =========================
  // SAFE VALUES
  // =========================

  const latency =

    Number(
      executionPacket.latency
    ) || 0;

  const safeSpread =

    Number(
      spread
    ) || 0;

  const averageSpread =

    Number(
      avgSpread
    ) || 0;

  const killSwitch =

    Boolean(
      riskPacket.killSwitch
    );

  // =========================
  // EXECUTION CONDITIONS
  // =========================

  const latencyBlocked =

    latency > 120;

  const latencyCritical =

    latency > 180;

  const spreadBlocked =

    safeSpread > 0.05;

  const spreadCritical =

    safeSpread > 0.1;

  // =========================
  // EXECUTION ENTRY STATE
  // =========================

  let adaptiveEntryState =
    "ALLOWED";

  if (
    latencyBlocked ||
    spreadBlocked
  ) {

    adaptiveEntryState =
      "LIMITED";

  }

  if (
    killSwitch ||
    latencyCritical ||
    spreadCritical
  ) {

    adaptiveEntryState =
      "BLOCKED";

  }

  // =========================
  // RISK LEVEL
  // =========================

  let adaptiveRiskLevel =
    "NORMAL";

  if (
    latencyBlocked ||
    spreadBlocked
  ) {

    adaptiveRiskLevel =
      "HIGH";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    adaptiveRiskLevel =
      "CRITICAL";

  }

  if (
    killSwitch
  ) {

    adaptiveRiskLevel =
      "EMERGENCY";

  }

  // =========================
  // EXECUTION PERMISSION
  // =========================

  const executionPermission =

    !killSwitch &&
    !latencyCritical &&
    !spreadCritical;

  // =========================
  // EMERGENCY STATE
  // =========================

  const emergencyState =

    killSwitch ||
    latencyCritical ||
    spreadCritical;

  // =========================
  // GOVERNANCE DECISION
  // =========================

  let governanceDecision =
    "NORMAL_RUNTIME";

  if (
    latencyBlocked
  ) {

    governanceDecision =
      "LIMIT_EXECUTION";

  }

  if (
    spreadBlocked
  ) {

    governanceDecision =
      "SPREAD_PROTECTION";

  }

  if (
    latencyCritical
  ) {

    governanceDecision =
      "LATENCY_PROTECTION";

  }

  if (
    spreadCritical
  ) {

    governanceDecision =
      "MARKET_PROTECTION";

  }

  if (
    killSwitch
  ) {

    governanceDecision =
      "EMERGENCY_STOP";

  }

  // =========================
  // AUTO DEFENSE
  // =========================

  let autoDefenseState =
    "NORMAL";

  if (
    latencyBlocked ||
    spreadBlocked
  ) {

    autoDefenseState =
      "ACTIVE";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    autoDefenseState =
      "EMERGENCY";

  }

  // =========================
  // RISK MULTIPLIER
  // =========================

  let dynamicRiskMultiplier =
    1;

  if (
    latencyBlocked
  ) {

    dynamicRiskMultiplier =
      0.7;

  }

  if (
    spreadBlocked
  ) {

    dynamicRiskMultiplier =
      0.5;

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    dynamicRiskMultiplier =
      0.25;

  }

  if (
    killSwitch
  ) {

    dynamicRiskMultiplier =
      0;

  }

  // =========================
  // COOLDOWN TRIGGER
  // =========================

  const autoCooldownTrigger =

    latencyBlocked ||
    spreadBlocked;

  // =========================
  // SPREAD DEFENSE
  // =========================

  let spreadDefenseMode =
    "NORMAL";

  if (
    averageSpread > 0.02
  ) {

    spreadDefenseMode =
      "DEFENSIVE";

  }

  if (
    averageSpread > 0.05
  ) {

    spreadDefenseMode =
      "EMERGENCY";

  }

  // =========================
  // EXECUTION THROTTLE
  // =========================

  let executionThrottle =
    "FULL_SPEED";

  if (
    latency > 100
  ) {

    executionThrottle =
      "SOFT_LIMIT";

  }

  if (
    latency > 150
  ) {

    executionThrottle =
      "HARD_LIMIT";

  }

  // =========================
  // DEFENSE REASON
  // =========================

  let defenseReason =
    "NONE";

  if (
    spreadBlocked
  ) {

    defenseReason =
      "SPREAD_EXPANSION";

  }

  if (
    latencyBlocked
  ) {

    defenseReason =
      "LATENCY_DEGRADED";

  }

  if (
    spreadCritical
  ) {

    defenseReason =
      "SPREAD_CRITICAL";

  }

  if (
    latencyCritical
  ) {

    defenseReason =
      "LATENCY_CRITICAL";

  }

  if (
    killSwitch
  ) {

    defenseReason =
      "KILL_SWITCH";

  }

  // =========================
  // GOVERNANCE HEALTH
  // =========================

  let governanceHealth =
    "STABLE";

  if (
    adaptiveRiskLevel ===
    "HIGH"
  ) {

    governanceHealth =
      "DEGRADED";

  }

  if (
    adaptiveRiskLevel ===
    "CRITICAL"
  ) {

    governanceHealth =
      "CRITICAL";

  }

  if (
    adaptiveRiskLevel ===
    "EMERGENCY"
  ) {

    governanceHealth =
      "EMERGENCY";

  }

  // =========================
  // RETURN
  // =========================

  return {

    adaptiveEntryState,

    adaptiveRiskLevel,

    executionPermission,

    emergencyState,

    governanceDecision,

    autoDefenseState,

    dynamicRiskMultiplier,

    autoCooldownTrigger,

    spreadDefenseMode,

    executionThrottle,

    defenseReason,

    governanceHealth,

  };

}