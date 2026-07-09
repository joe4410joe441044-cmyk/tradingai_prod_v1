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
import AccountRuntimeOverview from "../components/runtime/AccountRuntimeOverview";
import RuntimeHealthPanel from "../components/runtime/RuntimeHealthPanel";
import ExecutionTimelinePanel from "../components/runtime/ExecutionTimelinePanel";
import StageInspectorPanel from "../components/runtime/StageInspectorPanel";
import Header from "../components/header";

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


const Dashboard = () => {

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

    risk_percent: 1.0,

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
const [executionEnabled, setExecutionEnabled] = useState(false);
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
    if (botStatus?.runtime_health) {
        const updateId = setTimeout(() => {
            setExecutionEnabled(runtimeHealth.executionEnabled);
        }, 0);

        return () => clearTimeout(updateId);
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

        <>
        <Header runtimeHealth={runtimeHealth} />
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

                        botRunning={runtimeHealth.running}

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

                    <AccountRuntimeOverview
                        exchange={firstAvailable(
                            botStatus?.exchange,
                            tradeSettings.exchange,
                        )}
                        selectedMode={firstAvailable(
                            tradeSettings.mode,
                            botStatus?.selectedMode,
                            governance?.mode,
                        )}
                        executionMode={firstAvailable(
                            botStatus?.executionMode,
                            botStatus?.execution_mode,
                            "SIMULATION",
                        )}
                        realOrderAllowed={firstAvailable(
                            botStatus?.realOrderAllowed,
                            botStatus?.real_order_allowed,
                            false,
                        ) === true}
                        dryRun={firstAvailable(
                            botStatus?.dryRun,
                            true,
                        ) !== false}
                        safetyReason={botStatus?.safetyReason}
                        allowLive={botStatus?.allowLive}
                        tradeMode={botStatus?.tradeMode}
                        accountSource={firstAvailable(
                            botStatus?.accountSource,
                            "NOT_CONNECTED",
                        )}
                        balanceSource={firstAvailable(
                            botStatus?.balanceSource,
                            "NOT_CONNECTED",
                        )}
                        positionSource={firstAvailable(
                            botStatus?.positionSource,
                            "NOT_CONNECTED",
                        )}
                        exchangeAuth={firstAvailable(
                            botStatus?.exchangeAuth,
                            "NOT_VERIFIED",
                        )}
                        realAccountConnected={
                            botStatus?.realAccountConnected === true
                        }
                        realBalance={botStatus?.realBalance}
                        realPosition={botStatus?.realPosition}
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

                <div
                    className="execution-monitoring-card"
                    data-testid="runtime-health-monitor"
                >

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
                            <span>BOT STATE（ボット状態）</span>
                            <span
                                data-testid="bot-state"
                                className={runtimeHealth.running
                                ? "status-safe"
                                : "status-warning"
                                }
                            >
                                {runtimeHealth.running ? "RUNNING" : "STOPPED"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>TRADING RUNTIME（取引ランタイム）</span>
                            <span
                                data-testid="trading-runtime"
                                className={runtimeHealth.runtimeEngine.healthy
                                    ? "status-safe"
                                    : "status-warning"
                                }
                            >
                                {runtimeHealth.runtimeEngine.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>PIPELINE（パイプライン）</span>
                            <span
                                data-testid="pipeline-status"
                                className={runtimeHealth.pipelineStatus === "OK"
                                    ? "status-safe"
                                    : "status-warning"
                                }
                            >
                                {runtimeHealth.pipelineStatus ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>EXECUTION AUTHORITY（注文送信許可）</span>
                            <span className={runtimeHealth.executionEnabled
                                ? "status-safe"
                                : "status-warning"
                            }>
                                {runtimeHealth.executionAuthority.status}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>TRADING ACTION（取引判断）</span>
                            <span
                                data-testid="trading-action"
                                className={
                                runtimeHealth.tradingAction.status === "ORDER_SUBMITTED"
                                    ? "status-safe"
                                    : "status-warning"
                                }
                            >
                                {runtimeHealth.tradingAction.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>DECISION（判断）</span>
                            <span data-testid="current-decision">
                                {runtimeHealth.tradingAction.decision ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>EXECUTION ENGINE（実行エンジン）</span>
                            <span
                                data-testid="execution-engine"
                                className={runtimeHealth.executionEngine.available
                                ? "status-safe"
                                : runtimeHealth.running
                                    ? "status-danger"
                                    : "status-warning"
                                }
                            >
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
                            <span
                                data-testid="exchange-ws"
                                className={runtimeHealth.exchangeWebSocket.connected
                                ? "status-safe"
                                : runtimeHealth.running
                                    ? "status-danger"
                                    : "status-warning"
                                }
                            >
                                {runtimeHealth.exchangeWebSocket.status ?? "--"}
                            </span>
                        </div>

                        <div className="monitoring-row">
                            <span>ACTION REASON（待機理由）</span>
                            <span data-testid="action-reason">
                                {runtimeHealth.tradingAction.reason ?? "--"}
                            </span>
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
    </>

    );

};

export default Dashboard;
