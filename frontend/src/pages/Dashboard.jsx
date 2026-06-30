import {
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    startWebSocketRuntime,
} from "../runtime/websocketRuntime";
import { API } from "../api";
import usePolling from "../hooks/usePolling";
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
import { deriveRuntimeHealth } from "../utils/runtimeHealth";

import {
    telemetryState,
} from "../store/telemetryStore";

import BotControl from "../components/BotControl";

import RiskPanel from "../components/RiskPanel";

import TradeSettings from "../components/TradeSettings";

import ExecutionPanel from "../components/ExecutionPanel";

const fetchBotStatus = async () => {
    const response = await fetch(API.botStatus());

    if (!response.ok) {
        throw new Error(`Bot status request failed: ${response.status}`);
    }

    return {
        data: await response.json(),
        receivedAt: Date.now(),
    };
};

const firstAvailable = (...values) => (
    values.find((value) => (
        value !== null
        && value !== undefined
        && value !== ""
        && !(typeof value === "number" && !Number.isFinite(value))
    ))
);

const getPositionSide = (position) => {
    const candidate = Array.isArray(position)
        ? position[0]
        : position;

    if (!candidate) {
        return undefined;
    }

    if (typeof candidate !== "object") {
        return candidate;
    }

    return firstAvailable(
        candidate.side,
        candidate.position_side,
        candidate.state,
    );
};

const normalizeConnection = (value) => {
    const normalized = String(value ?? "").trim().toUpperCase();

    return ["CONNECTED", "LIVE", "ONLINE", "OPEN"].includes(normalized)
        ? "CONNECTED"
        : "DISCONNECTED";
};

const normalizeTimestamp = (value) => {
    if (value === null || value === undefined || value === "") {
        return undefined;
    }

    const numericValue = Number(value);

    if (Number.isFinite(numericValue)) {
        return numericValue < 1_000_000_000_000
            ? numericValue * 1000
            : numericValue;
    }

    return value;
};

/* =================================================
   DASHBOARD
================================================= */


const Dashboard = ({
    executionEnabled,
    setExecutionEnabled,
    onRuntimeHealthChange,
}) => {

const { data: botStatusSnapshot } = usePolling(
    fetchBotStatus,
    5000,
);

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
const [selectedStageId, setSelectedStageId] = useState(null);

const governance = telemetryState.governance;
const runtime = telemetryState.runtime;
const marketData = telemetryState.market;
const executionData = telemetryState.execution;
const cognitionData = telemetryState.cognition;
const executionRuntimeData = telemetryState.executionRuntime;

const statusReceivedAt = botStatusSnapshot?.receivedAt;
const websocketStatusReceivedAt = runtime?.botStatusLastUpdate;
const botStatus = runtime?.botStatus && (
    !statusReceivedAt
    || websocketStatusReceivedAt >= statusReceivedAt
)
    ? runtime.botStatus
    : botStatusSnapshot?.data;
const wsMarketData = marketData?.lastUpdate
    ? marketData
    : undefined;

const connection = normalizeConnection(firstAvailable(
    typeof botStatus?.ws_connected === "boolean"
        ? (botStatus.ws_connected ? "CONNECTED" : "DISCONNECTED")
        : undefined,
    runtime?.connectionState,
    runtime?.wsStatus,
));

const position = firstAvailable(
    getPositionSide(botStatus?.actual_position),
    getPositionSide(botStatus?.position),
    getPositionSide(wsMarketData?.position),
);

const lastUpdate = normalizeTimestamp(firstAvailable(
    botStatus?.last_update,
    botStatus?.timestamp,
    statusReceivedAt,
    runtime?.lastMessageTimestamp,
));

const runtimeHealth = useMemo(() => deriveRuntimeHealth({
    botStatus,
    marketState: marketData?.lastUpdate ? marketData : undefined,
    aiState: cognitionData?.lastUpdate
        ? cognitionData
        : undefined,
    governanceState: governance?.lastUpdate
        ? governance
        : undefined,
    executionState: executionRuntimeData?.lastUpdate
        ? executionRuntimeData
        : undefined,
    statusReceivedAt,
}), [
    botStatus,
    cognitionData,
    executionRuntimeData,
    governance,
    marketData,
    statusReceivedAt,
]);

const selectedStage = runtimeHealth.stages.find(
    (stage) => stage.id === selectedStageId,
);

useEffect(() => {
    onRuntimeHealthChange?.({
        pipelineStatus: runtimeHealth.pipelineStatus,
        loopCount: runtimeHealth.loopCount,
    });
}, [
    onRuntimeHealthChange,
    runtimeHealth.loopCount,
    runtimeHealth.pipelineStatus,
]);

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
                        connection={connection}
                        mode={firstAvailable(
                            tradeSettings.mode,
                            botStatus?.execution_mode,
                            governance?.mode,
                        )}
                        balance={firstAvailable(
                            botStatus?.balance,
                            wsMarketData?.balance,
                        )}
                        equity={firstAvailable(
                            botStatus?.equity,
                            wsMarketData?.equity,
                        )}
                        availableBalance={
                            firstAvailable(
                                wsMarketData?.availableBalance,
                                wsMarketData?.available_balance,
                                botStatus?.availableBalance,
                                botStatus?.available_balance,
                            )
                        }
                        position={position}
                        pnl={firstAvailable(
                            botStatus?.pnl,
                            wsMarketData?.pnl,
                            wsMarketData?.unrealizedPnL,
                        )}
                        lastUpdate={lastUpdate}
                    />

                    <RuntimeHealthPanel
                        stages={runtimeHealth.stages}
                        loops={runtimeHealth.loops}
                        selectedStageId={selectedStageId}
                        onSelectStage={setSelectedStageId}
                    />

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

                <StageInspectorPanel stage={selectedStage} />

            </div>

        </div>

    </div>

    );

};

export default Dashboard;
