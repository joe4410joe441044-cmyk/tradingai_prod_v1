// =========================
// ENGINES
// =========================

import {
  adaptiveEngine
} from "../../engines/adaptiveEngine";

import {
  scoringEngine
} from "../../engines/scoringEngine";

import {
  governanceEngine
} from "../../engines/governanceEngine";

import {
  positionSizingEngine
} from "../../engines/positionSizingEngine";

import {
  lifecycleEngine
} from "../../engines/lifecycleEngine";

import {
  survivabilityEngine
} from "../../engines/survivabilityEngine";

// =========================
// AGGREGATION PIPELINE
// =========================

export const aggregationPipeline = ({

  marketPacket,

  strategyPacket,

  runtimePacket,

  riskPacket,

  spreadHistory,

  latencyHistory,

}) => {

  // =========================
  // BASE DERIVED PACKET
  // =========================

  const baseDerivedPacket = {

    restrictionActive:
      runtimePacket.latency > 150,

    marketHostility:
      strategyPacket.spread > 0.05
        ? "HIGH"
        : strategyPacket.spread > 0.02
          ? "MEDIUM"
          : "LOW",

    routingQuality:
      Math.max(
        0,
        100 - runtimePacket.latency
      ),

    marketStability:
      strategyPacket.spread > 0.05
        ? 20
        : strategyPacket.spread > 0.02
          ? 60
          : 90,

    hostileMarketCondition:
      strategyPacket.spread > 0.05 ||
      runtimePacket.latency > 120 ||
      riskPacket.restrictionActive,

    runtimeInstability:
      runtimePacket.latency > 120,

    spreadInstability:
      strategyPacket.spread > 0.05,

  };

  // =========================
  // ADAPTIVE ENGINE
  // =========================

  const adaptiveSyncPacket =
    adaptiveEngine({

      riskPacket,

      runtimePacket,

      spread:
        strategyPacket.spread,

      avgSpread:
        spreadHistory?.length
          ? (
              spreadHistory.reduce(
                (a, b) => a + b,
                0
              ) / spreadHistory.length
            )
          : 0,

    });

  // =========================
  // SCORING ENGINE
  // =========================

  const scoringSyncPacket =
    scoringEngine({

      runtimePacket,

      riskPacket,

      strategyPacket,

    });

  // =========================
  // GOVERNANCE ENGINE
  // =========================

  const governanceSyncPacket =
    governanceEngine({

      riskPacket,

      runtimePacket,

      routingScore:
        scoringSyncPacket.routingScore,

      marketScore:
        scoringSyncPacket.marketScore,

    });

  // =========================
  // POSITION SIZING ENGINE
  // =========================

  const positionSizingSyncPacket =
    positionSizingEngine({

      runtimePacket,

      riskPacket,

      spread:
        strategyPacket.spread,

    });

  // =========================
  // LIFECYCLE ENGINE
  // =========================

  const lifecycleSyncPacket =
    lifecycleEngine({

      marketData:
        marketPacket,

      runtimePacket,

      riskPacket,

      spread:
        strategyPacket.spread,

    });

  // =========================
  // SURVIVABILITY ENGINE
  // =========================

  const survivabilityState =

    survivabilityEngine({

      runtimeData:
        runtimePacket,

      spread:
        strategyPacket.spread,

      latency:
        runtimePacket.latency,

      riskData:
        riskPacket,

    });

  // =========================
  // DERIVED PACKET
  // =========================

  const derivedPacket = {

    ...baseDerivedPacket,

    avgSpread:
      spreadHistory?.length
        ? (
            spreadHistory.reduce(
              (a, b) => a + b,
              0
            ) / spreadHistory.length
          )
        : 0,

    avgLatency:
      latencyHistory?.length
        ? (
            latencyHistory.reduce(
              (a, b) => a + b,
              0
            ) / latencyHistory.length
          )
        : 0,

    runtimeEnvironment:
      runtimePacket.latency > 120
        ? "DEGRADED"
        : runtimePacket.latency > 60
          ? "NORMAL"
          : "OPTIMAL",

    marketCondition:
      strategyPacket.spread > 0.05
        ? "UNSTABLE"
        : strategyPacket.spread > 0.02
          ? "VOLATILE"
          : "STABLE",

    runtimePressure:
      runtimePacket.latency > 120
        ? "HIGH"
        : runtimePacket.latency > 60
          ? "MEDIUM"
          : "LOW",

    cognitionStability:
      runtimePacket.latency > 150
        ? "CRITICAL"
        : runtimePacket.latency > 100
          ? "DEGRADED"
          : "STABLE",

    ...adaptiveSyncPacket,

    ...scoringSyncPacket,

    ...governanceSyncPacket,

    ...positionSizingSyncPacket,

    ...lifecycleSyncPacket,

    ...survivabilityState,

  };

  return derivedPacket;

};

// =========================
// REALTIME LOG PACKET
// =========================

export function buildRealtimeLogPacket(

  parsed,
  config,
  helpers,

) {

  const {
    safeDate,
    safeNumber,
  } = helpers;

  const timestamp =
    safeDate(
      parsed.timestamp
    );

  const runtimeLog = {

    timestamp,

    runtimeState:
      parsed.runtimeState ||
      "IDLE",

    routerState:
      parsed.routerState ||
      "STANDBY",

    restrictionReason:
      parsed.restrictionReason ||
      "NONE",

    latency:
      safeNumber(
        parsed.latency
      ),

    spread:
      safeNumber(
        parsed.spread
      ),

    cognitionStability:
      parsed.cognitionStability ||
      "NORMAL",

  };

  const tradeLog = {

    timestamp,

    action:
      parsed.orderStatus ||
      "IDLE",

    symbol:
      parsed.symbol ||
      config.symbol ||
      "BTCUSDT",

    pnl:
      safeNumber(
        parsed.pnl
      ),

  };

  return {

    runtimeLog,
    tradeLog,

  };

}