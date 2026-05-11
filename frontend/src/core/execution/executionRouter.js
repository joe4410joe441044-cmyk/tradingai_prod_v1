export default function executionRouter({

  executionGate = {},

  derivedIntel = {},

  marketData = {},

  executionData = {},

  riskData = {},

}) {

  // =========================
  // EXECUTION GATE
  // =========================

  const {

    shouldExecute = false,

    executionBlocked = false,

    blockReason = "NONE",

    executionConfidence = 0,

    executionMode = "SURVIVAL",

    executionPriority = "LOW",

  } = executionGate;

  // =========================
  // DERIVED INTELLIGENCE
  // =========================

  const {

    signal = "WAIT",

    direction = "NONE",

    strategyState = "NEUTRAL",

    marketPhase = "RANGING",

    emergencyExit = false,

    noTradeZone = false,

  } = derivedIntel;

  // =========================
  // MARKET DATA
  // =========================

  const {

    price = 0,

    position = "NONE",

    entryPrice = 0,

    balance = 0,

  } = marketData;

  // =========================
  // EXECUTION DATA
  // =========================

  const {

    orderStatus = "IDLE",

    latency = 0,

  } = executionData;

  // =========================
  // RISK DATA
  // =========================

  const {

    riskLevel = "LOW",

    killSwitch = false,

  } = riskData;

  // =========================
  // DEFAULT ROUTE
  // =========================

  let action = "WAIT";

  let route = "NONE";

  let side = "NONE";

  let qty = 0;

  let reduceOnly = false;

  let closePosition = false;

  let routerReason = "IDLE";

  // =========================
  // EXECUTION BLOCK
  // =========================

  if (
    executionBlocked ||
    !shouldExecute
  ) {

    return {

      action: "BLOCK",

      route: "EXECUTION_BLOCKED",

      side: "NONE",

      qty: 0,

      reduceOnly: false,

      closePosition: false,

      executionConfidence,

      executionMode,

      executionPriority,

      blockReason,

      routerReason:
        "EXECUTION_GATE_BLOCKED",

      signal,

      direction,

      strategyState,

      marketPhase,

      latency,

      orderStatus,

      riskLevel,

    };

  }

  // =========================
  // EMERGENCY EXIT
  // =========================

  if (
    emergencyExit ||
    killSwitch
  ) {

    return {

      action: "EXIT",

      route: "EMERGENCY_EXIT",

      side: "CLOSE",

      qty: 100,

      reduceOnly: true,

      closePosition: true,

      executionConfidence,

      executionMode,

      executionPriority: "CRITICAL",

      blockReason: "EMERGENCY_EXIT",

      routerReason:
        "EMERGENCY_PROTECTION",

      signal,

      direction,

      strategyState,

      marketPhase,

      latency,

      orderStatus,

      riskLevel,

    };

  }

  // =========================
  // NO TRADE ZONE
  // =========================

  if (noTradeZone) {

    return {

      action: "WAIT",

      route: "NO_TRADE_ZONE",

      side: "NONE",

      qty: 0,

      reduceOnly: false,

      closePosition: false,

      executionConfidence,

      executionMode,

      executionPriority,

      blockReason: "NO_TRADE_ZONE",

      routerReason:
        "MARKET_UNSTABLE",

      signal,

      direction,

      strategyState,

      marketPhase,

      latency,

      orderStatus,

      riskLevel,

    };

  }

  // =========================
  // LONG ENTRY
  // =========================

  if (
    signal === "ENTER_LONG" &&
    direction === "BUY"
  ) {

    action = "ENTER_LONG";

    route = "LONG_ENTRY";

    side = "BUY";

    qty =

      executionConfidence >= 90
        ? 1.0

        : executionConfidence >= 75
        ? 0.75

        : executionConfidence >= 60
        ? 0.5

        : 0.25;

    routerReason =
      "LONG_SIGNAL_CONFIRMED";

  }

  // =========================
  // SHORT ENTRY
  // =========================

  if (
    signal === "ENTER_SHORT" &&
    direction === "SELL"
  ) {

    action = "ENTER_SHORT";

    route = "SHORT_ENTRY";

    side = "SELL";

    qty =

      executionConfidence >= 90
        ? 1.0

        : executionConfidence >= 75
        ? 0.75

        : executionConfidence >= 60
        ? 0.5

        : 0.25;

    routerReason =
      "SHORT_SIGNAL_CONFIRMED";

  }

  // =========================
  // EXIT CONDITIONS
  // =========================

  if (
    signal === "EXIT" ||
    strategyState === "SURVIVAL"
  ) {

    action = "EXIT";

    route = "POSITION_EXIT";

    side = "CLOSE";

    qty = 100;

    reduceOnly = true;

    closePosition = true;

    routerReason =
      "EXIT_SIGNAL_TRIGGERED";

  }

  // =========================
  // REDUCE CONDITIONS
  // =========================

  if (
    executionMode === "DEFENSIVE" &&
    position !== "NONE"
  ) {

    action = "REDUCE";

    route = "DEFENSIVE_REDUCTION";

    side =
      position === "BUY"
        ? "SELL"
        : "BUY";

    qty = 50;

    reduceOnly = true;

    routerReason =
      "DEFENSIVE_MODE_ACTIVE";

  }

  // =========================
  // FINAL ROUTE
  // =========================

  return {

    action,

    route,

    side,

    qty,

    reduceOnly,

    closePosition,

    executionConfidence,

    executionMode,

    executionPriority,

    routerReason,

    signal,

    direction,

    strategyState,

    marketPhase,

    price,

    entryPrice,

    balance,

    latency,

    orderStatus,

    riskLevel,

  };

}