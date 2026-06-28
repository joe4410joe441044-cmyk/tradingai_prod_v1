import {
    useEffect,
    useState,
} from "react";

import {
    startWebSocketRuntime,
} from "../runtime/websocketRuntime";
import LogsPanel from "../components/monitor/LogsPanel";

import FilterSettings from "../components/FilterSettings";
import SafetySettings from "../components/SafetySettings";
import QuickActions from "../components/QuickActions";

import {
    mapLatencyQuality,
    mapExecutionHealth,
    mapSpreadSafety,
} from "../utils/telemetryUtils";

import {
    telemetryState,
} from "../store/telemetryStore";

import BotControl from "../components/BotControl";

import RiskPanel from "../components/RiskPanel";

import TradeSettings from "../components/TradeSettings";

import ExecutionPanel from "../components/ExecutionPanel";

import ResultPanel from "../components/ResultPanel";

/* =================================================
   TELEMETRY STATE
================================================= */

const signalLogs = [];

const tradeLogs = [];

const unifiedTelemetry = {};

const journalTelemetry = {};

/* =================================================
   TELEMETRY STORE
================================================= */

const governance =
    telemetryState.governance;

const runtime =
    telemetryState.runtime;

const routerTelemetry =
    telemetryState.router;

const marketData =
    telemetryState.market;

const executionData =
    telemetryState.execution;

const riskData =
    telemetryState.risk;

/* =================================================
   DASHBOARD
================================================= */


const Dashboard = ({
    executionEnabled,
    setExecutionEnabled
}) => {

const [tradeSettings, setTradeSettings] = useState({

    mode: "PAPER",

    exchange: "BINANCE",

    symbol: "XRPUSDT",

    leverage: 5,

    timeframe: "1m",

    positionSize: 100,

    tp: 1.0,

    sl: 1.0,

    maxDd: 5,

    trailing: false,

    spreadFilter: true,

    volatilityFilter: true,

    liquidityFilter: true,

    spoofFilter: true,

    momentumFilter: true,

    killSwitch: false,

    autoFlatten: false,

});
const [, forceUpdate] = useState(0);

useEffect(() => {
    const id = setInterval(() => {
        forceUpdate(v => v + 1);
    }, 250);

    return () => clearInterval(id);
}, []);
    
    useEffect(() => {

        startWebSocketRuntime();

    }, []);

    return (

        <div className="dashboard">

            <div className="dashboard-layout">

            {/* =================================================
            LEFT COLUMN
            ================================================= */}

            <div className="left-column">

                <div className="panel-card">

                    <BotControl

                        config={tradeSettings}

                        executionEnabled={
                            executionEnabled
                        }

                        setExecutionEnabledState={
                            setExecutionEnabled
                        }

                    />

                </div>

                <div className="panel-card">

                <TradeSettings
                    values={tradeSettings}
                    onChange={(update) =>
                        setTradeSettings(prev => ({

                            ...prev,

                            ...update,

                        }))
                    }
                />

                </div>

                <div className="panel-card">

                    <RiskPanel
                        values={tradeSettings}
                        onChange={(update) =>
                            setTradeSettings(prev => ({

                                ...prev,

                                ...update,

                            }))
                        }
                    />

                </div>

                <div className="panel-card">

                    <FilterSettings
                        values={tradeSettings}
                        onChange={(update) =>
                            setTradeSettings(prev => ({

                                ...prev,

                                ...update,

                            }))
                        }
                    />

                </div>

                <div className="panel-card">

                    <SafetySettings
                        values={tradeSettings}
                        onChange={(update) =>
                            setTradeSettings(prev => ({

                                ...prev,

                                ...update,

                            }))
                        }
                    />

                </div>

                <div className="panel-card">

                    <QuickActions />

                </div>

            </div>

            {/* =================================================
            CENTER COLUMN
            ================================================= */}

            <div className="center-column">

                <div className="panel-card center-terminal-panel">

                    {/* =============================================
                       CENTER TERMINAL TITLE
                    ============================================= */}

                    <div className="center-terminal-title">
                        CENTER | MONITOR
                    </div>

                    {/* =============================================
                       RESULT PANEL
                    ============================================= */}

                    <ResultPanel

                        price={
                            marketData?.price
                        }

                        balance={
                            marketData?.balance
                        }

                        equity={
                            marketData?.equity
                        }

                        pnl={
                            marketData?.pnl
                        }

                        position={
                            marketData?.position
                            || "NONE"
                        }

                        marketRegime={
                            marketData?.marketRegime
                            || "UNDEFINED"
                        }

                        routingQuality={
                            routerTelemetry?.routingQuality
                            || "UNKNOWN"
                        }

                        marketHostility={
                            marketData?.marketHostility
                            ?? "--"
                        }

                    />

                    {/* =============================================
                       EXECUTION PANEL
                    ============================================= */}

                    <ExecutionPanel

                        executionAllowed={
                            governance?.executionEnabled
                        }

                        governanceMode={
                            governance?.mode
                            || "PAPER"
                        }

                        runtimePhase={
                            executionData?.runtimePhase
                            || "--"
                        }

                        routerRoute={
                            routerTelemetry?.route
                            || "UNKNOWN"
                        }

                        marketRegime={
                            marketData?.marketRegime
                            || "UNDEFINED"
                        }

                        websocketHealth={
                            runtime?.websocketHealth
                            ?? "--"
                        }

                        latency={
                            runtime?.latency
                            || "--"
                        }

                        spreadCondition={
                            riskData?.spreadSafety
                            || "UNKNOWN"
                        }

                        volatility={
                            marketData?.volatility
                            || "--"
                        }

                        liquidity={
                            marketData?.liquidity
                            || "--"
                        }

                        microstructureBias={
                            marketData?.microstructureBias
                            || "--"
                        }

                        routingQuality={
                            routerTelemetry?.routingQuality
                            || "UNKNOWN"
                        }

                    />

                    {/* =============================================
                       LOGS PANEL
                    ============================================= */}

                    <LogsPanel

                        signalLogs={
                            signalLogs
                        }

                        tradeLogs={
                            tradeLogs
                        }

                        routerTelemetry={
                            routerTelemetry
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

            </div>

            {/* =================================================
            RIGHT GOVERNANCE COLUMN
            ================================================= */}

            <div className="right-governance-column">

                {/* =============================================
                   EXECUTION MONITORING
                ============================================= */}

                <div className="execution-monitoring-card">

                    <div className="governance-card-title">
                        EXECUTION MONITORING（実行監視）
                    </div>

                    {/* =============================================
                       EXECUTION
                    ============================================= */}

                    <div className="monitoring-section">

                        <div className="monitoring-label">
                            EXECUTION
                        </div>

                        <div className="monitoring-grid">

                            <div className="monitoring-row">

                                <span>STATUS</span>

                                <span className={
                                    governance?.executionEnabled
                                        ? "status-safe"
                                        : "status-danger"
                                }>

                                    {
                                        governance?.executionEnabled
                                            ? "ENABLED（有効）"
                                            : "BLOCKED（停止）"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>POSITION</span>

                                <span>

                                    {
                                        marketData?.position
                                        ?? "NONE"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>WS</span>

                                <span className={
                                    runtime?.wsStatus
                                    === "CONNECTED"
                                        ? "status-safe"
                                        : "status-danger"
                                }>

                                    {
                                        runtime?.wsStatus
                                        ?? "-"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>HEALTH</span>

                                <span className={
                                    mapExecutionHealth(
                                        runtime?.latency
                                    ) === "STABLE（安定）"
                                        ? "status-safe"
                                        : mapExecutionHealth(
                                            runtime?.latency
                                        ) === "NORMAL（正常）"
                                            ? "status-warning"
                                            : "status-danger"
                                }>

                                    {
                                        mapExecutionHealth(
                                            runtime?.latency
                                        )
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>LATENCY</span>

                                <span>

                                    {
                                        runtime?.latency
                                        ?? "-"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>SPREAD</span>

                                <span className={
                                    mapSpreadSafety(
                                        riskData?.spreadSafety
                                    ) === "SAFE"
                                        ? "status-safe"
                                        : "status-warning"
                                }>

                                    {
                                        mapSpreadSafety(
                                            riskData?.spreadSafety
                                        )
                                    }

                                </span>

                            </div>

                        </div>

                    </div>

                    {/* =============================================
                       MARKET
                    ============================================= */}

                    <div className="monitoring-section">

                        <div className="monitoring-label">
                            MARKET
                        </div>

                        <div className="monitoring-grid">

                            <div className="monitoring-row">

                                <span>LIQUIDITY</span>

                                <span>

                                    {
                                        marketData?.liquidity
                                        ?? "-"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>VOLATILITY</span>

                                <span>

                                    {
                                        marketData?.volatility
                                        ?? "-"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>SPOOF</span>

                                <span>

                                    {
                                        marketData?.spoofRisk
                                        ?? "-"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>MARKET QUALITY</span>

                                <span>

                                    {
                                        marketData?.marketQuality
                                        ?? "NORMAL"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>NO TRADE</span>

                                <span className={
                                    riskData?.noTrade
                                        ? "status-danger"
                                        : "status-safe"
                                }>

                                    {
                                        riskData?.noTrade
                                            ? "ON（有効）"
                                            : "OFF（無効）"
                                    }

                                </span>

                            </div>

                        </div>

                    </div>

                    {/* =============================================
                       RESTRICTIONS
                    ============================================= */}

                    <div className="monitoring-section">

                        <div className="monitoring-label">
                            RESTRICTIONS
                        </div>

                        <div className="monitoring-grid">

                            <div className="monitoring-row">

                                <span>COOLDOWN</span>

                                <span className={
                                    riskData?.cooldown
                                        ? "status-warning"
                                        : "status-safe"
                                }>

                                    {
                                        riskData?.cooldown
                                            ? "ACTIVE（稼働）"
                                            : "OFF（無効）"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>ROUTER</span>

                                <span className={
                                    routerTelemetry?.status
                                    === "ACTIVE"
                                        ? "status-safe"
                                        : "status-danger"
                                }>

                                    {
                                        routerTelemetry?.status
                                        ?? "ACTIVE"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>EXECUTION</span>

                                <span className={
                                    governance?.executionEnabled
                                        ? "status-safe"
                                        : "status-danger"
                                }>

                                    {
                                        governance?.executionEnabled
                                            ? "ALLOWED"
                                            : "BLOCKED"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>REASON</span>

                                <span>

                                    {
                                        executionData?.restrictionReason
                                        ?? "-"
                                    }

                                </span>

                            </div>

                        </div>

                    </div>

                    {/* =============================================
                       QUALITY
                    ============================================= */}

                    <div className="monitoring-section">

                        <div className="monitoring-label">
                            QUALITY
                        </div>

                        <div className="monitoring-grid">

                            <div className="monitoring-row">

                                <span>EXECUTION</span>

                                <span className={
                                    runtime?.executionQuality
                                    === "GOOD（良好）"
                                        ? "status-safe"
                                        : runtime?.executionQuality
                                            === "WEAK（弱い）"
                                            ? "status-warning"
                                            : "status-danger"
                                }>

                                    {
                                        runtime?.executionQuality
                                        ?? "NORMAL（正常）"
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>LATENCY</span>

                                <span className={
                                    mapLatencyQuality(
                                        runtime?.latency
                                    ) === "GOOD"
                                        ? "status-safe"
                                        : mapLatencyQuality(
                                            runtime?.latency
                                        ) === "WEAK"
                                            ? "status-warning"
                                            : "status-danger"
                                }>

                                    {
                                        mapLatencyQuality(
                                            runtime?.latency
                                        )
                                    }

                                </span>

                            </div>

                            <div className="monitoring-row">

                                <span>ROUTING</span>

                                <span>

                                    {
                                        routerTelemetry?.routingQuality
                                        ?? "NORMAL"
                                    }

                                </span>

                            </div>

                        </div>

                    </div>

                </div>

                {/* =============================================
                   HUMAN GOVERNANCE
                ============================================= */}

                <div className="human-governance-card">

                    <div className="governance-card-title">
                        HUMAN GOVERNANCE
                    </div>

                    <div className="governance-control-grid">

                        <div className="governance-control-row">

                            <span>EXECUTION</span>

                            <button
                                className={
                                    governance?.executionEnabled
                                        ? "governance-button active"
                                        : "governance-button danger"
                                }
                            >

                                {
                                    governance?.executionEnabled
                                        ? "ENABLED（有効）"
                                        : "DISABLED（無効）"
                                }

                            </button>

                        </div>

                        <div className="governance-control-row">

                            <span>MODE</span>

                            <button className="governance-button">

                                {
                                    governance?.mode
                                    ?? "PAPER"
                                }

                            </button>

                        </div>

                        <div className="governance-control-row">

                            <span>RISK PROFILE</span>

                            <button className="governance-button">

                                {
                                    riskData?.riskProfile
                                    ?? "SAFE"
                                }

                            </button>

                        </div>

                        <div className="governance-control-row">

                            <span>AUTHORITY</span>

                            <button className="governance-button active">

                                {
                                    governance?.authority
                                    ?? "BACKEND"
                                }

                            </button>

                        </div>

                        <div className="governance-control-row">

                            <span>ROUTER</span>

                            <button
                                className={
                                    routerTelemetry?.status
                                    === "ACTIVE"
                                        ? "governance-button active"
                                        : "governance-button danger"
                                }
                            >

                                {
                                    routerTelemetry?.status
                                    ?? "ACTIVE"
                                }

                            </button>

                        </div>

                        <div className="governance-control-row">

                            <span>SESSION</span>

                            <button className="governance-button active">
                                ACTIVE
                            </button>

                        </div>

                        <div className="governance-control-row">

                            <span>NO TRADE</span>

                            <button
                                className={
                                    riskData?.noTrade
                                        ? "governance-button danger"
                                        : "governance-button"
                                }
                            >

                                {
                                    riskData?.noTrade
                                        ? "RESTRICTED（制限）"
                                        : "NORMAL（正常）"
                                }

                            </button>

                        </div>

                    </div>

                    {/* =============================================
                       EMERGENCY CONTROL
                    ============================================= */}

                    <div className="emergency-control-section">

                        <button className="emergency-stop-button">
                            EMERGENCY STOP（緊急停止）
                        </button>

                    </div>

                </div>

            </div>

        </div>

    </div>

    );

};

export default Dashboard;