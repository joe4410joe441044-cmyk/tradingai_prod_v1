export function positionSizingEngine({

  executionPacket = {},
  riskPacket = {},

  spread = 0,

}) {

  // =========================
  // SAFE VALUES
  // =========================

  const latency =

    Number(
      executionPacket.latency
    ) || 0;

  const currentDrawdown =

    Number(
      riskPacket.currentDD
    ) || 0;

  const safeSpread =

    Number(
      spread
    ) || 0;

  const killSwitch =

    Boolean(
      riskPacket.killSwitch
    );

  // =========================
  // LATENCY STATES
  // =========================

  const latencyWarning =

    latency > 80;

  const latencyDanger =

    latency > 120;

  const latencyCritical =

    latency > 180;

  // =========================
  // SPREAD STATES
  // =========================

  const spreadWarning =

    safeSpread > 0.02;

  const spreadDanger =

    safeSpread > 0.05;

  const spreadCritical =

    safeSpread > 0.1;

  // =========================
  // POSITION MULTIPLIER
  // =========================

  let dynamicPositionMultiplier =
    1;

  if (
    latencyWarning ||
    spreadWarning
  ) {

    dynamicPositionMultiplier =
      0.7;

  }

  if (
    latencyDanger ||
    spreadDanger
  ) {

    dynamicPositionMultiplier =
      0.5;

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    dynamicPositionMultiplier =
      0.25;

  }

  if (
    killSwitch
  ) {

    dynamicPositionMultiplier =
      0;

  }

  // =========================
  // RISK POSITIONING
  // =========================

  let riskAdaptivePositioning =
    "NORMAL";

  if (
    latencyDanger ||
    spreadDanger
  ) {

    riskAdaptivePositioning =
      "REDUCED";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    riskAdaptivePositioning =
      "MINIMAL";

  }

  if (
    killSwitch
  ) {

    riskAdaptivePositioning =
      "BLOCKED";

  }

  // =========================
  // RISK EXPOSURE
  // =========================

  let suggestedRisk =
    1.0;

  if (
    latencyWarning ||
    spreadWarning
  ) {

    suggestedRisk =
      0.7;

  }

  if (
    latencyDanger ||
    spreadDanger
  ) {

    suggestedRisk =
      0.5;

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    suggestedRisk =
      0.25;

  }

  if (
    killSwitch
  ) {

    suggestedRisk =
      0;

  }

  // =========================
  // POSITION SCALING
  // =========================

  let positionScalingState =
    "NORMAL";

  if (
    latencyWarning ||
    spreadWarning
  ) {

    positionScalingState =
      "SCALE_DOWN";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    positionScalingState =
      "MINIMAL";

  }

  // =========================
  // EXPOSURE CONTROL
  // =========================

  let exposureControl =
    "OPEN";

  if (
    latencyDanger ||
    spreadDanger
  ) {

    exposureControl =
      "RESTRICTED";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    exposureControl =
      "BLOCKED";

  }

  if (
    killSwitch
  ) {

    exposureControl =
      "EMERGENCY_STOP";

  }

  // =========================
  // CAPITAL PROTECTION
  // =========================

  const capitalProtectionMode =

    currentDrawdown > 5 ||

    latencyDanger ||

    spreadDanger ||

    killSwitch;

  // =========================
  // POSITION LIMIT
  // =========================

  let maxPositionExposure =
    1.0;

  if (
    currentDrawdown > 3
  ) {

    maxPositionExposure =
      0.7;

  }

  if (
    currentDrawdown > 5
  ) {

    maxPositionExposure =
      0.5;

  }

  if (
    currentDrawdown > 8
  ) {

    maxPositionExposure =
      0.25;

  }

  if (
    killSwitch
  ) {

    maxPositionExposure =
      0;

  }

  // =========================
  // EXECUTION PROFILE
  // =========================

  let executionProfile =
    "STANDARD";

  if (
    latencyWarning ||
    spreadWarning
  ) {

    executionProfile =
      "LIMITED";

  }

  if (
    latencyCritical ||
    spreadCritical
  ) {

    executionProfile =
      "DEFENSIVE";

  }

  if (
    killSwitch
  ) {

    executionProfile =
      "EMERGENCY";

  }

  // =========================
  // RETURN
  // =========================

  return {

    dynamicPositionMultiplier,

    riskAdaptivePositioning,

    suggestedRisk,

    positionScalingState,

    exposureControl,

    capitalProtectionMode,

    maxPositionExposure,

    executionProfile,

  };

}