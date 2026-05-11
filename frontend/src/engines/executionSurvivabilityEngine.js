export function executionSurvivabilityEngine({

  marketIntel = {},
  strategyIntel = {},
  executionData = {},
  signalIntel = {},

}) {

  // =========================
  // SAFE VALUES
  // =========================

  const latency =

    Number(
      executionData.latency
    ) || 0;

  const spread =

    Number(
      strategyIntel.spread
    ) || 0;

  const spoofProbability =

    Number(
      signalIntel.spoofProbability
    ) || 0;

  const confidenceScore =

    Number(
      signalIntel.confidenceScore
    ) || 0;

  const adaptiveConfidence =

    Number(
      marketIntel.adaptiveConfidence
    ) || 0;

  // =========================
  // LATENCY DANGER
  // =========================

  const latencyDanger =

    latency > 150;

  const latencyWarning =

    latency > 80;

  // =========================
  // LIQUIDITY DANGER
  // =========================

  const liquidityDanger =

    marketIntel.liquidityCollapse ||

    spread > 1.5;

  // =========================
  // SPOOF DANGER
  // =========================

  const spoofDanger =

    spoofProbability > 70 ||

    signalIntel.fakeWall;

  // =========================
  // MARKET DANGER
  // =========================

  const marketDanger =

    marketIntel.marketPhase ===
      "CHAOTIC" ||

    marketIntel.marketRisk ===
      "HIGH";

  // =========================
  // SPREAD SHOCK
  // =========================

  const spreadShock =

    marketIntel.spreadShock ||

    spread > (
      (
        Number(
          marketIntel.avgSpread
        ) || 0
      ) * 2
    );

  // =========================
  // EXECUTION CONFIDENCE
  // =========================

  let executionConfidence =

    (
      confidenceScore * 0.5
    ) +

    (
      adaptiveConfidence * 0.5
    );

  if (latencyDanger) {
    executionConfidence -= 40;
  }

  if (liquidityDanger) {
    executionConfidence -= 30;
  }

  if (spoofDanger) {
    executionConfidence -= 25;
  }

  if (spreadShock) {
    executionConfidence -= 20;
  }

  executionConfidence =

    Math.max(
      0,
      Math.min(
        100,
        Math.round(
          executionConfidence
        )
      )
    );

  // =========================
  // SURVIVAL MODE
  // =========================

  const survivalMode =

    latencyDanger ||
    liquidityDanger ||
    spoofDanger ||
    marketDanger

      ? "DEFENSIVE"

      : executionConfidence > 80

      ? "OFFENSIVE"

      : "NORMAL";

  // =========================
  // ENTRY BLOCK
  // =========================

  const entryBlocked =

    latencyDanger ||

    liquidityDanger ||

    spoofDanger ||

    marketDanger ||

    spreadShock ||

    executionConfidence < 35;

  // =========================
  // EXECUTION ALLOWED
  // =========================

  const executionAllowed =

    !entryBlocked;

  // =========================
  // EMERGENCY EXIT
  // =========================

  const emergencyExit =

    (
      latencyDanger &&
      spoofDanger
    ) ||

    (
      liquidityDanger &&
      spreadShock
    ) ||

    (
      marketDanger &&
      executionConfidence < 20
    );

  // =========================
  // EXECUTION PRESSURE
  // =========================

  const executionPressure =

    latency > 150

      ? "EXTREME"

      : latency > 80

      ? "HIGH"

      : latency > 40

      ? "NORMAL"

      : "LOW";

  // =========================
  // SURVIVABILITY SCORE
  // =========================

  const survivabilityScore =

    Math.max(

      0,

      Math.min(

        100,

        Math.round(

          100 -

          (
            latency * 0.25
          ) -

          (
            spread * 15
          ) -

          (
            spoofProbability * 0.4
          )

        )

      )

    );

  // =========================
  // AI EXECUTION STATE
  // =========================

  const executionState =

    emergencyExit

      ? "EMERGENCY_EXIT"

      : entryBlocked

      ? "BLOCKED"

      : executionAllowed

      ? "ACTIVE"

      : "WAIT";

  return {

    latencyDanger,

    latencyWarning,

    liquidityDanger,

    spoofDanger,

    marketDanger,

    spreadShock,

    executionConfidence,

    survivalMode,

    entryBlocked,

    executionAllowed,

    emergencyExit,

    executionPressure,

    survivabilityScore,

    executionState,

  };

}