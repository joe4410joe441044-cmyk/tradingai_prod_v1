// ======================================================
// GOVERNANCE EXECUTION STRATEGY
// RUNTIME EXECUTION CONDITION EVALUATOR
// ======================================================

export function microstructureStrategy({

  marketPacket,
  strategyPacket,
  executionPacket,
  derivedPacket,

}) {

  // ======================================================
  // SAFE VALUES
  // ======================================================

  const spread =
    Number(
      strategyPacket?.spread || 0
    );

  const price =
    Number(
      marketPacket?.price || 0
    );

  const latency =
    Number(
      executionPacket?.latency || 0
    );

  const executionAllowed =
    Boolean(
      derivedPacket?.executionAllowed
    );

  const executionSafety =
    derivedPacket?.executionSafety ||
    "NORMAL";

  const governanceHealth =
    derivedPacket?.governanceHealth ||
    "NORMAL";

  const marketCondition =
    derivedPacket?.marketCondition ||
    "STABLE";

  const executionPressure =
    derivedPacket?.executionPressure ||
    "LOW";
  // ======================================================
  // SPREAD CONDITIONS
  // ======================================================

  const tightSpread =
    spread < 0.01;

  const acceptableSpread =
    spread < 0.03;

  const spreadExpansion =
    spread > 0.05;

  // ======================================================
  // LATENCY CONDITIONS
  // ======================================================

  const latencyHealthy =
    latency < 80;

  const latencyCritical =
    latency > 150;

  // ======================================================
  // MARKET CONDITIONS
  // ======================================================

  const stableMarket =
    marketCondition ===
    "STABLE";

  const volatileMarket =
    marketCondition ===
    "VOLATILE";

  const unstableMarket =
    marketCondition ===
    "UNSTABLE";

  // ======================================================
  // EXECUTION CONDITIONS
  // ======================================================

  const executionHealthy =

    latencyHealthy &&
    acceptableSpread &&
    !unstableMarket;

  const marketMakingWindow =

    tightSpread &&
    latency < 30 &&
    stableMarket;
  // ======================================================
  // ROUTING STATE
  // ======================================================

  let route =
    "STANDBY";

  if (
    stableMarket &&
    executionHealthy
  ) {

    route =
      "NORMAL_EXECUTION";

  }

  if (
    volatileMarket &&
    executionHealthy
  ) {

    route =
      "LIMITED_EXECUTION";

  }

  if (
    unstableMarket
  ) {

    route =
      "BLOCKED";

  }

  // ======================================================
  // EXECUTION DECISION
  // ======================================================

  let executionState =
    "WAIT";

  if (

    executionAllowed &&
    executionHealthy &&
    stableMarket

  ) {

    executionState =
      "READY";

  }

  if (
    unstableMarket
  ) {

    executionState =
      "BLOCKED";

  }

  if (
    latencyCritical
  ) {

    executionState =
      "EMERGENCY_BLOCK";

  }
  // ======================================================
  // FAILSAFE
  // ======================================================

  const emergencyExit =

    latencyCritical ||
    spreadExpansion;

  // ======================================================
  // GOVERNANCE RISK
  // ======================================================

  let governanceRisk =
    "NORMAL";

  if (
    unstableMarket
  ) {

    governanceRisk =
      "HIGH";

  }

  if (
    latencyCritical
  ) {

    governanceRisk =
      "CRITICAL";

  }

  // ======================================================
  // EXECUTION PROFILE
  // ======================================================

  let executionProfile =
    "STANDARD";

  if (
    marketMakingWindow
  ) {

    executionProfile =
      "MARKET_MAKING";

  }

  if (
    volatileMarket
  ) {

    executionProfile =
      "LIMITED";

  }

  if (
    unstableMarket
  ) {

    executionProfile =
      "BLOCKED";

  }
  // ======================================================
  // RUNTIME STATUS
  // ======================================================

  let runtimeStatus =
    "NORMAL";

  if (
    governanceHealth ===
    "DEGRADED"
  ) {

    runtimeStatus =
      "DEGRADED";

  }

  if (
    governanceHealth ===
    "CRITICAL"
  ) {

    runtimeStatus =
      "CRITICAL";

  }

  // ======================================================
  // EXECUTION AUTHORITY
  // ======================================================

  const executionAuthority =

    executionAllowed &&
    executionSafety !==
    "BLOCKED" &&
    runtimeStatus !==
    "CRITICAL";

  // ======================================================
  // ROUTE REASON
  // ======================================================

  let routeReason =
    "NORMAL_RUNTIME";

  if (
    unstableMarket
  ) {

    routeReason =
      "UNSTABLE_MARKET";

  }

  if (
    latencyCritical
  ) {

    routeReason =
      "LATENCY_CRITICAL";

  }
  // ======================================================
  // FINAL GOVERNANCE PACKET
  // ======================================================

  return {

    // execution

    executionAllowed:
      executionAuthority,

    executionState,

    executionProfile,

    emergencyExit,

    // governance

    governanceRisk,

    governanceHealth,

    runtimeStatus,

    // routing

    route,

    routeReason,

    // market

    marketCondition,

    stableMarket,

    volatileMarket,

    unstableMarket,

    // spread

    spread,

    tightSpread,

    acceptableSpread,

    spreadExpansion,

    // latency

    latency,

    latencyHealthy,

    latencyCritical,

    // execution

    executionPressure,

    executionSafety,

    marketMakingWindow,

    // misc

    price,

  };

}
