import {
    useCallback,
    useEffect,
    useMemo,
    useState,
} from "react";

import { API } from "../api";
import usePolling from "../hooks/usePolling";
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
import OperationAuthGate from "../components/auth/OperationAuthGate";
import {
    pendingOrderAuthorityValue,
} from "../components/operation/operationPreparationModel";


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

/* =================================================
   DASHBOARD
================================================= */


const Dashboard = () => {

const { data: botStatusSnapshot } = usePolling(
    fetchBotStatus,
    5000,
);

const { tradeSettings, setTradeSettings } = useDashboardMarketContext();
const [, forceUpdate] = useState(0);
const [executionEnabled, setExecutionEnabled] = useState(false);
const [selectedStageId, setSelectedStageId] = useState("trading-runtime");
const [manualBotStatusSnapshot, setManualBotStatusSnapshot] = useState(null);

const refreshBotStatus = useCallback(async () => {
    const snapshot = await fetchBotStatus();

    setManualBotStatusSnapshot(snapshot);

    return snapshot.data;
}, []);

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

                <div className="operations-top-body">

                    <div className="operations-top-section operations-bot-control">

                        <OperationAuthGate>

                            <BotControl

                            config={{
                                ...tradeSettings,
                                ...(runtimeHealth.running ? {
                                    positionSize: firstAvailable(botStatus?.positionSize, botStatus?.position_size, tradeSettings.positionSize),
                                    timeframe: firstAvailable(botStatus?.timeframe, tradeSettings.timeframe),
                                    tp: firstAvailable(botStatus?.tp_percent, botStatus?.tradeSettings?.tp_percent, tradeSettings.tp),
                                    sl: firstAvailable(botStatus?.sl_percent, botStatus?.tradeSettings?.sl_percent, tradeSettings.sl),
                                    trailing: firstAvailable(botStatus?.trailingStop, botStatus?.trailing_stop, botStatus?.tradeSettings?.trailing_stop, tradeSettings.trailing) === true,
                                    leverage: firstAvailable(botStatus?.leverage, botStatus?.tradeSettings?.leverage, tradeSettings.leverage),
                                } : {}),
                                selectionMode: tradeSettings.selectionMode || botStatus?.selectionMode || botStatus?.autoMarketSelection?.selectionMode || "NOT EXPOSED",
                                displaySymbol: botStatus?.autoMarketSelection?.topCandidate?.symbol,
                                autoMarketState: botStatus?.autoMarketSelection?.productionIntegration?.status || "NOT AVAILABLE",
                                executionMode: botStatus?.executionMode || botStatus?.execution_mode,
                                realOrderAllowed: botStatus?.realOrderAllowed === true || botStatus?.real_order_allowed === true,
                                realOrderAuthorityKnown: typeof botStatus?.realOrderAllowed === "boolean"
                                    || typeof botStatus?.real_order_allowed === "boolean",
                                allowLive: botStatus?.allowLive,
                                tradeMode: botStatus?.tradeMode,
                                leverageAuthority: botStatus?.leverageAuthority ?? null,
                                paperBootstrapEligible: botStatus?.paperBootstrapEligible,
                                paperBootstrapStatus: botStatus?.paperBootstrapStatus,
                                paperBootstrapReasonCodes: botStatus?.paperBootstrapReasonCodes,
                                paperBootstrapSource: botStatus?.paperBootstrapSource,
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
                                pendingOrderAuthorityValue(botStatus)
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

                        </OperationAuthGate>

                    </div>

                </div>

            </div>

            {/* =================================================
            CENTER COLUMN
            ================================================= */}

            <div className="center-column">

                <div className="panel-card center-terminal-panel">

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
