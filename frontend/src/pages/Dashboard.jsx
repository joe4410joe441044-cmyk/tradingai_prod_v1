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
    deriveLiveCapitalAuthority,
    pendingOrderAuthorityValue,
    resolveOperationDisplaySymbol,
} from "../components/operation/operationPreparationModel";
import { performSaveSettings } from "../features/trade-settings/saveSettings";
import { authenticatedControlRequest } from "../features/auth/operatorAuth";


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

// Shared BotControl config builder. The DRAFT config is built from the live
// editor state; the SAVED config is built from the last committed SAVE
// SETTINGS revision. Runtime context fields (execution mode, real-order
// authority, LIVE permission, display symbol) are appended identically to
// both, but the authoritative trade values (mode / symbol / leverage / SL /
// TP / size / timeframe / automation switches) come from the supplied base.
const buildBotConfig = (base, botStatus, running) => ({
    ...base,
    ...(running ? {
        positionSize: firstAvailable(botStatus?.positionSize, botStatus?.position_size, base.positionSize),
        timeframe: firstAvailable(botStatus?.timeframe, base.timeframe),
        tp: firstAvailable(botStatus?.tp_percent, botStatus?.tradeSettings?.tp_percent, base.tp),
        sl: firstAvailable(botStatus?.sl_percent, botStatus?.tradeSettings?.sl_percent, base.sl),
        trailing: firstAvailable(botStatus?.trailingStop, botStatus?.trailing_stop, botStatus?.tradeSettings?.trailing_stop, base.trailing) === true,
        leverage: firstAvailable(botStatus?.leverage, botStatus?.tradeSettings?.leverage, base.leverage),
    } : {}),
    selectionMode: base.selectionMode || botStatus?.selectionMode || botStatus?.autoMarketSelection?.selectionMode || "NOT EXPOSED",
    displaySymbol: resolveOperationDisplaySymbol(botStatus),
    autoMarketState: botStatus?.autoMarketSelection?.productionIntegration?.status || "NOT AVAILABLE",
    executionMode: botStatus?.executionMode || botStatus?.execution_mode,
    realOrderAllowed: botStatus?.realOrderAllowed === true || botStatus?.real_order_allowed === true,
    realOrderAuthorityKnown: typeof botStatus?.realOrderAllowed === "boolean"
        || typeof botStatus?.real_order_allowed === "boolean",
    allowLive: botStatus?.allowLive,
    tradeMode: botStatus?.tradeMode,
    tradeModeCapability: botStatus?.tradeModeCapability,
    selectedMode: botStatus?.selectedMode,
    savedMode: botStatus?.savedMode,
    savedModeRevision: botStatus?.savedModeRevision,
    runtimeMode: botStatus?.runtimeMode,
    dryRun: typeof botStatus?.dryRun === "boolean" ? botStatus.dryRun : undefined,
    leverageAuthority: botStatus?.leverageAuthority ?? null,
    paperBootstrapEligible: botStatus?.paperBootstrapEligible,
    paperBootstrapStatus: botStatus?.paperBootstrapStatus,
    paperBootstrapReasonCodes: botStatus?.paperBootstrapReasonCodes,
    paperBootstrapSource: botStatus?.paperBootstrapSource,
});

/* =================================================
   DASHBOARD
================================================= */


const Dashboard = () => {

const { data: botStatusSnapshot } = usePolling(
    fetchBotStatus,
    5000,
);

const {
    tradeSettings,
    setTradeSettings,
    savedSettings,
    settingsRevision,
    settingsDirty,
    commitSavedSettings,
} = useDashboardMarketContext();
const [, forceUpdate] = useState(0);
const [executionEnabled, setExecutionEnabled] = useState(false);
const [selectedStageId, setSelectedStageId] = useState("trading-runtime");
const [manualBotStatusSnapshot, setManualBotStatusSnapshot] = useState(null);
const [savingSettings, setSavingSettings] = useState(false);
const [settingsSaveError, setSettingsSaveError] = useState(null);
const [settingsSaveNotice, setSettingsSaveNotice] = useState(null);

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

// LIVE account context read path (read-only). SAVE SETTINGS refreshes this via
// /bot/status; Final Preparation surfaces it when the SAVED mode is LIVE so the
// operator can confirm LIVE capital while the runtime is still STOPPED.
// The authority object carries the canonical source + freshness so the UI
// never falls back to PAPER capital while LIVE is selected.
const liveCapitalAuthority = deriveLiveCapitalAuthority(botStatus);
const liveAccountCapital = firstAvailable(
    botStatus?.realEquity,
    botStatus?.realAvailableBalance,
    botStatus?.realBalance,
);

// Canonical selected/saved destination authority. The backend savedMode is
// the source of truth for the next START destination; localStorage is only a
// fallback while the backend value has not yet been observed.
const canonicalSavedMode = (() => {
    const candidate = String(botStatus?.savedMode ?? "").trim().toUpperCase();
    return candidate === "LIVE" || candidate === "PAPER" ? candidate : null;
})();

// Persist the mode to the backend canonical saved-mode authority. This is a
// pure configuration write: it never starts the runtime, arms LIVE, constructs
// an execution engine, changes real-order authority, or places an order.
const persistSavedMode = useCallback(async (mode) => {
    const normalized = String(mode ?? "").trim().toUpperCase();
    if (normalized !== "PAPER" && normalized !== "LIVE") {
        return { ok: false, code: "INVALID_MODE" };
    }
    const expectedRevision = Number.isFinite(Number(botStatus?.savedModeRevision))
        ? Number(botStatus.savedModeRevision)
        : undefined;
    try {
        const response = await authenticatedControlRequest(API.botSavedMode(), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "application/json",
            },
            body: JSON.stringify({
                mode: normalized.toLowerCase(),
                ...(expectedRevision === undefined ? {} : { expectedRevision }),
            }),
        });
        if (!response.ok) {
            return {
                ok: false,
                code: "SAVED_MODE_REJECTED",
                status: response.status,
            };
        }
        const body = await response.json().catch(() => ({}));
        if (body?.success !== true) {
            return { ok: false, code: body?.reason || "SAVED_MODE_REJECTED" };
        }
        return {
            ok: true,
            savedMode: body.savedMode,
            revision: body.savedModeRevision,
        };
    } catch {
        return { ok: false, code: "SAVED_MODE_UNAVAILABLE" };
    }
}, [botStatus?.savedModeRevision]);

// SAVE SETTINGS = the configuration authority boundary. It reads the current
// draft, validates it, and (for LIVE) refreshes the authoritative LIVE account
// context via the existing read-only status path. Only after a successful
// read/validation does it commit the mode to the backend canonical saved-mode
// authority and a new local saved revision. It NEVER starts the runtime, arms
// execution, or creates an order. A failed step leaves the previous saved
// mode/revision untouched.
const handleSaveSettings = useCallback(async () => {
    if (savingSettings) {
        return { ok: false, inProgress: true };
    }
    setSavingSettings(true);
    setSettingsSaveError(null);
    setSettingsSaveNotice(null);
    try {
        const result = await performSaveSettings({
            draft: tradeSettings,
            refreshLiveContext: refreshBotStatus,
        });
        if (!result.ok) {
            const message = {
                INVALID_MODE: "Mode must be PAPER or LIVE.（モードはPAPERまたはLIVEにしてください）",
                INVALID_SYMBOL: "Symbol is required.（シンボルを指定してください）",
                LIVE_ACCOUNT_CONTEXT_UNAVAILABLE: "LIVE account context could not be refreshed. Saved settings were not changed.（LIVEアカウント情報を取得できませんでした。保存済み設定は変更されていません）",
            }[result.code] || "SAVE FAILED（保存に失敗しました）";
            setSettingsSaveError({ code: result.code, message });
            return { ok: false, code: result.code };
        }
        const persisted = await persistSavedMode(tradeSettings.mode);
        if (!persisted.ok) {
            const message = {
                STALE_SAVED_MODE_REVISION: "Saved mode changed in another session. Reload and save again.（別の画面で保存モードが更新されました。再読み込みして保存し直してください）",
                SAVED_MODE_UNAVAILABLE: "Saved mode could not be committed to the backend. Saved settings were not changed.（保存モードをサーバーに確定できませんでした。保存済み設定は変更されていません）",
            }[persisted.code] || "SAVE FAILED（保存に失敗しました）";
            setSettingsSaveError({ code: persisted.code, message });
            return { ok: false, code: persisted.code };
        }
        commitSavedSettings(tradeSettings);
        setSettingsSaveNotice("SETTINGS SAVED");
        await refreshBotStatus();
        return { ok: true };
    } finally {
        setSavingSettings(false);
    }
}, [commitSavedSettings, persistSavedMode, refreshBotStatus, savingSettings, tradeSettings]);

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

                            config={buildBotConfig(tradeSettings, botStatus, runtimeHealth.running)}

                            savedConfig={buildBotConfig(
                                canonicalSavedMode
                                    ? { ...savedSettings, mode: canonicalSavedMode }
                                    : savedSettings,
                                botStatus,
                                runtimeHealth.running,
                            )}

                            settingsDirty={settingsDirty}

                            settingsRevision={settingsRevision}

                            savingSettings={savingSettings}

                            settingsSaveError={settingsSaveError}

                            settingsSaveNotice={settingsSaveNotice}

                            onSaveSettings={handleSaveSettings}

                            liveAccountCapital={liveAccountCapital}

                            liveCapitalAuthority={liveCapitalAuthority}

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

                            controlAuthority={
                                botStatus?.controlAuthority
                                || botStatus?.executionControl?.controlAuthority
                                || "BOT"
                            }

                            controlRevision={
                                botStatus?.controlRevision
                                ?? botStatus?.executionControl?.controlRevision
                                ?? 0
                            }

                            activeSymbol={
                                botStatus?.activeSymbol
                                || botStatus?.symbol
                            }

                            executionMode={
                                botStatus?.executionMode
                                || botStatus?.mode
                            }

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

        </div>

        <TradingDecisionCard
            decision={botStatus?.tradingDecision}
            diagnostics={botStatus?.tradingCycleDiagnostics}
            lastOrderActivity={lastExecutionActivity}
            lastOrderValue={formatActivityTime(lastExecutionActivity.timestamp)}
        />

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
