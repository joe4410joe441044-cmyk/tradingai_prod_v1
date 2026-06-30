import {
    useEffect,
    useState,
} from "react";

import {
    startWebSocketRuntime,
} from "../runtime/websocketRuntime";
import ExchangeLivePanel from "../components/runtime/ExchangeLivePanel";
import RuntimeHealthPanel from "../components/runtime/RuntimeHealthPanel";
import ExecutionTimelinePanel from "../components/runtime/ExecutionTimelinePanel";
import StageInspectorPanel from "../components/runtime/StageInspectorPanel";

import FilterSettings from "../components/FilterSettings";
import SafetySettings from "../components/SafetySettings";
import QuickActions from "../components/QuickActions";

import {
    mapExecutionHealth,
} from "../utils/telemetryUtils";

import {
    telemetryState,
} from "../store/telemetryStore";

import BotControl from "../components/BotControl";

import RiskPanel from "../components/RiskPanel";

import TradeSettings from "../components/TradeSettings";

import ExecutionPanel from "../components/ExecutionPanel";

/* =================================================
   TELEMETRY STORE
================================================= */

const governance =
    telemetryState.governance;

const runtime =
    telemetryState.runtime;

const marketData =
    telemetryState.market;

const executionData =
    telemetryState.execution;

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
                        CENTER（中央監視）
                    </div>

                    <ExchangeLivePanel
                        exchange={tradeSettings.exchange}
                        connection={runtime?.wsStatus}
                        mode={tradeSettings.mode ?? governance?.mode}
                        balance={marketData?.balance}
                        equity={marketData?.equity}
                        availableBalance={
                            marketData?.availableBalance
                            ?? marketData?.available_balance
                        }
                        position={marketData?.position}
                        pnl={
                            marketData?.pnl
                            ?? marketData?.unrealizedPnL
                        }
                        lastUpdate={
                            marketData?.lastUpdate
                            ?? marketData?.last_update
                        }
                    />

                    <RuntimeHealthPanel />

                    {/* =============================================
                       EXECUTION PANEL
                    ============================================= */}

                    <ExecutionPanel

                        executionAllowed={
                            governance?.executionEnabled
                            ?? executionData?.executionAllowed
                            ?? executionEnabled
                        }

                        runtimePhase={
                            executionData?.runtimePhase
                            ?? runtime?.runtimePhase
                        }

                        websocketStatus={
                            runtime?.wsStatus
                        }

                        latency={
                            runtime?.latency
                        }

                        balance={
                            marketData?.balance
                        }

                        equity={
                            marketData?.equity
                        }

                        positionSide={
                            marketData?.position
                        }

                    />

                    {/* =============================================
                       LOGS PANEL
                    ============================================= */}

                    <ExecutionTimelinePanel />

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

                    <div className="monitoring-grid execution-state-grid">
                        <div className="monitoring-row">
                            <span>EXECUTION STATUS（実行状態）</span>
                            <span className={
                                governance?.executionEnabled
                                    ? "status-safe"
                                    : "status-danger"
                            }>
                                {governance?.executionEnabled
                                    ? "ENABLED"
                                    : "BLOCKED"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>WS（通信）</span>
                            <span className={
                                runtime?.wsStatus === "CONNECTED"
                                    ? "status-safe"
                                    : "status-danger"
                            }>
                                {runtime?.wsStatus ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>LATENCY（遅延）</span>
                            <span>{runtime?.latency ?? "--"}</span>
                        </div>

                        <div className="monitoring-row">
                            <span>HEALTH（健全性）</span>
                            <span className={
                                mapExecutionHealth(runtime?.latency)
                                === "STABLE（安定）"
                                    ? "status-safe"
                                    : mapExecutionHealth(runtime?.latency)
                                    === "NORMAL（正常）"
                                        ? "status-warning"
                                        : "status-danger"
                            }>
                                {mapExecutionHealth(runtime?.latency)}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>POSITION（ポジション）</span>
                            <span>{marketData?.position ?? "--"}</span>
                        </div>
                    </div>

                </div>

                <StageInspectorPanel />

            </div>

        </div>

    </div>

    );

};

export default Dashboard;
