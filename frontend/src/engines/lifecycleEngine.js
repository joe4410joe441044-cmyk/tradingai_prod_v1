export function lifecycleEngine({

  marketData,

  aiCompositeScore,

  aiTradeRejection,

  executionPacket,
  intelligencePacket,
  riskPacket,

  volatilityRegime,
  momentumRegime,
  liquidityStability,

}) {

  const tradeLifecycleState =

    marketData.position === "NONE"

      ? "WAITING ENTRY"

      : aiCompositeScore > 80

      ? "ACTIVE MANAGEMENT"

      : "DEFENSIVE MANAGEMENT";

  const aiHoldDecision =

    aiCompositeScore > 70 &&

    !aiTradeRejection;

  const aiPartialCloseTrigger =

    executionPacket.latency > 120 ||

    intelligencePacket.spoofProbability > 80 ||

    volatilityRegime === "EXTREME VOL";

  const aiEmergencyExit =

    riskPacket.killSwitch ||

    executionPacket.latency > 180 ||

    intelligencePacket.spoofProbability > 95;

  const aiTimeExitMode =

    momentumRegime === "NORMAL" &&

    aiCompositeScore < 40

      ? "FAST EXIT"

      : "NORMAL HOLD";

  const aiProfitProtection =

    marketData.pnl > 0 &&

    volatilityRegime === "EXTREME VOL";

  const aiTradeManagementMode =

    momentumRegime === "EXPLOSIVE"

      ? "TREND MANAGEMENT"

      : liquidityStability === "COLLAPSING"

      ? "DEFENSIVE MANAGEMENT"

      : "NORMAL MANAGEMENT";

  return {

    tradeLifecycleState,

    aiHoldDecision,

    aiPartialCloseTrigger,

    aiEmergencyExit,

    aiTimeExitMode,

    aiProfitProtection,

    aiTradeManagementMode,

  };

}