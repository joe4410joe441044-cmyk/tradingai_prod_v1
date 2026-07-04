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

    exchange: "KUCOIN",

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
const [selectedStageId, setSelectedStageId] = useState("trading-runtime");

const governance = telemetryState.governance;
const runtime = telemetryState.runtime;
const marketData = telemetryState.market;

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

const exchangeConnection = normalizeConnection(firstAvailable(
    typeof botStatus?.ws_connected === "boolean"
        ? (botStatus.ws_connected ? "CONNECTED" : "DISCONNECTED")
        : undefined,
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
}), [
    botStatus,
]);

const browserWsConnected = runtimeHealth.browserWebSocket.connected === true;
const executionStatus = runtimeHealth.executionEngine.status ?? "UNKNOWN";
const apiHealth = botStatusSnapshot?.data?.runtime_health;
const wsHealth = runtime?.botStatus?.runtime_health;
const apiWsMismatch = Boolean(
    apiHealth?.statusFingerprint
    && wsHealth?.statusFingerprint
    && apiHealth.statusFingerprint !== wsHealth.statusFingerprint
    && apiHealth.snapshotId === wsHealth.snapshotId,
);
const displayedHealth = apiWsMismatch ? "CRITICAL" : runtimeHealth.health;
const displayedBlockingReason = apiWsMismatch
    ? "API_WS_MISMATCH"
    : runtimeHealth.blockingReason;

const selectedStage = runtimeHealth.stages.find(
    (stage) => stage.id === selectedStageId,
) ?? runtimeHealth.stages.find(
    (stage) => stage.id === runtimeHealth.activeStageId,
) ?? runtimeHealth.stages[0];

useEffect(() => {
    onRuntimeHealthChange?.({
        botStatus: runtimeHealth.running ? "RUNNING" : "STOPPED",
        wsStatus: runtimeHealth.browserWebSocket.status,
        engineStatus: runtimeHealth.runtimeEngine.status,
        executionState: executionStatus,
        latency: runtimeHealth.latencyMs,
        pipelineStatus: runtimeHealth.pipelineStatus,
        loopCount: runtimeHealth.loopCount,
    });
}, [
    executionStatus,
    onRuntimeHealthChange,
    runtimeHealth.browserWebSocket.status,
    runtimeHealth.latencyMs,
    runtimeHealth.loopCount,
    runtimeHealth.pipelineStatus,
    runtimeHealth.running,
    runtimeHealth.runtimeEngine.status,
]);

useEffect(() => {
    if (botStatus?.runtime_health) {
        setExecutionEnabled(runtimeHealth.executionEnabled);
    }
}, [
    botStatus?.runtime_health,
    runtimeHealth.executionEnabled,
    setExecutionEnabled,
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
                        exchange={firstAvailable(
                            botStatus?.exchange,
                            tradeSettings.exchange,
                        )}
                        connection={exchangeConnection}
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

                        executionStatus={
                            runtimeHealth.executionEngine.status
                        }

                        runtimePhase={
                            runtimeHealth.tradingAction.reason
                                ? `${runtimeHealth.tradingAction.status}: ${runtimeHealth.tradingAction.reason}`
                                : runtimeHealth.tradingAction.status
                        }

                        websocketStatus={
                            runtimeHealth.browserWebSocket.status
                        }

                        latency={
                            runtimeHealth.latencyMs
                        }

                        balance={
                            botStatus?.balance
                        }

                        equity={
                            botStatus?.equity
                        }

                        positionSide={
                            position
                        }

                    />

                    {/* =============================================
                       LOGS PANEL
                    ============================================= */}

                    <ExecutionTimelinePanel events={runtimeHealth.timeline} />

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
                            <span>RUNTIME HEALTH（稼働健全性）</span>
                            <span className={
                                displayedHealth === "HEALTHY"
                                    ? "status-safe"
                                    : displayedHealth === "DEGRADED"
                                        ? "status-warning"
                                        : "status-danger"
                            }>
                                {displayedHealth}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>TRADING ACTION（取引判断）</span>
                            <span className={
                                runtimeHealth.tradingAction.status === "ORDER_SUBMITTED"
                                    ? "status-safe"
                                    : "status-warning"
                            }>
                                {runtimeHealth.tradingAction.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>EXECUTION ENGINE（実行エンジン）</span>
                            <span className={runtimeHealth.executionEngine.available
                                ? "status-safe"
                                : "status-danger"
                            }>
                                {runtimeHealth.executionEngine.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>BROWSER WS（画面通信）</span>
                            <span className={browserWsConnected ? "status-safe" : "status-danger"}>
                                {runtimeHealth.browserWebSocket.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>EXCHANGE WS（取引所通信）</span>
                            <span className={runtimeHealth.exchangeWebSocket.connected
                                ? "status-safe"
                                : "status-danger"
                            }>
                                {runtimeHealth.exchangeWebSocket.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>ACTION REASON（待機理由）</span>
                            <span>{runtimeHealth.tradingAction.reason ?? "--"}</span>
                        </div>

                        <div className="monitoring-row">
                            <span>BLOCKING REASON（障害理由）</span>
                            <span className={displayedBlockingReason
                                ? "status-danger"
                                : "status-safe"
                            }>
                                {displayedBlockingReason ?? "NONE"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>LATENCY（遅延）</span>
                            <span>{runtimeHealth.latencyMs ?? "--"}</span>
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
