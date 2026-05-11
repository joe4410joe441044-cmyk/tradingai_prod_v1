export function permissionEngine({

  riskPacket,
  executionPacket,
  intelligencePacket,

  liquidityStability,

  aiCompositeScore,

  executionScore,
  marketSurvivabilityScore,
  liquidityScore,
  trendQualityScore,

}) {

  const entryPermissionState =

    riskPacket.killSwitch

      ? "REJECTED"

      : executionPacket.latency > 150

      ? "REJECTED"

      : intelligencePacket.spoofProbability > 85

      ? "REJECTED"

      : liquidityStability === "COLLAPSING"

      ? "LIMITED"

      : aiCompositeScore > 75

      ? "APPROVED"

      : "LIMITED";

  const entryApprovalScore =

    Math.round(

      (
        executionScore +

        marketSurvivabilityScore +

        liquidityScore +

        trendQualityScore
      ) / 4
    );

  const aiTradeRejection =

    riskPacket.killSwitch ||

    executionPacket.latency > 150 ||

    intelligencePacket.spoofProbability > 90 ||

    liquidityStability === "COLLAPSING";

  const rejectionReason =

    riskPacket.killSwitch

      ? "KILL SWITCH"

      : executionPacket.latency > 150

      ? "LATENCY CRITICAL"

      : intelligencePacket.spoofProbability > 90

      ? "SPOOF RISK"

      : liquidityStability === "COLLAPSING"

      ? "LIQUIDITY COLLAPSE"

      : "NONE";

  const executionPriority =

    aiCompositeScore > 80

      ? "MAXIMUM"

      : aiCompositeScore > 60

      ? "HIGH"

      : aiCompositeScore > 40

      ? "NORMAL"

      : "LOW";

  const aiExecutionMode =

    aiCompositeScore > 80

      ? "AGGRESSIVE"

      : aiCompositeScore > 60

      ? "BALANCED"

      : "DEFENSIVE";

  return {

    entryPermissionState,

    entryApprovalScore,

    aiTradeRejection,

    rejectionReason,

    executionPriority,

    aiExecutionMode,

  };

}