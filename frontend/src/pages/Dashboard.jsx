import { useEffect, useState } from "react";
import "../styles/dashboard.css";

import StatusPanel from "../components/StatusPanel";
import StrategyMonitor from "../components/StrategyMonitor";
import SignalIntelligencePanel from "../components/SignalIntelligencePanel";
import DerivedIntelligencePanel from "../components/DerivedIntelligencePanel";

import ExecutionPanel from "../components/ExecutionPanel";
import LogsPanel from "../components/monitor/LogsPanel";

import TradeSettings from "../components/TradeSettings";
import StrategyControl from "../components/StrategyControl";
import RiskPanel from "../components/RiskPanel";

import ExecutionSettings from "../components/config/ExecutionSettings";
import PositionSettings from "../components/config/PositionSettings";
import EmergencySettings from "../components/config/EmergencySettings";
import AdvancedSettings from "../components/config/AdvancedSettings";

import ResultPanel from "../components/ResultPanel";

import {
  createRealtimeWebSocketLifecycle,
} from "../core/realtime/websocketLifecycle";

import realtimePipeline from "../core/realtime/realtimePipeline";

import {
  createTelemetryPipeline,
  updateTelemetryPipeline,
  createUnifiedTelemetryPacket,
} from "../core/telemetry/telemetryPipeline";

// =========================
// SAFE NUMBER
// =========================

const safeNumber = (
  value,
  fallback = null
) => {

  if (
    value === null ||
    value === undefined
  ) {

    return fallback;

  }

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : fallback;

};

// =========================
// SAFE DATE
// =========================

const safeDate = (
  value
) => {

  if (!value) {
    return null;
  }

  const d = new Date(value);

  return Number.isNaN(d.getTime())
    ? null
    : d.getTime();

};

const telemetryPipeline =
  createTelemetryPipeline();

createUnifiedTelemetryPacket();

// =========================
// DASHBOARD
// =========================

export default function Dashboard({

  config = {},
  setConfig = () => { },

  botData = {},

  handleStart = () => { },
  handleStop = () => { },

}) {

  // =========================
  // MARKET DATA
  // =========================

  const [marketData, setMarketData] = useState({

    timestamp: null,

    price: null,

    pnl: null,

    balance: null,

    equity: null,

    position: null,

    entryPrice: null,

    botStatus: null,

  });

  // =========================
  // STRATEGY DATA
  // =========================

  const [strategyData, setStrategyData] = useState({

    timestamp: null,

    imbalance: null,

    momentum: null,

    spread: null,

    edge: null,

    delta: null,

    cooldown: false,

    entryReady: false,

  });

  // =========================
  // EXECUTION DATA
  // =========================

  const [executionData, setExecutionData] = useState({

    timestamp: null,

    latency: null,

    orderStatus: null,

    wsStatus: null,

    engineStatus: null,

    executionMode: null,

  });

  // =========================
  // RISK DATA
  // =========================

  const [riskData, setRiskData] = useState({

    timestamp: null,

    currentDD: null,

    dailyLoss: null,

    lossStreak: null,

    riskLevel: null,

    killSwitch: false,

  });

  // =========================
  // SIGNAL INTELLIGENCE
  // =========================

  const [signalIntel, setSignalIntel] = useState({

    fakeWall: false,

    liquidityGrab: false,

    spoofProbability: null,

    absorption: false,

    spreadExplosion: false,

    confidenceScore: null,

  });

  // =========================
  // DERIVED INTELLIGENCE
  // =========================

  const [derivedIntel, setDerivedIntel] = useState({

    marketDanger: null,

    entryQuality: null,

    executionQuality: null,

    marketStability: null,

    trendAggression: null,

    noTradeZone: false,

    momentumBurst: false,

    executionAnomaly: false,

    unstableMarket: false,

    spoofDanger: false,

    confidenceScore: null,

    marketPhase: null,

    signalRank: null,

  });

  const [signalLogs, setSignalLogs] =
    useState([]);

  const [tradeLogs, setTradeLogs] =
    useState([]);

  const [frontendMetrics, setFrontendMetrics] = useState({

    wsReconnects: 0,

    staleEvents: 0,

    parseErrors: 0,

    packetsProcessed: 0,

    droppedPackets: 0,

  });

  const [momentumHistory, setMomentumHistory] =
    useState([]);

  const [spreadHistory, setSpreadHistory] =
    useState([]);

  const [latencyHistory, setLatencyHistory] =
    useState([]);

  const [executionRoute, setExecutionRoute] =
    useState(null);

  const [executionAllowed, setExecutionAllowed] =
    useState(false);

  const [routerReason, setRouterReason] =
    useState(null);

  const [executionPriority, setExecutionPriority] =
    useState(null);

  const [executionMode, setExecutionMode] =
    useState(null);

  const [survivabilityScore, setSurvivabilityScore] =
    useState(null);

  const [routerTelemetry, setRouterTelemetry] =
    useState({});

  const [unifiedTelemetry, setUnifiedTelemetry] =
    useState({});

  const [journalTelemetry, setJournalTelemetry] =
    useState({

      executionJournalSize: 0,

      lastJournalEntry: null,

      journalPersistenceStatus:
        null,

      journalRestoreStatus:
        null,

      crashRecoveryDetected:
        false,

    });

  useEffect(() => {

    const wsLifecycle =
      createRealtimeWebSocketLifecycle({

        url:
          `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`,

        debug: true,

        onOpen: () => {

          console.log(
            "WS LIFECYCLE READY"
          );

        },

        onReconnect: (attempts) => {

          console.log(
            "WS RECONNECT",
            attempts
          );
                setFrontendMetrics((prev) => ({

                  ...prev,

                  wsReconnects:
                    prev.wsReconnects + 1,

                }));

              },

                onStale: () => {

                  console.warn(
                    "WS STALE DETECTED"
                  );

                  setFrontendMetrics((prev) => ({

                    ...prev,

                    staleEvents:
                      prev.staleEvents + 1,

                  }));

                },

                  onError: (err) => {

                    console.error(
                      "WS ERROR:",
                      err
                    );

                  },

                    onMessage: (event) => {

                      realtimePipeline({

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

                      });

                      try {

                        const parsed =
                          JSON.parse(event.data);

                        const now = safeDate(
                          parsed.timestamp
                        );

                        setExecutionRoute(
                          parsed.executionRoute ??
                          null
                        );

                        setExecutionAllowed(
                          parsed.executionAllowed ??
                          false
                        );

                        setRouterReason(
                          parsed.routerReason ??
                          null
                        );

                        setExecutionPriority(
                          parsed.executionPriority ??
                          null
                        );

                        setExecutionMode(
                          parsed.executionMode ??
                          null
                        );

                        setSurvivabilityScore(
                          safeNumber(
                            parsed.survivabilityScore,
                            null
                          )
                        );

                        setRouterTelemetry(
                          parsed.routerTelemetry ??
                          {}
                        );

                        const telemetryPacket =
                          updateTelemetryPipeline({

                            executionTelemetry: {

                              executionRoute:
                                parsed.executionRoute,

                              executionAllowed:
                                parsed.executionAllowed,

                              routerReason:
                                parsed.routerReason,

                              executionPriority:
                                parsed.executionPriority,

                              executionMode:
                                parsed.executionMode,

                              survivabilityScore:
                                parsed.survivabilityScore,

                            },

                            runtimeTelemetry: {

                              websocketConnected:
                                executionData?.wsStatus === "CONNECTED",

                              lastUpdate:
                                now,

                            },

                            survivabilityTelemetry: {

                              survivabilityScore:
                                parsed.survivabilityScore,

                            },

                          });

                        setUnifiedTelemetry(
                          telemetryPacket
                        );

                        setJournalTelemetry({

                          executionJournalSize:
                            telemetryPacket
                              ?.executionJournalSize ?? 0,

                          lastJournalEntry:
                            telemetryPacket
                              ?.lastJournalEntry ?? null,

                          journalPersistenceStatus:
                            telemetryPacket
                              ?.journalPersistenceStatus ??
                            null,

                          journalRestoreStatus:
                            telemetryPacket
                              ?.journalRestoreStatus ??
                            null,

                          crashRecoveryDetected:
                            telemetryPacket
                              ?.crashRecoveryDetected ??
                            false,

                        });

                        setSignalLogs((prev) => ([

                          {

                            timestamp: now,

                            signal:
                              parsed.signal ??
                              null,

                            confidence:
                              safeNumber(
                                parsed.confidenceScore,
                                null
                              ),

                            momentum:
                              safeNumber(
                                parsed.momentum,
                                null
                              ),

                          },

                          ...prev,

                        ].slice(0, 50)));

                        setTradeLogs((prev) => ([

                          {

                            timestamp: now,

                            action:
                              parsed.orderStatus ??
                              null,

                            symbol:
                              parsed.symbol ??
                              config.symbol ??
                              null,

                            pnl:
                              safeNumber(
                                parsed.pnl,
                                null
                              ),

                            executionRoute:
                              parsed.executionRoute ??
                              null,

                            routerReason:
                              parsed.routerReason ??
                              null,

                            executionMode:
                              parsed.executionMode ??
                              null,

                            survivabilityScore:
                              safeNumber(
                                parsed.survivabilityScore,
                                null
                              ),

                          },

                          ...prev,

                        ].slice(0, 50)));

                      } catch (err) {

                        console.error(
                          "LOG PIPELINE ERROR:",
                          err
                        );

                      }

                    },

      });

    return () => {

      if (
        wsLifecycle &&
        wsLifecycle.destroy
      ) {

        wsLifecycle.destroy();

      }

    };

  }, []);

  const resultData = {

    positionSize:
      marketData?.balance !== null &&
        config.risk_percent !== null
        ? (
          safeNumber(
            marketData.balance,
            null
          ) *
          (
            safeNumber(
              config.risk_percent ?? null,
              null
            ) / 100
          )
        ).toFixed(2)
        : "-",

    qty:
      marketData?.price !== null &&
        marketData?.balance !== null &&
        config.risk_percent !== null
        ? (
          (
            safeNumber(
              marketData.balance,
              null
            ) *
            (
              safeNumber(
                config.risk_percent ?? null,
                null
              ) / 100
            )
          ) /
          safeNumber(
            marketData.price,
            null
          )
        ).toFixed(6)
        : "-",

    riskAmount:
      marketData?.balance !== null &&
        config.risk_percent !== null
        ? (
          safeNumber(
            marketData.balance,
            null
          ) *
          (
            safeNumber(
              config.risk_percent ?? null,
              null
            ) / 100
          )
        ).toFixed(2)
        : "-",

    ddAfter:
      config.sl_percent ?? null,

    symbol:
      config.symbol ?? null,

  };

  return (

    <div className="dashboard">

      <div className="header">

        <h1>
          TradingAI Dashboard
        </h1>

      </div>

      <div className="dashboard-content">

        <div className="panel-card full-dashboard-card">

          <div className="left-column">

            <StatusPanel

              balance={marketData?.balance}
              equity={marketData?.equity}
              pnl={marketData?.pnl}
              price={marketData?.price}

              position={marketData?.position}
              entryPrice={marketData?.entryPrice}

              botStatus={marketData?.botStatus}

              connection={
                executionData?.wsStatus
              }

              currentDD={
                riskData?.currentDD
              }

              lossStreak={
                riskData?.lossStreak
              }

              lastSignal={
                strategyData?.entryReady
                  ? "BUY"
                  : null
              }

              lastBlock={
                derivedIntel?.marketPhase ??
                null
              }

              engineState={
                executionData?.engineStatus
              }

              killSwitch={
                riskData?.killSwitch
                  ? "ACTIVE"
                  : "SAFE"
              }

              riskLevel={
                riskData?.riskLevel
              }

            />

            <StrategyMonitor
              strategyData={strategyData}
            />

            <SignalIntelligencePanel
              signalIntel={signalIntel}
            />

            <DerivedIntelligencePanel
              derivedIntel={derivedIntel}
            />

            <StrategyControl />

            <ResultPanel

              price={marketData?.price}
              balance={marketData?.balance}

              risk_percent={
                config.risk_percent
              }

              sl_percent={
                config.sl_percent
              }

              tp_percent={
                config.tp_percent
              }

              timeExit={
                config.time_exit ?? 3
              }

            />

          </div>

          <div className="center-column">

            <ExecutionPanel

              handleStart={handleStart}
              handleStop={handleStop}

              botData={{
                ...botData,
                ...marketData,
              }}

              executionData={{
                ...executionData,

                executionRoute,

                executionAllowed,

                routerReason,

                executionPriority,

                executionMode,

                survivabilityScore,

                routerTelemetry,

                unifiedTelemetry,

                journalTelemetry,

              }}

              aiData={{

                aiDecision:
                  derivedIntel?.signal,

                finalAction:
                  derivedIntel?.direction,

                executionProfile:
                  derivedIntel?.strategyState,

                aiConviction:
                  derivedIntel?.signalRank,

                survivalMode:
                  derivedIntel?.marketPhase,

                executionConfidence:
                  derivedIntel?.confidenceScore,

              }}

            />

            <LogsPanel

              signalLogs={signalLogs}
              tradeLogs={tradeLogs}

              routerTelemetry={
                routerTelemetry
              }

              executionRoute={
                executionRoute
              }

              routerReason={
                routerReason
              }

              unifiedTelemetry={
                unifiedTelemetry
              }

              journalTelemetry={
                journalTelemetry
              }

              loading={false}
              error={false}

            />

          </div>

          <div className="right-column">

            <TradeSettings

              config={config}
              setConfig={setConfig}

            />

            <ExecutionSettings

              config={config}
              setConfig={setConfig}

            />

            <PositionSettings

              config={config}
              setConfig={setConfig}

            />

            <RiskPanel
              result={resultData}
            />

            <EmergencySettings

              config={config}
              setConfig={setConfig}

            />

            <AdvancedSettings

              config={config}
              setConfig={setConfig}

            />

          </div>

        </div>

      </div>

    </div>

  );

}
