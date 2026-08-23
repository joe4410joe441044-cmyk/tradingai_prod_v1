import {
    useCallback,
    useEffect,
    useMemo,
    useState,
    useRef,
} from "react";
import ReactDOM from "react-dom";

import { API } from "../api";
import usePolling from "../hooks/usePolling";
import AccountRuntimeOverview from "../components/runtime/AccountRuntimeOverview";
import RuntimeDiagnosticsDisclosure from "../components/runtime/RuntimeDiagnosticsDisclosure";
import TradingDecisionCard from "../components/runtime/TradingDecisionCard";
import { formatActivityTime, getLastExecutionActivity } from "../runtime/runtimeDisplay";
import Header from "../components/header";

import { deriveRuntimeHealth } from "../utils/runtimeHealth";

import {
    telemetryState,
} from "../store/telemetryStore";
import { useDashboardMarketContext } from "../state/dashboard-market/DashboardMarketContext";

import BotControl from "../components/BotControl";
import EmergencyControls from "../components/operation/EmergencyControls";


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
    const emergencyContainerRef = useRef(null);

const { data: botStatusSnapshot } = usePolling(
    fetchBotStatus,
    5000,
);

const { tradeSettings, setTradeSettings } = useDashboardMarketContext();
const [, forceUpdate] = useState(0);
const [executionEnabled, setExecutionEnabled] = useState(false);
const [selectedStageId, setSelectedStageId] = useState("trading-runtime");
const [manualBotStatusSnapshot, setManualBotStatusSnapshot] = useState(null);

    const onRenderEmergency = useCallback((emergencyProps) => {
        if (emergencyContainerRef.current) {
            ReactDOM.render(
                <EmergencyControls {...emergencyProps} />,
                emergencyContainerRef.current
            );
        }
    }, []);

    const refreshBotStatus = useCallback(async () => {
        const snapshot = await fetchBotStatus();

        setManualBotStatusSnapshot(snapshot);

        return snapshot.data;
    }, []);

const governance = telemetryState.governance;
const runtime = telemetryState.runtime;
const marketData = telemetryState.market;

const apiBotStatusSnapshot = (
    manualBotStatusSnapshot?.receivedAt
        > (botStatusSnapshot?.receivedAt || 0)
        ? manualBotStatusSnapshot
        : botStatusSnapshot
);

const statusReceivedAt = apiBotStatusSnapshot?.receivedAt;
const websocketStatusReceivedAt = runtime?.botStatusLastUpdate;
const botStatus = runtime?.botStatus && (
    !statusReceivedAt
    || websocketStatusReceivedAt >= statusReceivedAt
)
    ? runtime.botStatus
    : apiBotStatusSnapshot?.data;
const statusEmergency = (
    apiBotStatusSnapshot?.data?.emergency
    && typeof apiBotStatusSnapshot.data.emergency === "object"
        ? apiBotStatusSnapshot.data.emergency
        : (
            botStatus?.emergency
            && typeof botStatus.emergency === "object"
                ? botStatus.emergency
                : undefined
        )
);
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
const lastExecutionActivity = getLastExecutionActivity(runtimeHealth.timeline);

const browserWsConnected = runtimeHealth.browserWebSocket.connected === true;
const apiHealth = apiBotStatusSnapshot?.data?.runtime_health;
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

const accountRuntimeProps = {
    accountRuntime: botStatus?.accountRuntime,
    exchange: firstAvailable(
        botStatus?.exchange,
        tradeSettings.exchange,
    ),
    selectedMode: firstAvailable(
        tradeSettings.mode,
        botStatus?.selectedMode,
        governance?.mode,
    ),
    executionMode: firstAvailable(
        botStatus?.executionMode,
        botStatus?.execution_mode,
        "SIMULATION",
    ),
    realOrderAllowed: firstAvailable(
        botStatus?.realOrderAllowed,
        botStatus?.real_order_allowed,
        false,
    ) === true,
    dryRun: firstAvailable(
        botStatus?.dryRun,
        true,
    ) !== false,
    safetyReason: botStatus?.safetyReason,
    allowLive: botStatus?.allowLive,
    tradeMode: botStatus?.tradeMode,
    accountSource: firstAvailable(
        botStatus?.accountSource,
        "NOT_CONNECTED",
    ),
    balanceSource: firstAvailable(
        botStatus?.balanceSource,
        "NOT_CONNECTED",
    ),
    positionSource: firstAvailable(
        botStatus?.positionSource,
        "NOT_CONNECTED",
    ),
    exchangeAuth: firstAvailable(
        botStatus?.exchangeAuth,
        "NOT_VERIFIED",
    ),
    exchangeConnection: firstAvailable(
        botStatus?.exchangeConnection,
        "NOT_CONNECTED",
    ),
    apiKeyStatus: firstAvailable(
        botStatus?.apiKeyStatus,
        "MISSING",
    ),
    permission: firstAvailable(
        botStatus?.permission,
        "NOT_VERIFIED",
    ),
    accountType: firstAvailable(
        botStatus?.accountType,
        "UNKNOWN",
    ),
    exchangeAuthReason: botStatus?.exchangeAuthReason,
    exchangeConnectionReason: botStatus?.exchangeConnectionReason,
    accountReason: botStatus?.accountReason,
    balanceReason: botStatus?.balanceReason,
    positionReason: botStatus?.positionReason,
    accountSourceReason: botStatus?.accountSourceReason,
    balanceSourceReason: botStatus?.balanceSourceReason,
    positionSourceReason: botStatus?.positionSourceReason,
    realAccountConnected: botStatus?.realAccountConnected === true,
    realBalance: botStatus?.realBalance,
    realEquity: botStatus?.realEquity,
    realAvailableBalance: botStatus?.realAvailableBalance,
    realPosition: botStatus?.realPosition,
    realPositionState: botStatus?.realPositionState,
    realAccountLastSync: botStatus?.realAccountLastSync,
    realLastSync: botStatus?.realLastSync,
    balance: firstAvailable(
        botStatus?.balance,
        wsMarketData?.balance,
    ),
    equity: firstAvailable(
        botStatus?.equity,
        wsMarketData?.equity,
    ),
    availableBalance: firstAvailable(
        wsMarketData?.availableBalance,
        wsMarketData?.available_balance,
        botStatus?.availableBalance,
        botStatus?.available_balance,
    ),
    position,
    pnl: firstAvailable(
        botStatus?.pnl,
        wsMarketData?.pnl,
        wsMarketData?.unrealizedPnL,
    ),
    lastUpdate,
};

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
    
    return (

        <>
        <Header runtimeHealth={runtimeHealth} />
        <div className="dashboard">

            <div className="dashboard-layout">

            {/* =================================================
            TOP: OPERATION (FULL WIDTH)
            ================================================= */}

            <div className="operations-top-card left-column panel-card">

                <div className="operations-top-card-header">
                    <div className="left-card-title section-number-title">
                        OPERATION
                    </div>
                    <div 
                        className="operations-top-emergency-container"
                        ref={emergencyContainerRef}
                    />
                </div>

                <div className="operations-top-body">

                    <div className="operations-top-section operations-bot-control">

                        <BotControl
                            onRenderEmergency={onRenderEmergency}

                            config={{
                                ...tradeSettings,
                                selectionMode: tradeSettings.selectionMode || botStatus?.selectionMode || botStatus?.autoMarketSelection?.selectionMode || "NOT EXPOSED",
                                displaySymbol: botStatus?.activeSymbol || botStatus?.autoMarketSelection?.activeSymbol,
                                autoMarketState: botStatus?.autoMarketSelection?.autoRuntime?.runtimeState || "NOT AVAILABLE",
                                executionMode: botStatus?.executionMode || botStatus?.execution_mode,
                                realOrderAllowed: botStatus?.realOrderAllowed === true || botStatus?.real_order_allowed === true,
                                realOrderAuthorityKnown: typeof botStatus?.realOrderAllowed === "boolean"
                                    || typeof botStatus?.real_order_allowed === "boolean",
                                allowLive: botStatus?.allowLive,
                                tradeMode: botStatus?.tradeMode,
                                leverageAuthority: botStatus?.leverageAuthority ?? null,
                                requestedLeverage: botStatus?.leverageAuthority?.requestedLeverage,
                            }}

                            executionEnabled={
                                executionEnabled
                            }

                            botRunning={runtimeHealth.running}

                            loopEnabled={
                                typeof botStatus?.loopEnabled === "boolean"
                                    ? botStatus.loopEnabled
                                    : runtimeHealth.running
                            }

                            loopState={
                                botStatus?.loopState
                                || runtimeHealth.lifecycle?.state
                            }

                            emergencyLocked={
                                typeof botStatus?.emergencyLocked === "boolean"
                                    ? botStatus.emergencyLocked
                                    : undefined
                            }

                            emergencyState={
                                botStatus?.emergencyState
                            }

                            emergency={
                                statusEmergency
                            }

                            pendingOrder={
                                botStatus?.pendingOrder
                            }

                            position={position}

                            runtimeHealth={runtimeHealth}

                            onStatusRefresh={
                                refreshBotStatus
                            }

                            setExecutionEnabledState={
                                setExecutionEnabled
                            }

                            onLegacyConfigChange={(update) => setTradeSettings((previous) => ({
                                ...previous,
                                ...update,
                            }))}

                        />

                    </div>

                </div>

            </div>

            {/* =================================================
            CENTER COLUMN
            ================================================= */}

            <div className="center-column">

                <div className="panel-card center-terminal-panel">

                    <AccountRuntimeOverview
                        variant="summary"
                        {...accountRuntimeProps}
                        onPaperCapitalApplied={refreshBotStatus}
                    />

                    <div className="execution-activity" data-testid="last-execution-activity">
                        <span>{lastExecutionActivity.label}</span>
                        <strong>{formatActivityTime(lastExecutionActivity.timestamp)}</strong>
                    </div>

                </div>

            </div>

        </div>

        <TradingDecisionCard decision={botStatus?.tradingDecision} />

        <RuntimeDiagnosticsDisclosure
            runtimeHealth={runtimeHealth}
            displayedHealth={displayedHealth}
            displayedBlockingReason={displayedBlockingReason}
            browserWsConnected={browserWsConnected}
            selectedStageId={selectedStageId}
            onSelectStage={setSelectedStageId}
            selectedStage={selectedStage}
        />

    </div>
    </>

    );

};

export default Dashboard;
