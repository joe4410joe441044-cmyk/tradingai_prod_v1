import {
  realtimePacketBuilder
} from "../websocket/realtimePacketBuilder";

import {
  aggregationPipeline
} from "./aggregationPipeline";

import {
  createReconnectRecovery
} from "./reconnectRecovery";

// =========================
// REALTIME MEMORY
// =========================

const HISTORY_LIMIT = 50;

const SIGNAL_MEMORY_LIMIT = 100;

const THROTTLE_MS = 25;

let realtimeMomentumHistory = [];

let realtimeSpreadHistory = [];

let realtimeLatencyHistory = [];

let signalMemory = [];

let lastPacketTimestamp = 0;

let lastProcessedTime = 0;

let lastPacketSignature = null;

let websocketHealthScore = 100;

let consecutiveLatencySpikes = 0;

let consecutiveSpreadShocks = 0;

let consecutiveSpoofDanger = 0;

let previousMarketPhase = "UNKNOWN";

const reconnectRecovery =
  createReconnectRecovery();

// =========================
// SAFE NUMBER
// =========================

const safeNumber = (
  value,
  fallback = 0
) => {

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : fallback;

};

// =========================
// AVERAGE
// =========================

const average = (
  arr = []
) => {

  if (!arr.length) {
    return 0;
  }

  return (
    arr.reduce(
      (a, b) => a + b,
      0
    ) / arr.length
  );

};

// =========================
// CLAMP
// =========================

const clamp = (
  value,
  min = 0,
  max = 100
) => {

  return Math.max(
    min,
    Math.min(max, value)
  );

};

// =========================
// PACKET SIGNATURE
// =========================

const createPacketSignature = (
  data
) => {

  return JSON.stringify({

    price:
      data?.price,

    momentum:
      data?.momentum,

    spread:
      data?.spread,

    timestamp:
      data?.timestamp,

  });

};

// =========================
// HEALTH SCORING
// =========================

const updateHealthScore = ({
  dropped = false,
  parseError = false,
  stale = false,
}) => {

  if (parseError) {
    websocketHealthScore -= 5;
  }

  if (stale) {
    websocketHealthScore -= 2;
  }

  if (dropped) {
    websocketHealthScore -= 1;
  }

  websocketHealthScore =
    clamp(
      websocketHealthScore,
      0,
      100
    );

};

// =========================
// MOMENTUM REGIME
// =========================

const getMomentumRegime = (
  momentum
) => {

  const absMomentum =
    Math.abs(momentum);

  if (absMomentum < 0.2) {
    return "WEAK";
  }

  if (absMomentum < 0.5) {
    return "BUILDING";
  }

  if (absMomentum < 1.2) {
    return "STRONG";
  }

  return "EXPLOSIVE";

};

// =========================
// LIQUIDITY STABILITY
// =========================

const getLiquidityStability = (
  spread
) => {

  if (spread < 0.01) {
    return "STABLE";
  }

  if (spread < 0.03) {
    return "WEAK";
  }

  return "COLLAPSING";

};

// =========================
// SPREAD REGIME
// =========================

const getSpreadRegime = (
  spread
) => {

  if (spread < 0.005) {
    return "TIGHT";
  }

  if (spread < 0.02) {
    return "NORMAL";
  }

  if (spread < 0.05) {
    return "WIDE";
  }

  return "DANGER";

};

// =========================
// EXECUTION QUALITY
// =========================

const getExecutionQuality = (
  latency
) => {

  if (latency < 20) {
    return "EXCELLENT";
  }

  if (latency < 50) {
    return "GOOD";
  }

  if (latency < 120) {
    return "DEGRADED";
  }

  return "CRITICAL";

};

// =========================
// VOLATILITY REGIME
// =========================

const getVolatilityRegime = (
  spread
) => {

  if (spread < 0.005) {
    return "CALM";
  }

  if (spread < 0.02) {
    return "NORMAL";
  }

  if (spread < 0.05) {
    return "VOLATILE";
  }

  return "EXTREME";

};

// =========================
// TREND AGGRESSION
// =========================

const getTrendAggression = (
  momentum
) => {

  const absMomentum =
    Math.abs(momentum);

  if (absMomentum < 0.2) {
    return "PASSIVE";
  }

  if (absMomentum < 0.5) {
    return "ACTIVE";
  }

  if (absMomentum < 1.2) {
    return "AGGRESSIVE";
  }

  return "EXTREME";

};

// =========================
// MARKET PHASE
// =========================

const getMarketPhase = ({
  momentumRegime,
  spreadRegime,
  spoofDanger,
  liquidityCollapse,
  volatilityRegime,
}) => {

  if (
    spoofDanger ||
    liquidityCollapse
  ) {
    return "CHAOTIC";
  }

  if (
    momentumRegime === "EXPLOSIVE" &&
    volatilityRegime === "EXTREME"
  ) {
    return "BREAKOUT";
  }

  if (
    momentumRegime === "STRONG"
  ) {
    return "TRENDING";
  }

  if (
    momentumRegime === "WEAK"
  ) {
    return "RANGING";
  }

  if (
    spreadRegime === "DANGER"
  ) {
    return "EXHAUSTION";
  }

  return "RANGING";

};

// =========================
// ENTRY TIMING
// =========================

const getEntryTiming = ({
  momentumRegime,
  marketPhase,
  confidenceScore,
}) => {

  if (
    marketPhase === "CHAOTIC"
  ) {
    return "AVOID";
  }

  if (
    momentumRegime === "BUILDING" &&
    confidenceScore > 70
  ) {
    return "EARLY";
  }

  if (
    momentumRegime === "STRONG" &&
    confidenceScore > 80
  ) {
    return "CONFIRMED";
  }

  if (
    momentumRegime === "EXPLOSIVE"
  ) {
    return "LATE";
  }

  return "AVOID";

};

// =========================
// SIGNAL RANK
// =========================

const getSignalRank = (
  confidenceScore
) => {

  if (confidenceScore >= 95) {
    return "A+";
  }

  if (confidenceScore >= 85) {
    return "A";
  }

  if (confidenceScore >= 70) {
    return "B";
  }

  if (confidenceScore >= 50) {
    return "C";
  }

  if (confidenceScore >= 30) {
    return "D";
  }

  return "AVOID";

};

// =========================
// RISK BIAS
// =========================

const getRiskBias = ({
  marketDanger,
  confidenceScore,
  volatilityRegime,
}) => {

  if (
    marketDanger === "HIGH"
  ) {
    return "SURVIVAL";
  }

  if (
    volatilityRegime === "EXTREME"
  ) {
    return "DEFENSIVE";
  }

  if (
    confidenceScore > 85
  ) {
    return "OFFENSIVE";
  }

  return "NEUTRAL";

};

// =========================
// DYNAMIC ENTRY AGGRESSION
// =========================

const getEntryAggression = ({
  confidenceScore,
  marketDanger,
  volatilityRegime,
}) => {

  if (
    marketDanger === "HIGH"
  ) {
    return "BLOCKED";
  }

  if (
    volatilityRegime === "EXTREME"
  ) {
    return "SCALP_ONLY";
  }

  if (
    confidenceScore > 90
  ) {
    return "MAX_OFFENSIVE";
  }

  if (
    confidenceScore > 75
  ) {
    return "AGGRESSIVE";
  }

  return "NORMAL";

};

// =========================
// SPOOF RISK
// =========================

const calculateSpoofRisk = ({
  fakeWall,
  spoofProbability,
  spreadExplosion,
  liquidityGrab,
}) => {

  let risk = 0;

  if (fakeWall) {
    risk += 30;
  }

  risk += spoofProbability * 50;

  if (spreadExplosion) {
    risk += 10;
  }

  if (liquidityGrab) {
    risk += 10;
  }

  return clamp(
    Math.round(risk),
    0,
    100
  );

};

// =========================
// ENTRY QUALITY
// =========================

const calculateEntryQuality = ({
  momentum,
  spread,
  latency,
  spoofRisk,
  marketDanger,
}) => {

  let score = 100;

  score -= spread * 1000;

  score -= latency * 0.3;

  score -= spoofRisk * 0.5;

  score += Math.abs(momentum) * 15;

  if (marketDanger === "HIGH") {
    score -= 40;
  }

  return clamp(
    Math.round(score),
    0,
    100
  );

};

// =========================
// EXECUTION SCORE
// =========================

const calculateExecutionScore = ({
  websocketHealth,
  latency,
  droppedPackets,
}) => {

  let score = websocketHealth;

  score -= latency * 0.4;

  score -= droppedPackets * 2;

  return clamp(
    Math.round(score),
    0,
    100
  );

};

// =========================
// MARKET STABILITY
// =========================

const calculateMarketStability = ({
  spread,
  latency,
  spoofRisk,
}) => {

  let score = 100;

  score -= spread * 1200;

  score -= latency * 0.2;

  score -= spoofRisk * 0.5;

  return clamp(
    Math.round(score),
    0,
    100
  );

};

// =========================
// EXPLAINABLE ATTRIBUTION INTELLIGENCE
// =========================

const calculateAttributionIntel = ({
  momentum,
  spread,
  latency,
  spoofRisk,
  confidenceScore,
}) => {

  const momentumContribution =
    clamp(
      Math.abs(momentum) * 35,
      0,
      100
    );

  const liquidityContribution =
    clamp(
      100 - (spread * 2500),
      0,
      100
    );

  const executionContribution =
    clamp(
      100 - (latency * 0.8),
      0,
      100
    );

  const spoofPenalty =
    clamp(spoofRisk, 0, 100);

  const volatilityPenalty =
    spread > 0.05
      ? 80
      : spread > 0.02
        ? 40
        : 10;

  const totalScore =
    clamp(
      Math.round(
        (
          momentumContribution * 0.3 +
          liquidityContribution * 0.25 +
          executionContribution * 0.2 +
          confidenceScore * 0.25
        ) -
        (
          spoofPenalty * 0.35 +
          volatilityPenalty * 0.15
        )
      ),
      0,
      100
    );

  const strongestBullishFactor =
    momentumContribution >= liquidityContribution &&
      momentumContribution >= executionContribution
      ? "momentumContribution"
      : liquidityContribution >= executionContribution
        ? "liquidityContribution"
        : "executionContribution";

  const strongestBearishFactor =
    spoofPenalty >= volatilityPenalty
      ? "spoofPenalty"
      : "volatilityPenalty";

  let confidenceEnvironment = "LOW";

  if (totalScore >= 85) {
    confidenceEnvironment = "EXTREME";
  } else if (totalScore >= 70) {
    confidenceEnvironment = "HIGH";
  } else if (totalScore >= 45) {
    confidenceEnvironment = "MEDIUM";
  }

  return {
    momentumContribution,
    liquidityContribution,
    executionContribution,
    spoofPenalty,
    volatilityPenalty,
    totalScore,
    strongestBullishFactor,
    strongestBearishFactor,
    confidenceEnvironment,
  };

};

// =========================
// REALTIME PIPELINE
// =========================

export default function realtimePipeline({

  event,

  setMarketData,
  setStrategyData,
  setExecutionData,
  setRiskData,

  setSignalIntel,
  setDerivedIntel,

  setMomentumHistory,
  setSpreadHistory,
  setLatencyHistory,

  setFrontendMetrics,

}) {

  try {

    if (!event?.data) {
      return;
    }

    const now = Date.now();

    if (
      now - lastProcessedTime <
      THROTTLE_MS
    ) {

      return;

    }

    lastProcessedTime = now;

    const data =
      JSON.parse(event.data);

    const packetTimestamp =
      Number(
        data.timestamp ||
        data.ts ||
        Date.now()
      );

    if (
      packetTimestamp <=
      lastPacketTimestamp
    ) {

      updateHealthScore({
        stale: true,
        dropped: true,
      });

      return;

    }

    lastPacketTimestamp =
      packetTimestamp;

    const packetSignature =
      createPacketSignature(
        data
      );

    if (
      packetSignature ===
      lastPacketSignature
    ) {

      updateHealthScore({
        dropped: true,
      });

      return;

    }

    lastPacketSignature =
      packetSignature;

    reconnectRecovery
      .updateRealtimePacketTimestamp();

    const {

      marketPacket,

      strategyPacket,

      executionPacket,

      riskPacket,

      intelligencePacket,

    } = realtimePacketBuilder(data);

    strategyPacket.momentum =
      safeNumber(
        strategyPacket.momentum
      );

    strategyPacket.spread =
      safeNumber(
        strategyPacket.spread
      );

    executionPacket.latency =
      safeNumber(
        executionPacket.latency
      );

    realtimeMomentumHistory = [

      strategyPacket.momentum,

      ...realtimeMomentumHistory,

    ].slice(0, HISTORY_LIMIT);

    realtimeSpreadHistory = [

      strategyPacket.spread,

      ...realtimeSpreadHistory,

    ].slice(0, HISTORY_LIMIT);

    realtimeLatencyHistory = [

      executionPacket.latency,

      ...realtimeLatencyHistory,

    ].slice(0, HISTORY_LIMIT);

    const derivedPacket =
      aggregationPipeline({

        marketPacket,

        strategyPacket,

        executionPacket,

        riskPacket,

        intelligencePacket,

        momentumHistory:
          realtimeMomentumHistory,

        spreadHistory:
          realtimeSpreadHistory,

        latencyHistory:
          realtimeLatencyHistory,

      });

    const staleCheck =
      reconnectRecovery
        .detectStaleRealtimeFeed();

    const disconnectCheck =
      reconnectRecovery
        .detectStreamDisconnect({
          websocketConnected:
            executionPacket.wsStatus ===
            "CONNECTED",
        });

    const reconnectTelemetry =
      reconnectRecovery
        .createReconnectTelemetryPacket();

    const avgMomentum =
      average(
        realtimeMomentumHistory
      );

    const avgSpread =
      average(
        realtimeSpreadHistory
      );

    const avgLatency =
      average(
        realtimeLatencyHistory
      );

    derivedPacket.avgMomentum = avgMomentum;
    derivedPacket.avgSpread = avgSpread;
    derivedPacket.avgLatency = avgLatency;

    derivedPacket.momentumRegime =
      getMomentumRegime(
        strategyPacket.momentum
      );

    derivedPacket.liquidityStability =
      getLiquidityStability(
        strategyPacket.spread
      );

    derivedPacket.spreadRegime =
      getSpreadRegime(
        strategyPacket.spread
      );

    derivedPacket.volatilityRegime =
      getVolatilityRegime(
        strategyPacket.spread
      );

    derivedPacket.trendAggression =
      getTrendAggression(
        strategyPacket.momentum
      );

    derivedPacket.spoofRisk =
      calculateSpoofRisk({

        fakeWall:
          intelligencePacket.fakeWall,

        spoofProbability:
          intelligencePacket.spoofProbability,

        spreadExplosion:
          intelligencePacket.spreadExplosion,

        liquidityGrab:
          intelligencePacket.liquidityGrab,

      });

    derivedPacket.spoofDanger =
      derivedPacket.spoofRisk > 70;

    derivedPacket.marketDanger =
      derivedPacket.spoofDanger
        ? "HIGH"
        : "LOW";

    derivedPacket.entryQuality =
      calculateEntryQuality({

        momentum:
          strategyPacket.momentum,

        spread:
          strategyPacket.spread,

        latency:
          executionPacket.latency,

        spoofRisk:
          derivedPacket.spoofRisk,

        marketDanger:
          derivedPacket.marketDanger,

      });

    derivedPacket.executionQuality =
      calculateExecutionScore({

        websocketHealth:
          websocketHealthScore,

        latency:
          executionPacket.latency,

        droppedPackets: 0,

      });

    derivedPacket.marketStability =
      calculateMarketStability({

        spread:
          strategyPacket.spread,

        latency:
          executionPacket.latency,

        spoofRisk:
          derivedPacket.spoofRisk,

      });

    derivedPacket.confidenceScore =
      clamp(
        Math.round(
          (
            derivedPacket.entryQuality +
            derivedPacket.executionQuality +
            derivedPacket.marketStability
          ) / 3
        ),
        0,
        100
      );

    derivedPacket.marketPhase =
      getMarketPhase({

        momentumRegime:
          derivedPacket.momentumRegime,

        spreadRegime:
          derivedPacket.spreadRegime,

        spoofDanger:
          derivedPacket.spoofDanger,

        liquidityCollapse:
          derivedPacket.liquidityStability === "COLLAPSING",

        volatilityRegime:
          derivedPacket.volatilityRegime,

      });

    derivedPacket.entryTiming =
      getEntryTiming({

        momentumRegime:
          derivedPacket.momentumRegime,

        marketPhase:
          derivedPacket.marketPhase,

        confidenceScore:
          derivedPacket.confidenceScore,

      });

    derivedPacket.signalRank =
      getSignalRank(
        derivedPacket.confidenceScore
      );

    derivedPacket.riskBias =
      getRiskBias({

        marketDanger:
          derivedPacket.marketDanger,

        confidenceScore:
          derivedPacket.confidenceScore,

        volatilityRegime:
          derivedPacket.volatilityRegime,

      });

    signalMemory = [

      {

        timestamp: now,

        confidenceScore:
          derivedPacket.confidenceScore,

        marketPhase:
          derivedPacket.marketPhase,

        spoofRisk:
          derivedPacket.spoofRisk,

        latency:
          executionPacket.latency,

      },

      ...signalMemory,

    ].slice(0, SIGNAL_MEMORY_LIMIT);

    if (
      derivedPacket.latencySpike
    ) {
      consecutiveLatencySpikes += 1;
    } else {
      consecutiveLatencySpikes = 0;
    }

    if (
      derivedPacket.spreadShock
    ) {
      consecutiveSpreadShocks += 1;
    } else {
      consecutiveSpreadShocks = 0;
    }

    if (
      derivedPacket.spoofDanger
    ) {
      consecutiveSpoofDanger += 1;
    } else {
      consecutiveSpoofDanger = 0;
    }

    derivedPacket.regimeTransition =
      previousMarketPhase !==
      derivedPacket.marketPhase;

    derivedPacket.trendContinuation =
      previousMarketPhase ===
      "TRENDING" &&
      derivedPacket.marketPhase ===
      "TRENDING";

    derivedPacket.trendWeakening =
      previousMarketPhase ===
      "TRENDING" &&
      derivedPacket.marketPhase !==
      "TRENDING";

    previousMarketPhase =
      derivedPacket.marketPhase;

    derivedPacket.confidenceDecay =
      clamp(
        derivedPacket.confidenceScore -
        signalMemory.length * 0.1,
        0,
        100
      );

    derivedPacket.entryAggression =
      getEntryAggression({

        confidenceScore:
          derivedPacket.confidenceScore,

        marketDanger:
          derivedPacket.marketDanger,

        volatilityRegime:
          derivedPacket.volatilityRegime,

      });

    derivedPacket.aiStabilityConfidence =
      clamp(
        100 - (
          consecutiveLatencySpikes * 5 +
          consecutiveSpreadShocks * 4 +
          consecutiveSpoofDanger * 6
        ),
        0,
        100
      );

    derivedPacket.streamDisconnected =
      disconnectCheck.disconnected;

    derivedPacket.streamStale =
      staleCheck.stale;

    derivedPacket.reconnectTriggered =
      reconnectTelemetry
        .reconnectTriggered;

    derivedPacket.reconnectInProgress =
      reconnectTelemetry
        .reconnectInProgress;

    derivedPacket.reconnectCount =
      reconnectTelemetry
        .reconnectCount;

    derivedPacket.reconnectFailures =
      reconnectTelemetry
        .reconnectFailures;

    derivedPacket.lastReconnectAt =
      reconnectTelemetry
        .lastReconnectAt;

    derivedPacket.lastReconnectReason =
      reconnectTelemetry
        .lastReconnectReason;

    derivedPacket.reconnectLatency =
      reconnectTelemetry
        .reconnectLatency;

    derivedPacket.reconnectRecovered =
      reconnectTelemetry
        .reconnectRecovered;

    if (
      derivedPacket.streamDisconnected ||
      derivedPacket.streamStale ||
      derivedPacket.reconnectInProgress
    ) {

      derivedPacket.executionAllowed =
        false;

    }

    Object.assign(
      derivedPacket,
      calculateAttributionIntel({
        momentum:
          strategyPacket.momentum,
        spread:
          strategyPacket.spread,
        latency:
          executionPacket.latency,
        spoofRisk:
          derivedPacket.spoofRisk,
        confidenceScore:
          derivedPacket.confidenceScore,
      })
    );

    setMarketData((prev) => ({

      ...prev,

      ...marketPacket,

      price:
        marketPacket.price ??
        prev.price,

      balance:
        marketPacket.balance ??
        prev.balance,

      equity:
        marketPacket.equity ??
        prev.equity,

      pnl:
        marketPacket.pnl ??
        prev.pnl,

      position:
        marketPacket.position ??
        prev.position,

      entryPrice:
        marketPacket.entryPrice ??
        prev.entryPrice,

      timestamp:
        marketPacket.timestamp ??
        prev.timestamp,

    }));

    setStrategyData(
      strategyPacket
    );

    setExecutionData(
      executionPacket
    );

    setRiskData(
      riskPacket
    );

    setSignalIntel(
      intelligencePacket
    );

    setMomentumHistory(
      realtimeMomentumHistory
    );

    setSpreadHistory(
      realtimeSpreadHistory
    );

    setLatencyHistory(
      realtimeLatencyHistory
    );

    setDerivedIntel(
      derivedPacket
    );

    setFrontendMetrics((prev) => ({

      ...prev,

      packetsProcessed:
        prev.packetsProcessed + 1,

    }));


  } catch (err) {

    console.error(
      "REALTIME PIPELINE ERROR:",
      err
    );

    updateHealthScore({
      parseError: true,
    });

    setFrontendMetrics((prev) => ({

      ...prev,

      parseErrors:
        prev.parseErrors + 1,

    }));

  }

}
