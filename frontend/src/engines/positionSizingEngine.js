export function positionSizingEngine({

  aiCompositeScore,

  volatilityRegime,
  liquidityStability,
  momentumRegime,

  executionPacket,
  intelligencePacket,

  riskPacket,

}) {

  const dynamicPositionMultiplier =

    aiCompositeScore > 85

      ? 1.5

      : aiCompositeScore > 70

      ? 1.2

      : aiCompositeScore > 50

      ? 1

      : aiCompositeScore > 30

      ? 0.5

      : 0.25;

  const riskAdaptivePositioning =

    volatilityRegime === "EXTREME VOL"

      ? "REDUCED"

      : liquidityStability === "COLLAPSING"

      ? "MINIMAL"

      : aiCompositeScore > 80

      ? "EXPANDED"

      : "NORMAL";

  const aiSuggestedRisk =

    aiCompositeScore > 80

      ? 2.0

      : aiCompositeScore > 60

      ? 1.0

      : 0.5;

  const positionScalingState =

    momentumRegime === "EXPLOSIVE" &&

    liquidityStability === "STABLE"

      ? "SCALE UP"

      : volatilityRegime === "EXTREME VOL"

      ? "SCALE DOWN"

      : "NORMAL";

  const exposureControl =

    executionPacket.latency > 120 ||

    intelligencePacket.spoofProbability > 80

      ? "RESTRICTED"

      : "OPEN";

  const capitalProtectionMode =

    riskPacket.currentDD > 5 ||

    liquidityStability === "COLLAPSING";

  return {

    dynamicPositionMultiplier,

    riskAdaptivePositioning,

    aiSuggestedRisk,

    positionScalingState,

    exposureControl,

    capitalProtectionMode,

  };

}