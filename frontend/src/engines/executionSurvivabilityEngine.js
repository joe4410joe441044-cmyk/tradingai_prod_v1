export function executionSurvivabilityEngine({

  executionData = {},
  riskData = {},

  spread = 0,
  latency = 0,

}) {

  // =========================
  // SAFE VALUES
  // =========================

  const safeLatency =

    Number(
      latency ??
      executionData.latency
    ) || 0;

  const safeSpread =

    Number(
      spread
    ) || 0;

  const killSwitch =

    Boolean(
      riskData.killSwitch
    );

  // =========================
  // LATENCY STATE
  // =========================

  const latencyDanger =

    safeLatency > 150;

  const latencyWarning =

    safeLatency > 80;

  const latencyCritical =

    safeLatency > 220;

  // =========================
  // SPREAD STATE
  // =========================

  const spreadDanger =

    safeSpread > 0.05;

  const spreadWarning =

    safeSpread > 0.02;

  const spreadCritical =

    safeSpread > 0.1;

  // =========================
  // MARKET HEALTH
  // =========================

  const marketHealthy =

    !spreadDanger &&
    !spreadCritical;

  const executionHealthy =

    !latencyDanger &&
    !latencyCritical;

  // =========================
  // EXECUTION PRESSURE
  // =========================

  let executionPressure =
    "LOW";

  if (
    safeLatency > 40
  ) {

    executionPressure =
      "NORMAL";

  }

  if (
    safeLatency > 80
  ) {

    executionPressure =
      "HIGH";

  }

  if (
    safeLatency > 150
  ) {

    executionPressure =
      "EXTREME";

  }

  // =========================
  // EXECUTION SAFETY
  // =========================

  let executionSafety =
    "NORMAL";

  if (
    latencyWarning ||
    spreadWarning
  ) {

    executionSafety =
      "LIMITED";

  }

  if (
    latencyDanger ||
    spreadDanger
  ) {

    executionSafety =
      "BLOCKED";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    executionSafety =
      "CRITICAL";

  }

  // =========================
  // ENTRY BLOCK
  // =========================

  const entryBlocked =

    latencyDanger ||

    spreadDanger ||

    killSwitch;

  // =========================
  // EXECUTION ALLOWED
  // =========================

  const executionAllowed =

    !entryBlocked;

  // =========================
  // FAILSAFE
  // =========================

  const emergencyExit =

    latencyCritical ||

    spreadCritical ||

    killSwitch;

  // =========================
  // SURVIVAL MODE
  // =========================

  let survivalMode =
    "NORMAL";

  if (
    executionSafety ===
    "LIMITED"
  ) {

    survivalMode =
      "DEFENSIVE";

  }

  if (
    executionSafety ===
    "BLOCKED"
  ) {

    survivalMode =
      "SURVIVAL";

  }

  if (
    executionSafety ===
    "CRITICAL"
  ) {

    survivalMode =
      "EMERGENCY";

  }

  // =========================
  // EXECUTION SCORE
  // =========================

  let survivabilityScore =
    100;

  survivabilityScore -=
    safeLatency * 0.25;

  survivabilityScore -=
    safeSpread * 1200;

  if (
    killSwitch
  ) {

    survivabilityScore -=
      50;

  }

  survivabilityScore =

    Math.max(

      0,

      Math.min(

        100,

        Math.round(
          survivabilityScore
        )

      )

    );

  // =========================
  // EXECUTION STATE
  // =========================

  let executionState =
    "WAIT";

  if (
    executionAllowed
  ) {

    executionState =
      "ACTIVE";

  }

  if (
    entryBlocked
  ) {

    executionState =
      "BLOCKED";

  }

  if (
    emergencyExit
  ) {

    executionState =
      "EMERGENCY_EXIT";

  }

  // =========================
  // GOVERNANCE HEALTH
  // =========================

  let governanceHealth =
    "STABLE";

  if (
    executionSafety ===
    "LIMITED"
  ) {

    governanceHealth =
      "DEGRADED";

  }

  if (
    executionSafety ===
    "BLOCKED"
  ) {

    governanceHealth =
      "CRITICAL";

  }

  // =========================
  // RETURN
  // =========================

  return {

    latencyDanger,

    latencyWarning,

    latencyCritical,

    spreadDanger,

    spreadWarning,

    spreadCritical,

    marketHealthy,

    executionHealthy,

    executionPressure,

    executionSafety,

    entryBlocked,

    executionAllowed,

    emergencyExit,

    survivalMode,

    survivabilityScore,

    executionState,

    governanceHealth,

  };

}