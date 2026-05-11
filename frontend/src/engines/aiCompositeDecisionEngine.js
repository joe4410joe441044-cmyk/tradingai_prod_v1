export function aiCompositeDecisionEngine({

  marketIntel = {},
  scoringPacket = {},
  permissionPacket = {},
  interpretationPacket = {},
  executionSurvival = {},

}) {

  // =========================
  // SAFE VALUES
  // =========================

  const aiCompositeScore =

    Number(
      scoringPacket.aiCompositeScore
    ) || 0;

  const executionScore =

    Number(
      scoringPacket.executionScore
    ) || 0;

  const tradeabilityScore =

    Number(
      interpretationPacket.tradeabilityScore
    ) || 0;

  const adaptiveConfidence =

    Number(
      marketIntel.adaptiveConfidence
    ) || 0;

  const executionConfidence =

    Number(
      executionSurvival.executionConfidence
    ) || 0;

  const survivabilityScore =

    Number(
      executionSurvival.survivabilityScore
    ) || 0;

  // =========================
  // AI CONVICTION
  // =========================

  const aiConviction =

    Math.round(

      (

        aiCompositeScore * 0.25 +

        executionScore * 0.15 +

        tradeabilityScore * 0.20 +

        adaptiveConfidence * 0.20 +

        executionConfidence * 0.10 +

        survivabilityScore * 0.10

      )

    );

  // =========================
  // MARKET STATE
  // =========================

  const chaoticMarket =

    marketIntel.marketPhase ===
      "CHAOTIC" ||

    marketIntel.liquidityCollapse;

  const trendingMarket =

    marketIntel.marketPhase ===
      "TRENDING" ||

    marketIntel.marketPhase ===
      "BREAKOUT";

  const rangingMarket =

    marketIntel.marketPhase ===
      "RANGING";

  // =========================
  // RISK STATE
  // =========================

  const aiRiskState =

    chaoticMarket

      ? "HIGH RISK"

      : executionSurvival.spoofDanger

      ? "MANIPULATED"

      : executionSurvival.latencyDanger

      ? "LATENCY RISK"

      : aiConviction > 80

      ? "OPTIMAL"

      : aiConviction > 60

      ? "FAVORABLE"

      : "NEUTRAL";

  // =========================
  // TRADE BIAS
  // =========================

  const tradeBias =

    trendingMarket

      ? "TREND_FOLLOW"

      : rangingMarket

      ? "MEAN_REVERSION"

      : "DEFENSIVE";

  // =========================
  // ENTRY PRIORITY
  // =========================

  const entryPriority =

    aiConviction > 90

      ? "MAXIMUM"

      : aiConviction > 75

      ? "HIGH"

      : aiConviction > 55

      ? "NORMAL"

      : aiConviction > 40

      ? "LOW"

      : "BLOCKED";

  // =========================
  // AI DECISION
  // =========================

  let aiDecision = "WAIT";

  if (
    executionSurvival.emergencyExit
  ) {

    aiDecision =
      "EMERGENCY_EXIT";

  } else if (
    chaoticMarket
  ) {

    aiDecision =
      "BLOCK";

  } else if (
    permissionPacket.aiTradeAllowed &&
    aiConviction > 75
  ) {

    aiDecision =
      "BUY";

  } else if (
    permissionPacket.aiTradeAllowed &&
    aiConviction > 55
  ) {

    aiDecision =
      "SCALP";

  } else if (
    executionSurvival.entryBlocked
  ) {

    aiDecision =
      "BLOCK";

  }

  // =========================
  // FINAL ACTION
  // =========================

  const finalAction =

    aiDecision ===
    "BUY"

      ? "EXECUTE_LONG"

      : aiDecision ===
        "SCALP"

      ? "EXECUTE_MICRO"

      : aiDecision ===
        "EMERGENCY_EXIT"

      ? "FORCE_EXIT"

      : aiDecision ===
        "BLOCK"

      ? "NO_TRADE"

      : "WAIT";

  // =========================
  // EXECUTION PROFILE
  // =========================

  const executionProfile =

    aiConviction > 85 &&
    tradeabilityScore > 70

      ? "AGGRESSIVE"

      : aiConviction > 60

      ? "BALANCED"

      : "DEFENSIVE";

  // =========================
  // MARKET READINESS
  // =========================

  const marketReadiness =

    aiConviction > 80 &&
    !chaoticMarket &&
    !executionSurvival.entryBlocked;

  // =========================
  // AI SENTIMENT
  // =========================

  const aiSentiment =

    aiConviction > 80

      ? "STRONGLY_BULLISH"

      : aiConviction > 60

      ? "BULLISH"

      : aiConviction > 40

      ? "NEUTRAL"

      : "DEFENSIVE";

  return {

    aiConviction,

    aiRiskState,

    tradeBias,

    entryPriority,

    aiDecision,

    finalAction,

    executionProfile,

    marketReadiness,

    aiSentiment,

  };

}