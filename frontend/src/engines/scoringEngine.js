export function scoringEngine({

  executionPacket,
  intelligencePacket,
  riskPacket,

  strategyPacket,

  momentumAcceleration,

  liquidityStability,

  avgSpread,

}) {

  const executionScore =

    Math.max(

      0,

      100 -

      executionPacket.latency -

      intelligencePacket.spoofProbability -

      avgSpread * 12
    );

  const marketSurvivabilityScore =

    Math.max(

      0,

      100 -

      riskPacket.currentDD * 2 -

      intelligencePacket.spoofProbability
    );

  const trendQualityScore =

    Math.min(

      100,

      Math.abs(
        momentumAcceleration
      ) * 20
    );

  const liquidityScore =

    liquidityStability === "STABLE"

      ? 100

      : liquidityStability === "WEAK"

      ? 60

      : 20;

  const entryConfidenceScore =

    Math.max(

      0,

      (
        strategyPacket.edge * 15 +

        intelligencePacket.confidenceScore +

        (
          liquidityStability === "STABLE"
            ? 20
            : 0
        )
      )
    );

  const aiCompositeScore =

    Math.round(

      (
        executionScore +

        liquidityScore +

        trendQualityScore
      ) / 3
    );

  const executionGrade =

    executionPacket.latency < 40

      ? "S"

      : executionPacket.latency < 70

      ? "A"

      : executionPacket.latency < 100

      ? "B"

      : "C";

  return {

    executionScore,

    marketSurvivabilityScore,

    trendQualityScore,

    liquidityScore,

    entryConfidenceScore,

    aiCompositeScore,

    executionGrade,

  };

}