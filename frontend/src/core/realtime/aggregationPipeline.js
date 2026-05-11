// =========================
// ENGINES
// =========================

import {
  aiCompositeDecisionEngine
} from "../../engines/aiCompositeDecisionEngine";

import {
  marketIntelligenceEngine
} from "../../engines/marketIntelligenceEngine";

import {
  adaptiveEngine
} from "../../engines/adaptiveEngine";

import {
  scoringEngine
} from "../../engines/scoringEngine";

import {
  permissionEngine
} from "../../engines/permissionEngine";

import {
  positionSizingEngine
} from "../../engines/positionSizingEngine";

import {
  lifecycleEngine
} from "../../engines/lifecycleEngine";

import {
  interpretationEngine
} from "../../engines/interpretationEngine";

import {
  executionSurvivabilityEngine
} from "../../engines/executionSurvivabilityEngine";

// =========================
// AGGREGATION PIPELINE
// =========================

export const aggregationPipeline = ({

  marketPacket,

  strategyPacket,

  executionPacket,

  riskPacket,

  intelligencePacket,

  momentumHistory,

  spreadHistory,

  latencyHistory,

}) => {

  // =========================
  // BASE DERIVED PACKET
  // =========================

  const baseDerivedPacket = {

    marketDanger:
      intelligencePacket.spoofProbability >= 80 ||
      intelligencePacket.spreadExplosion
        ? "HIGH"
        : intelligencePacket.spoofProbability >= 50
        ? "MEDIUM"
        : "LOW",

    entryQuality:
      Math.max(
        0,
        100 -
        intelligencePacket.spoofProbability +
        strategyPacket.edge * 10
      ),

    executionQuality:
      Math.max(
        0,
        100 - executionPacket.latency
      ),

    marketStability:
      intelligencePacket.spreadExplosion
        ? 20
        : 90,

    trendAggression:
      Math.abs(strategyPacket.delta) * 10,

    noTradeZone:
      intelligencePacket.spreadExplosion ||
      executionPacket.latency > 80 ||
      riskPacket.killSwitch,

    momentumBurst:
      Math.abs(strategyPacket.delta) > 5 &&
      strategyPacket.momentum > 3,

    executionAnomaly:
      executionPacket.latency > 120,

    unstableMarket:
      intelligencePacket.spreadExplosion ||
      intelligencePacket.spoofProbability > 70,

    spoofDanger:
      intelligencePacket.spoofProbability > 80,

  };

  // =========================
  // MARKET INTELLIGENCE
  // =========================

  const marketIntelSync =
    marketIntelligenceEngine({

      momentumHistory,

      spreadHistory,

      latencyHistory,

      strategyData:
        strategyPacket,

    });

  // =========================
  // ADAPTIVE ENGINE
  // =========================

  const adaptiveSyncPacket =
    adaptiveEngine({

      riskPacket,

      executionPacket,

      intelligencePacket,

      volatilityRegime:
        marketIntelSync.volatilityRegime,

      liquidityStability:
        marketIntelSync.liquidityStability,

      momentumRegime:
        marketIntelSync.momentumRegime,

      avgSpread:
        marketIntelSync.avgSpread,

    });

  // =========================
  // SCORING ENGINE
  // =========================

  const scoringSyncPacket =
    scoringEngine({

      executionPacket,

      intelligencePacket,

      riskPacket,

      strategyPacket,

      momentumAcceleration:
        marketIntelSync.momentumAcceleration,

      liquidityStability:
        marketIntelSync.liquidityStability,

      avgSpread:
        marketIntelSync.avgSpread,

    });

  // =========================
  // PERMISSION ENGINE
  // =========================

  const permissionSyncPacket =
    permissionEngine({

      riskPacket,

      executionPacket,

      intelligencePacket,

      liquidityStability:
        marketIntelSync.liquidityStability,

      aiCompositeScore:
        scoringSyncPacket.aiCompositeScore,

      executionScore:
        scoringSyncPacket.executionScore,

      marketSurvivabilityScore:
        scoringSyncPacket.marketSurvivabilityScore,

      liquidityScore:
        scoringSyncPacket.liquidityScore,

      trendQualityScore:
        scoringSyncPacket.trendQualityScore,

    });

  // =========================
  // POSITION SIZING ENGINE
  // =========================

  const positionSizingSyncPacket =
    positionSizingEngine({

      aiCompositeScore:
        scoringSyncPacket.aiCompositeScore,

      volatilityRegime:
        marketIntelSync.volatilityRegime,

      liquidityStability:
        marketIntelSync.liquidityStability,

      momentumRegime:
        marketIntelSync.momentumRegime,

      executionPacket,

      intelligencePacket,

      riskPacket,

    });

  // =========================
  // LIFECYCLE ENGINE
  // =========================

  const lifecycleSyncPacket =
    lifecycleEngine({

      marketData:
        marketPacket,

      aiCompositeScore:
        scoringSyncPacket.aiCompositeScore,

      aiTradeRejection:
        permissionSyncPacket.aiTradeRejection,

      executionPacket,

      intelligencePacket,

      riskPacket,

      volatilityRegime:
        marketIntelSync.volatilityRegime,

      momentumRegime:
        marketIntelSync.momentumRegime,

      liquidityStability:
        marketIntelSync.liquidityStability,

    });

  // =========================
  // INTERPRETATION ENGINE
  // =========================

  const interpretationSyncPacket =
    interpretationEngine({

      volatilityRegime:
        marketIntelSync.volatilityRegime,

      momentumRegime:
        marketIntelSync.momentumRegime,

      liquidityStability:
        marketIntelSync.liquidityStability,

      executionPacket,

      intelligencePacket,

      momentumAcceleration:
        marketIntelSync.momentumAcceleration,

      avgSpread:
        marketIntelSync.avgSpread,

    });

  // =========================
  // EXECUTION SURVIVABILITY
  // =========================

  const executionSurvival =

    executionSurvivabilityEngine({

      marketIntel:
        marketIntelSync,

      strategyIntel:
        strategyPacket,

      executionData:
        executionPacket,

      signalIntel:
        interpretationSyncPacket,

    });

  // =========================
  // AI COMPOSITE DECISION
  // =========================

  const aiCompositeDecision =

    aiCompositeDecisionEngine({

      marketIntel:
        marketIntelSync,

      scoringPacket:
        scoringSyncPacket,

      permissionPacket:
        permissionSyncPacket,

      interpretationPacket:
        interpretationSyncPacket,

      executionSurvival,

    });

  // =========================
  // DERIVED PACKET
  // =========================

  const derivedPacket = {

    ...baseDerivedPacket,

    volatilityRegime:
      marketIntelSync.volatilityRegime,

    momentumRegime:
      marketIntelSync.momentumRegime,

    liquidityStability:
      marketIntelSync.liquidityStability,

    marketPhase:
      marketIntelSync.marketPhase,

    spreadShock:
      marketIntelSync.spreadShock,

    liquidityCollapse:
      marketIntelSync.liquidityCollapse,

    executionSurvivability:
      marketIntelSync.executionSurvivability,

    adaptiveConfidence:
      marketIntelSync.adaptiveConfidence,

    executionPressure:
      marketIntelSync.executionPressure,

    marketRisk:
      marketIntelSync.marketRisk,

    executionEnvironment:
      marketIntelSync.executionEnvironment,

    marketTemperature:
      marketIntelSync.marketTemperature,

    trendStrength:
      marketIntelSync.trendStrength,

    ...interpretationSyncPacket,

    ...adaptiveSyncPacket,

    ...scoringSyncPacket,

    ...permissionSyncPacket,

    ...positionSizingSyncPacket,

    ...lifecycleSyncPacket,

    ...executionSurvival,

    ...aiCompositeDecision,

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

  const signalLog = {

    timestamp,

    signal:
      parsed.signal ||
      "NEUTRAL",

    confidence:
      safeNumber(
        parsed.confidenceScore
      ),

    momentum:
      safeNumber(
        parsed.momentum
      ),

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

    signalLog,
    tradeLog,

  };

}