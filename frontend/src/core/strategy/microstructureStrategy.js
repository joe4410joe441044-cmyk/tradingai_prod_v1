// ======================================================
// MICROSTRUCTURE EDGE STRATEGY
// XRP-focused Order Flow / Liquidity / Momentum Strategy
// ======================================================

export function microstructureStrategy({

  marketPacket,
  strategyPacket,
  executionPacket,
  intelligencePacket,
  derivedPacket,

}) {

  // ======================================================
  // SAFE VALUES
  // ======================================================

  const momentum =
    Number(
      strategyPacket?.momentum || 0
    );

  const spread =
    Number(
      strategyPacket?.spread || 0
    );

  const price =
    Number(
      marketPacket?.price || 0
    );

  const latency =
    Number(
      executionPacket?.latency || 0
    );

  const spoofProbability =
    Number(
      intelligencePacket?.spoofProbability || 0
    );

  const confidenceScore =
    Number(
      derivedPacket?.confidenceScore || 0
    );

  const liquidityStability =
    derivedPacket?.liquidityStability ||
    "UNKNOWN";

  const momentumRegime =
    derivedPacket?.momentumRegime ||
    "UNKNOWN";

  // ======================================================
  // ORDER FLOW
  // ======================================================

  const buyPressure =
    momentum > 0
      ? Math.abs(momentum) * 10
      : 0;

  const sellPressure =
    momentum < 0
      ? Math.abs(momentum) * 10
      : 0;

  const orderFlowDelta =
    buyPressure - sellPressure;

  const aggressiveBuyFlow =
    orderFlowDelta > 5;

  const aggressiveSellFlow =
    orderFlowDelta < -5;

  // ======================================================
  // TICK MOMENTUM
  // ======================================================

  let tickMomentumState =
    "NEUTRAL";

  if (
    momentumRegime === "BUILDING"
  ) {

    tickMomentumState =
      "ACCELERATING";

  }

  if (
    momentumRegime === "STRONG"
  ) {

    tickMomentumState =
      "TRENDING";

  }

  if (
    momentumRegime === "EXPLOSIVE"
  ) {

    tickMomentumState =
      "PARABOLIC";

  }

  // ======================================================
  // SPREAD / MARKET MAKING
  // ======================================================

  const tightSpread =
    spread < 0.01;

  const acceptableSpread =
    spread < 0.03;

  const spreadExpansion =
    spread > 0.05;

  const marketMakingWindow =
    tightSpread &&
    latency < 30;

  // ======================================================
  // LIQUIDITY GRAB
  // ======================================================

  const liquidityGrab =

    intelligencePacket?.liquidityGrab ||

    (
      spreadExpansion &&
      Math.abs(momentum) > 1
    );

  const fakeBreakout =

    liquidityGrab &&
    spoofProbability > 60;

  // ======================================================
  // SPOOF DETECTION
  // ======================================================

  const spoofDanger =
    spoofProbability > 70;

  const fakeWallDetected =
    intelligencePacket?.fakeWall ||
    false;

  // ======================================================
  // VOLATILITY / SIGMA
  // ======================================================

  let sigmaState =
    "NORMAL";

  if (
    spread > 0.05
  ) {

    sigmaState =
      "VOLATILE";

  }

  if (
    spread > 0.1
  ) {

    sigmaState =
      "EXTREME";

  }

  // ======================================================
  // DELTA PRESSURE
  // ======================================================

  let deltaPressure =
    "NEUTRAL";

  if (
    aggressiveBuyFlow
  ) {

    deltaPressure =
      "BUY_DOMINANT";

  }

  if (
    aggressiveSellFlow
  ) {

    deltaPressure =
      "SELL_DOMINANT";

  }

  // ======================================================
  // GAMMA ACCELERATION
  // ======================================================

  let gammaState =
    "STABLE";

  if (
    Math.abs(momentum) > 1 &&
    confidenceScore > 80
  ) {

    gammaState =
      "ACCELERATING";

  }

  if (
    Math.abs(momentum) > 2
  ) {

    gammaState =
      "EXPLODING";

  }

  // ======================================================
  // BREAKOUT ENGINE
  // ======================================================

  const breakoutLong =

    momentum > 0.8 &&
    confidenceScore > 75 &&
    acceptableSpread;

  const breakoutShort =

    momentum < -0.8 &&
    confidenceScore > 75 &&
    acceptableSpread;

  // ======================================================
  // LIQUIDITY ABSORPTION
  // ======================================================

  const liquidityAbsorption =

    tightSpread &&
    Math.abs(momentum) < 0.3 &&
    spoofProbability < 30;

  // ======================================================
  // MARKET ENVIRONMENT
  // ======================================================

  let marketEnvironment =
    "RANGING";

  if (
    breakoutLong ||
    breakoutShort
  ) {

    marketEnvironment =
      "BREAKOUT";

  }

  if (
    liquidityGrab
  ) {

    marketEnvironment =
      "LIQUIDITY_SWEEP";

  }

  if (
    spoofDanger
  ) {

    marketEnvironment =
      "MANIPULATED";

  }

  // ======================================================
  // DIRECTION
  // ======================================================

  let direction =
    "NONE";

  if (
    breakoutLong ||
    aggressiveBuyFlow
  ) {

    direction =
      "LONG";

  }

  if (
    breakoutShort ||
    aggressiveSellFlow
  ) {

    direction =
      "SHORT";

  }

  // ======================================================
  // EXECUTION FILTER
  // ======================================================

  const executionHealthy =
    latency < 80;

  const liquidityHealthy =
    liquidityStability ===
    "STABLE";

  const executionAllowed =

    executionHealthy &&
    liquidityHealthy &&
    !spoofDanger &&
    !fakeBreakout &&
    acceptableSpread;

  // ======================================================
  // SIGNAL ENGINE
  // ======================================================

  let signal =
    "WAIT";

  if (

    direction === "LONG" &&
    executionAllowed &&
    confidenceScore > 70

  ) {

    signal =
      "ENTER_LONG";

  }

  if (

    direction === "SHORT" &&
    executionAllowed &&
    confidenceScore > 70

  ) {

    signal =
      "ENTER_SHORT";

  }

  // ======================================================
  // EMERGENCY BLOCK
  // ======================================================

  const emergencyExit =

    spoofDanger ||
    spreadExpansion ||
    latency > 150;

  // ======================================================
  // EDGE SCORE
  // ======================================================

  let edgeScore = 0;

  edgeScore +=
    confidenceScore * 0.35;

  edgeScore +=
    Math.abs(momentum) * 20;

  edgeScore +=
    liquidityHealthy
      ? 15
      : 0;

  edgeScore +=
    tightSpread
      ? 15
      : 0;

  edgeScore -=
    spoofProbability * 0.4;

  edgeScore -=
    latency * 0.2;

  edgeScore =
    Math.max(
      0,
      Math.min(
        100,
        Math.round(edgeScore)
      )
    );

  // ======================================================
  // STRATEGY STATE
  // ======================================================

  let strategyState =
    "NEUTRAL";

  if (
    signal === "ENTER_LONG"
  ) {

    strategyState =
      "BULLISH_ATTACK";

  }

  if (
    signal === "ENTER_SHORT"
  ) {

    strategyState =
      "BEARISH_ATTACK";

  }

  if (
    marketEnvironment ===
    "MANIPULATED"
  ) {

    strategyState =
      "SURVIVAL";

  }

  // ======================================================
  // FINAL STRATEGY PACKET
  // ======================================================

  return {

    // signal

    signal,
    direction,
    strategyState,

    // execution

    executionAllowed,
    emergencyExit,

    // scores

    edgeScore,
    confidenceScore,

    // order flow

    buyPressure,
    sellPressure,
    orderFlowDelta,

    // regimes

    momentumRegime,
    liquidityStability,
    marketEnvironment,

    // sigma/delta/gamma

    sigmaState,
    deltaPressure,
    gammaState,

    // spread

    spread,
    tightSpread,
    spreadExpansion,

    // spoof

    spoofProbability,
    spoofDanger,
    fakeWallDetected,
    fakeBreakout,

    // liquidity

    liquidityGrab,
    liquidityAbsorption,

    // breakout

    breakoutLong,
    breakoutShort,

    // execution

    latency,
    marketMakingWindow,

    // misc

    price,
    momentum,

  };

}