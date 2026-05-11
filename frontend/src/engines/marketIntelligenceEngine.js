export function marketIntelligenceEngine({

  momentumHistory,
  spreadHistory,
  latencyHistory,

  strategyData,

}) {

  // =========================
  // SAFE DATA
  // =========================

  const safeMomentumHistory =
    Array.isArray(momentumHistory)
      ? momentumHistory
      : [];

  const safeSpreadHistory =
    Array.isArray(spreadHistory)
      ? spreadHistory
      : [];

  const safeLatencyHistory =
    Array.isArray(latencyHistory)
      ? latencyHistory
      : [];

  const momentum =
    Number(strategyData?.momentum) || 0;

  const spread =
    Number(strategyData?.spread) || 0;

  // =========================
  // ROLLING AVERAGES
  // =========================

  const avgMomentum =

    safeMomentumHistory.length > 0

      ? safeMomentumHistory.reduce(
          (a, b) => a + b,
          0
        ) / safeMomentumHistory.length

      : 0;

  const avgSpread =

    safeSpreadHistory.length > 0

      ? safeSpreadHistory.reduce(
          (a, b) => a + b,
          0
        ) / safeSpreadHistory.length

      : 0;

  const avgLatency =

    safeLatencyHistory.length > 0

      ? safeLatencyHistory.reduce(
          (a, b) => a + b,
          0
        ) / safeLatencyHistory.length

      : 0;

  // =========================
  // VOLATILITY REGIME
  // =========================

  const volatilityRegime =

    avgSpread > 2

      ? "EXTREME VOL"

      : avgSpread > 1

      ? "HIGH VOL"

      : avgSpread > 0.5

      ? "NORMAL VOL"

      : "LOW VOL";

  // =========================
  // MOMENTUM
  // =========================

  const momentumAcceleration =

    momentum -
    avgMomentum;

  const momentumRegime =

    momentumAcceleration > 3

      ? "EXPLOSIVE"

      : momentumAcceleration > 1.5

      ? "FAST"

      : momentumAcceleration > 0.5

      ? "RISING"

      : momentumAcceleration < -2

      ? "REVERSAL"

      : "NORMAL";

  // =========================
  // LIQUIDITY
  // =========================

  const liquidityStability =

    avgSpread < 0.3 &&
    avgLatency < 40

      ? "STABLE"

      : avgSpread < 1 &&
        avgLatency < 80

      ? "WEAK"

      : "COLLAPSING";

  // =========================
  // SPREAD SHOCK
  // =========================

  const spreadShock =

    spread >
    Math.max(
      0.0001,
      avgSpread * 2
    );

  // =========================
  // LIQUIDITY COLLAPSE
  // =========================

  const liquidityCollapse =

    avgSpread > 1.5 ||

    avgLatency > 120 ||

    spreadShock;

  // =========================
  // EXECUTION SURVIVABILITY
  // =========================

  const executionSurvivability =

    liquidityCollapse

      ? "CRITICAL"

      : avgLatency > 80

      ? "WEAK"

      : avgLatency > 40

      ? "DEGRADED"

      : "STABLE";

  // =========================
  // TREND STRENGTH
  // =========================

  const trendStrength =

    Math.abs(
      momentumAcceleration
    ) *

    (
      avgSpread > 0
        ? (
            1 / avgSpread
          )
        : 1
    );

  // =========================
  // MARKET TEMPERATURE
  // =========================

  const marketTemperature =

    liquidityCollapse

      ? "OVERHEATED"

      : volatilityRegime ===
        "EXTREME VOL"

      ? "HOT"

      : volatilityRegime ===
        "HIGH VOL"

      ? "ACTIVE"

      : "COOL";

  // =========================
  // EXECUTION ENVIRONMENT
  // =========================

  const executionEnvironment =

    executionSurvivability ===
    "CRITICAL"

      ? "UNSAFE"

      : executionSurvivability ===
        "WEAK"

      ? "DEFENSIVE"

      : "NORMAL";

  // =========================
  // MARKET PHASE
  // =========================

  const marketPhase =

    liquidityCollapse

      ? "CHAOTIC"

      : momentumRegime ===
        "EXPLOSIVE"

      ? "BREAKOUT"

      : momentumRegime ===
        "FAST"

      ? "TRENDING"

      : momentumRegime ===
        "REVERSAL"

      ? "REVERSAL"

      : volatilityRegime ===
        "HIGH VOL"

      ? "VOLATILE RANGE"

      : "RANGING";

  // =========================
  // EXECUTION PRESSURE
  // =========================

  const executionPressure =

    avgLatency > 100

      ? "EXTREME"

      : avgLatency > 60

      ? "HIGH"

      : avgLatency > 30

      ? "NORMAL"

      : "LOW";

  // =========================
  // LIQUIDITY SCORE
  // =========================

  const liquidityScore =

    liquidityStability ===
    "STABLE"

      ? 90

      : liquidityStability ===
        "WEAK"

      ? 55

      : 15;

  // =========================
  // MARKET RISK
  // =========================

  const marketRisk =

    liquidityCollapse

      ? "HIGH"

      : spreadShock

      ? "MEDIUM"

      : "LOW";

  // =========================
  // ADAPTIVE CONFIDENCE
  // =========================

  const adaptiveConfidence =

    Math.max(

      0,

      Math.min(

        100,

        Math.round(

          (
            Math.abs(
              momentumAcceleration
            ) * 20
          ) +

          (
            liquidityScore * 0.5
          ) -

          (
            avgLatency * 0.2
          )

        )

      )

    );

  return {

    avgMomentum,
    avgSpread,
    avgLatency,

    volatilityRegime,

    momentumAcceleration,
    momentumRegime,

    liquidityStability,

    spreadShock,

    liquidityCollapse,

    executionSurvivability,

    trendStrength,

    marketTemperature,

    executionEnvironment,

    marketPhase,

    executionPressure,

    liquidityScore,

    marketRisk,

    adaptiveConfidence,

  };

}