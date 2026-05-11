function sanitizeNumber(value, fallback = 0) {
  if (value === null || value === undefined) {
    return fallback;
  }

  if (Number.isNaN(value)) {
    return fallback;
  }

  if (!Number.isFinite(Number(value))) {
    return fallback;
  }

  return Number(value);
}

function fallbackNumeric(value, fallback = 0) {
  return sanitizeNumber(value, fallback);
}

function safeDivide(a, b, fallback = 0) {
  const numerator = sanitizeNumber(a, 0);
  const denominator = sanitizeNumber(b, 0);

  if (denominator === 0) {
    return fallback;
  }

  const result = numerator / denominator;

  return sanitizeNumber(result, fallback);
}

function clampConfidence(value) {
  const sanitized = sanitizeNumber(value, 0);

  if (sanitized < 0) {
    return 0;
  }

  if (sanitized > 100) {
    return 100;
  }

  return sanitized;
}

export function interpretationEngine({

  volatilityRegime,

  momentumRegime,

  liquidityStability,

  executionPacket,

  intelligencePacket,

  momentumAcceleration,

  avgSpread,

}) {

  const safeLatency = sanitizeNumber(
    executionPacket?.latency,
    999
  );

  const safeSpoofProbability = clampConfidence(
    intelligencePacket?.spoofProbability
  );

  const safeAvgSpread = sanitizeNumber(
    avgSpread,
    0
  );

  const safeMomentumAcceleration = sanitizeNumber(
    momentumAcceleration,
    0
  );

  const marketPhase =

    volatilityRegime === "EXTREME VOL"

      ? "CHAOTIC"

      : momentumRegime === "EXPLOSIVE"

      ? "TRENDING"

      : liquidityStability === "COLLAPSING"

      ? "UNSTABLE"

      : "BALANCED";

  const executionHealth =

    safeLatency < 40

      ? "EXCELLENT"

      : safeLatency < 80

      ? "NORMAL"

      : "DEGRADED";

  const rawTradeabilityScore =

    100 -
    safeLatency -
    safeSpoofProbability -
    safeAvgSpread * 10;

  const tradeabilityScore = clampConfidence(
    sanitizeNumber(rawTradeabilityScore, 0)
  );

  const liquidityConfidence =

    liquidityStability === "STABLE"

      ? 90

      : liquidityStability === "WEAK"

      ? 60

      : 20;

  const stabilizedLiquidityConfidence =
    clampConfidence(liquidityConfidence);

  const regimeShiftDetection =

    safeMomentumAcceleration > 3 &&

    safeAvgSpread > 1;

  const executionConfidence = clampConfidence(

    tradeabilityScore * 0.55 +

    stabilizedLiquidityConfidence * 0.45

  );

  const aggressionScore = clampConfidence(

    safeMomentumAcceleration * 18 -

    safeAvgSpread * 6

  );

  const realtimeConfidenceState =

    executionConfidence >= 80

      ? "HIGH"

      : executionConfidence >= 50

      ? "MEDIUM"

      : "LOW";

  const runtimeSynchronizationState =

    safeLatency < 80 &&

    !regimeShiftDetection

      ? "STABLE"

      : "UNSTABLE";

  return {

    marketPhase,

    executionHealth,

    tradeabilityScore,

    liquidityConfidence:
      stabilizedLiquidityConfidence,

    regimeShiftDetection,

    executionConfidence,

    aggressionScore,

    realtimeConfidenceState,

    runtimeSynchronizationState,

    telemetry: {

      realtimeSpread:
        safeAvgSpread,

      momentumAcceleration:
        safeMomentumAcceleration,

      executionLatency:
        safeLatency,

      spoofProbability:
        safeSpoofProbability,

    },

  };

}