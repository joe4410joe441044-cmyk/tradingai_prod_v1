export function scoringEngine({

  executionPacket = {},
  riskPacket = {},
  strategyPacket = {},

}) {

  // =========================
  // SAFE VALUES
  // =========================

  const latency =

    Number(
      executionPacket.latency
    ) || 0;

  const spread =

    Number(
      strategyPacket.spread
    ) || 0;

  const currentDrawdown =

    Number(
      riskPacket.currentDD
    ) || 0;

  const killSwitch =

    Boolean(
      riskPacket.killSwitch
    );

  // =========================
  // EXECUTION SCORE
  // =========================

  let executionScore =
    100;

  executionScore -=
    latency * 0.5;

  executionScore -=
    spread * 1000;

  executionScore =

    Math.max(

      0,

      Math.min(

        100,

        Math.round(
          executionScore
        )

      )

    );

  // =========================
  // MARKET SCORE
  // =========================

  let marketScore =
    100;

  marketScore -=
    spread * 1200;

  marketScore -=
    currentDrawdown * 2;

  if (
    killSwitch
  ) {

    marketScore -= 50;

  }

  marketScore =

    Math.max(

      0,

      Math.min(

        100,

        Math.round(
          marketScore
        )

      )

    );

  // =========================
  // RISK SCORE
  // =========================

  let riskScore =
    100;

  riskScore -=
    currentDrawdown * 3;

  if (
    latency > 120
  ) {

    riskScore -= 20;

  }

  if (
    spread > 0.05
  ) {

    riskScore -= 20;

  }

  if (
    killSwitch
  ) {

    riskScore = 0;

  }

  riskScore =

    Math.max(

      0,

      Math.min(

        100,

        Math.round(
          riskScore
        )

      )

    );

  // =========================
  // RUNTIME SCORE
  // =========================

  const runtimeScore =

    Math.round(

      (
        executionScore +
        marketScore +
        riskScore
      ) / 3

    );

  // =========================
  // EXECUTION GRADE
  // =========================

  let executionGrade =
    "C";

  if (
    latency < 30
  ) {

    executionGrade =
      "S";

  }

  else if (
    latency < 60
  ) {

    executionGrade =
      "A";

  }

  else if (
    latency < 100
  ) {

    executionGrade =
      "B";

  }

  // =========================
  // MARKET GRADE
  // =========================

  let marketGrade =
    "C";

  if (
    spread < 0.01
  ) {

    marketGrade =
      "S";

  }

  else if (
    spread < 0.02
  ) {

    marketGrade =
      "A";

  }

  else if (
    spread < 0.05
  ) {

    marketGrade =
      "B";

  }

  // =========================
  // GOVERNANCE HEALTH
  // =========================

  let governanceHealth =
    "CRITICAL";

  if (
    runtimeScore >= 85
  ) {

    governanceHealth =
      "STABLE";

  }

  else if (
    runtimeScore >= 65
  ) {

    governanceHealth =
      "NORMAL";

  }

  else if (
    runtimeScore >= 40
  ) {

    governanceHealth =
      "DEGRADED";

  }

  // =========================
  // EXECUTION STATUS
  // =========================

  let executionStatus =
    "BLOCKED";

  if (
    runtimeScore >= 70 &&
    !killSwitch
  ) {

    executionStatus =
      "READY";

  }

  if (
    runtimeScore >= 85 &&
    !killSwitch
  ) {

    executionStatus =
      "OPTIMAL";

  }

  if (
    killSwitch
  ) {

    executionStatus =
      "EMERGENCY_STOP";

  }

  // =========================
  // RETURN
  // =========================

  return {

    executionScore,

    marketScore,

    riskScore,

    runtimeScore,

    executionGrade,

    marketGrade,

    governanceHealth,

    executionStatus,

  };

}