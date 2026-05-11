export default function decisionTraceEngine({

  derivedPacket,

}) {

  const entryReasons = [];

  const blockReasons = [];

  const riskReasons = [];

  const executionReasons = [];

  // =========================
  // ENTRY REASONS
  // =========================

  if (
    derivedPacket.momentumRegime
    === "STRONG"
  ) {

    entryReasons.push(
      "STRONG_MOMENTUM"
    );

  }

  if (
    derivedPacket.momentumRegime
    === "EXPLOSIVE"
  ) {

    entryReasons.push(
      "EXPLOSIVE_MOMENTUM"
    );

  }

  if (
    derivedPacket.spreadRegime
    === "TIGHT"
  ) {

    entryReasons.push(
      "TIGHT_SPREAD"
    );

  }

  if (
    derivedPacket.marketPhase
    === "BREAKOUT"
  ) {

    entryReasons.push(
      "BREAKOUT_PHASE"
    );

  }

  if (
    derivedPacket.tradeProbability
    > 80
  ) {

    entryReasons.push(
      "HIGH_TRADE_PROBABILITY"
    );

  }

  // =========================
  // BLOCK REASONS
  // =========================

  if (
    derivedPacket.spoofDanger
  ) {

    blockReasons.push(
      "SPOOF_DANGER"
    );

  }

  if (
    derivedPacket.latencySpike
  ) {

    blockReasons.push(
      "LATENCY_SPIKE"
    );

  }

  if (
    derivedPacket.liquidityCollapse
  ) {

    blockReasons.push(
      "LIQUIDITY_COLLAPSE"
    );

  }

  if (
    derivedPacket.noTradeZone
  ) {

    blockReasons.push(
      "NO_TRADE_ZONE"
    );

  }

  // =========================
  // RISK REASONS
  // =========================

  if (
    derivedPacket.riskBias
    === "SURVIVAL"
  ) {

    riskReasons.push(
      "SURVIVAL_MODE"
    );

  }

  if (
    derivedPacket.volatilityRegime
    === "EXTREME"
  ) {

    riskReasons.push(
      "EXTREME_VOLATILITY"
    );

  }

  if (
    derivedPacket.entryAggression
    === "SCALP_ONLY"
  ) {

    riskReasons.push(
      "SCALP_ONLY_ENVIRONMENT"
    );

  }

  // =========================
  // EXECUTION REASONS
  // =========================

  if (
    derivedPacket.executionMode
    === "PASSIVE_LIMIT"
  ) {

    executionReasons.push(
      "PASSIVE_EXECUTION_DUE_TO_VOLATILITY"
    );

  }

  if (
    derivedPacket.executionMode
    === "MARKET"
  ) {

    executionReasons.push(
      "FAST_MARKET_EXECUTION"
    );

  }

  if (
    derivedPacket.slippageDanger
  ) {

    executionReasons.push(
      "SLIPPAGE_DEFENSE_ACTIVE"
    );

  }

  // =========================
  // AI SUMMARY
  // =========================

  let aiSummary =
    "NEUTRAL_MARKET";

  if (
    derivedPacket.marketPhase
    === "BREAKOUT"
  ) {

    aiSummary =
      "BREAKOUT_ENVIRONMENT";

  }

  if (
    derivedPacket.marketPhase
    === "TRENDING"
  ) {

    aiSummary =
      "TRENDING_ENVIRONMENT";

  }

  if (
    derivedPacket.marketPhase
    === "CHAOTIC"
  ) {

    aiSummary =
      "CHAOTIC_MARKET_CONDITIONS";

  }

  if (
    derivedPacket.noTradeZone
  ) {

    aiSummary =
      "ENTRY_BLOCKED_BY_AI";

  }

  return {

    entryReasons,

    blockReasons,

    riskReasons,

    executionReasons,

    aiSummary,

  };

}