import {
  realtimePacketBuilder
} from "../websocket/realtimePacketBuilder";

import {
  aggregationPipeline
} from "./aggregationPipeline";

import {
  createReconnectRecovery
} from "./reconnectRecovery";

// =====================================================
// COGNITION RUNTIME MEMORY
// =====================================================

const HISTORY_LIMIT = 50;

const THROTTLE_MS = 25;

let realtimeSpreadHistory = [];

let realtimeLatencyHistory = [];

let lastPacketTimestamp = 0;

let lastProcessedTime = 0;

let lastPacketSignature = null;

let websocketHealthScore = 100;

const reconnectRecovery =
  createReconnectRecovery();

// =====================================================
// SAFE NUMBER
// =====================================================

const safeNumber = (
  value,
  fallback = 0
) => {

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : fallback;

};

// =====================================================
// AVERAGE
// =====================================================

// =====================================================
// CLAMP
// =====================================================

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

// =====================================================
// PACKET SIGNATURE
// =====================================================

const createPacketSignature = (
  data
) => {

  return JSON.stringify({

    price:
      data?.price,

    spread:
      data?.spread,

    timestamp:
      data?.timestamp,

  });

};

// =====================================================
// WEBSOCKET HEALTH
// =====================================================

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

// =====================================================
// MARKET REGIME
// =====================================================

const getMarketRegime = (
  spread
) => {

  if (spread < 0.005) {
    return "STABLE";
  }

  if (spread < 0.02) {
    return "NORMAL";
  }

  if (spread < 0.05) {
    return "VOLATILE";
  }

  return "HOSTILE";

};

// =====================================================
// ROUTING QUALITY
// =====================================================

const getRoutingQuality = (
  latency
) => {

  if (latency < 20) {
    return "HIGH";
  }

  if (latency < 50) {
    return "MEDIUM";
  }

  if (latency < 120) {
    return "LOW";
  }

  return "DEGRADED";

};

// =====================================================
// SURVIVABILITY
// =====================================================

const calculateSurvivability = ({
  websocketHealth,
  latency,
  spread,
}) => {

  let score = websocketHealth;

  score -= latency * 0.35;

  score -= spread * 1200;

  return clamp(
    Math.round(score),
    0,
    100
  ) / 100;

};

// =====================================================
// MARKET HOSTILITY
// =====================================================

const calculateMarketHostility = ({
  spread,
  latency,
}) => {

  let hostility = 0;

  hostility += spread * 15;

  hostility += latency * 0.002;

  return Math.min(
    hostility,
    1
  );

};

// =====================================================
// COGNITION STABILITY
// =====================================================

const calculateCognitionStability = ({
  websocketHealth,
  latency,
}) => {

  let score =
    websocketHealth -
    latency * 0.3;

  return clamp(
    score,
    0,
    100
  ) / 100;

};

// =====================================================
// ROUTER BELIEF
// =====================================================

const synthesizeBelief = ({
  survivability,
  marketHostility,
  tickMomentum,
}) => {

  if (
    survivability < 0.4
  ) {

    return "DEFENSIVE";

  }

  if (
    marketHostility > 0.7
  ) {

    return "HOSTILE";

  }

  if (
    tickMomentum === "UP"
  ) {

    return "BULLISH";

  }

  if (
    tickMomentum === "DOWN"
  ) {

    return "BEARISH";

  }

  return "NEUTRAL";

};

// =====================================================
// REALTIME PIPELINE
// =====================================================

export default function realtimePipeline({

  event,

  setMarketData,
  setStrategyData,
  setExecutionData,
  setRiskData,

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

    } = realtimePacketBuilder(data);

    strategyPacket.spread =
      safeNumber(
        strategyPacket.spread
      );

    executionPacket.latency =
      safeNumber(
        executionPacket.latency
      );

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


    // =====================================================
    // MARKET REGIME
    // =====================================================

    const marketRegime =
      getMarketRegime(
        strategyPacket.spread
      );

    // =====================================================
    // ROUTING QUALITY
    // =====================================================

    const routingQuality =
      getRoutingQuality(
        executionPacket.latency
      );

    // =====================================================
    // SURVIVABILITY
    // =====================================================

    const survivability =
      calculateSurvivability({

        websocketHealth:
          websocketHealthScore,

        latency:
          executionPacket.latency,

        spread:
          strategyPacket.spread,

      });

    // =====================================================
    // MARKET HOSTILITY
    // =====================================================

    const marketHostility =
      calculateMarketHostility({

        spread:
          strategyPacket.spread,

        latency:
          executionPacket.latency,

      });

    // =====================================================
    // COGNITION STABILITY
    // =====================================================

    const cognitionStability =
      calculateCognitionStability({

        websocketHealth:
          websocketHealthScore,

        latency:
          executionPacket.latency,

      });

    // =====================================================
    // MICROSTRUCTURE
    // =====================================================

    const microstructureSignals = {

      imbalance:
        derivedPacket.imbalance ?? 0,

      spreadQuality:
        marketRegime,

      liquidityShift:
        derivedPacket.liquidityShift ??
        "STABLE",

      tickMomentum:
        derivedPacket.tickMomentum ??
        "NEUTRAL",

      volatilityPressure:
        marketHostility,

      orderFlowBias:
        derivedPacket.orderFlowBias ??
        "NEUTRAL",

    };

    // =====================================================
    // ROUTER BELIEF
    // =====================================================

    const belief =
      synthesizeBelief({

        survivability,

        marketHostility,

        tickMomentum:
          microstructureSignals
            .tickMomentum,

      });

    // =====================================================
    // RESTRICTION SYNTHESIS
    // =====================================================

    let restrictionReason =
      "NONE";

    if (
      staleCheck.stale
    ) {

      restrictionReason =
        "STALE_STREAM";

    }

    if (
      disconnectCheck.disconnected
    ) {

      restrictionReason =
        "STREAM_DISCONNECTED";

    }

    if (
      marketHostility > 0.8
    ) {

      restrictionReason =
        "HOSTILE_MARKET";

    }

    // =====================================================
    // COGNITION TELEMETRY
    // =====================================================

    derivedPacket.cognition = {

      belief,

      confidence:
        survivability,

      survivability,

      routingQuality,

      cognitionStability,

      restrictionReason,

    };

    // =====================================================
    // ROUTER TELEMETRY
    // =====================================================

    derivedPacket.router = {

      status:

        survivability < 0.4
          ? "SURVIVAL"

          : cognitionStability < 0.5
          ? "UNSTABLE"

          : marketHostility > 0.7
          ? "VOLATILE"

          : "STABLE",

      routingQuality,

      lastRouteUpdate:
        Date.now(),

    };

    // =====================================================
    // MARKET TELEMETRY
    // =====================================================

    derivedPacket.market = {

      marketRegime,

      marketHostility,

      microstructureSignals,

    };

    // =====================================================
    // RECONNECT TELEMETRY
    // =====================================================

    derivedPacket.runtime = {

      websocketHealth:
        websocketHealthScore,

      streamDisconnected:
        disconnectCheck.disconnected,

      streamStale:
        staleCheck.stale,

      reconnectTriggered:
        reconnectTelemetry
          .reconnectTriggered,

      reconnectInProgress:
        reconnectTelemetry
          .reconnectInProgress,

      reconnectCount:
        reconnectTelemetry
          .reconnectCount,

      reconnectFailures:
        reconnectTelemetry
          .reconnectFailures,

      lastReconnectAt:
        reconnectTelemetry
          .lastReconnectAt,

      lastReconnectReason:
        reconnectTelemetry
          .lastReconnectReason,

      reconnectLatency:
        reconnectTelemetry
          .reconnectLatency,

      reconnectRecovered:
        reconnectTelemetry
          .reconnectRecovered,

    };

    // =====================================================
    // MARKET DATA
    // =====================================================

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

    // =====================================================
    // STRATEGY DATA
    // =====================================================

    setStrategyData({
      ...strategyPacket,
      cognition:
        derivedPacket.cognition,
    });

    // =====================================================
    // EXECUTION DATA
    // =====================================================

    setExecutionData({

      ...executionPacket,

      router:
        derivedPacket.router,

      market:
        derivedPacket.market,

      runtime:
        derivedPacket.runtime,

      cognition:
        derivedPacket.cognition,

    });

    // =====================================================
    // RISK DATA
    // =====================================================

    setRiskData({

      ...riskPacket,

      survivability,

      restrictionReason,

    });

    setMomentumHistory([]);

    setSpreadHistory(
      realtimeSpreadHistory
    );

    setLatencyHistory(
      realtimeLatencyHistory
    );

    // =====================================================
    // FRONTEND METRICS
    // =====================================================

    setFrontendMetrics((prev) => ({

      ...prev,

      packetsProcessed:
        prev.packetsProcessed + 1,

      websocketHealth:
        websocketHealthScore,

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

      websocketHealth:
        websocketHealthScore,

    }));

  }

}