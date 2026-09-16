import React, {
    useRef,
    useState,
    useEffect,
} from "react";

import {
    updateExecutionRuntimeTelemetry,
} from "../store/telemetryStore";

import {
    runEmergencyOrchestrator,
    setExecutionEnabled,
    unlockEmergency,
} from "../runtime/governanceRuntime";
import {
    API,
} from "../api";
import {
    requestBotStop,
} from "../runtime/botLifecycle";
import {
    authenticatedControlRequest,
    authErrorMessage,
    isAuthErrorStatus,
} from "../features/auth/operatorAuth";
import {
    useMoneyManagement,
} from "../features/money-management/hooks/useMoneyManagement";
import OperationToggle from "./common/OperationToggle";
import OperationPreparation from "./operation/OperationPreparation";
import {
    createOperationPreparationSettings,
    deriveOperationReadiness,
    resolveEffectiveMmConfiguration,
    selectionModeDisplayLabel,
} from "./operation/operationPreparationModel";

const formatLoopError = (
    error,
    requestedEnabled
) => {
    const code = (
        error?.code
        || (
            error?.status
                ? `HTTP_${error.status}`
                : null
        )
        || "LOOP_REQUEST_FAILED"
    );
    const actionText = requestedEnabled
        ? "start Loop"
        : "stop Loop";
    const japaneseActionText = requestedEnabled
        ? "LOOP開始"
        : "LOOP停止";
    const detail = error?.message
        ? ` ${error.message}`
        : "";

    return (
        `Failed to ${actionText}.`
        + `（${japaneseActionText}に失敗しました）`
        + ` [${code}]`
        + detail
    );
};

const getAutoTradeActivity = ({ enabled, emergencyState, runtimeAvailable,
    governance, tradingAction, decision }) => {
    if (!enabled) return { state: "DISABLED", detail: null };
    if (["LOCKED", "PROCESSING", "ACTION_REQUIRED"].includes(emergencyState)) {
        return { state: "ENABLED", detail: "BLOCKED BY EMERGENCY" };
    }
    if (!runtimeAvailable) return { state: "ENABLED", detail: "RUNTIME UNAVAILABLE" };
    if (String(governance?.status).toUpperCase() === "BLOCKED") {
        return { state: "ENABLED", detail: "BLOCKED BY GOVERNANCE" };
    }
    if (/ORDER|PROCESSING|SUBMITTING/.test(String(tradingAction).toUpperCase())) {
        return { state: "ENABLED", detail: "ORDER PROCESSING" };
    }
    if (String(decision).toUpperCase() === "HOLD"
        && String(tradingAction).toUpperCase() === "IDLE_BY_AI_HOLD") {
        return { state: "ENABLED", detail: "WAITING FOR SIGNAL" };
    }
    return { state: "ENABLED", detail: null };
};

const formatAutoTradeError = (
    error
) => {
    const code = (
        error?.code
        || error?.data?.detail?.reason
        || error?.data?.reason
        || "AUTO_TRADE_REQUEST_FAILED"
    );

    if (code === "AUTO_TRADE_REQUIRES_LOOP_ON") {
        return (
            "Loop must be running before Auto Trade can be enabled."
            + "（LOOPを開始してからAUTO TRADEを有効にしてください）"
            + ` [${code}]`
        );
    }

    if (code === "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK") {
        return (
            "Auto Trade cannot be enabled while Emergency Lock is active."
            + "（Emergency Lock中はAUTO TRADEを有効にできません）"
            + ` [${code}]`
        );
    }

    if (code === "NETWORK_ERROR") {
        return (
            "Unable to reach the server."
            + "（サーバーへ接続できません）"
            + ` [${code}]`
        );
    }

    if (error?.status === 409) {
        return (
            "Auto Trade request was rejected."
            + "（AUTO TRADE要求が拒否されました）"
            + ` [${code}]`
        );
    }

    if (
        error?.status >= 500
        || error?.status === null
        || error?.status === undefined
    ) {
        return (
            "Failed to update Auto Trade."
            + "（AUTO TRADEの更新に失敗しました）"
            + ` [${code}]`
        );
    }

    return (
        "Failed to update Auto Trade."
        + "（AUTO TRADEの更新に失敗しました）"
        + ` [${code}]`
    );
};

const formatEmergencyError = (
    error
) => {
    const code = (
        error?.code
        || error?.data?.detail?.reason
        || error?.data?.error_code
        || error?.data?.reason
        || (
            error?.status
                ? `HTTP_${error.status}`
                : null
        )
        || "EMERGENCY_REQUEST_FAILED"
    );
    const detail = error?.message
        ? ` ${error.message}`
        : "";

    if (code === "NETWORK_ERROR") {
        return (
            "Unable to reach the server."
            + "（サーバーへ接続できません）"
            + ` [${code}]`
        );
    }

    if (code === "MALFORMED_RESPONSE") {
        return (
            "Emergency response could not be verified."
            + "（Emergency応答を確認できません）"
            + ` [${code}]`
        );
    }

    if (error?.status === 409) {
        return (
            "Emergency request was rejected."
            + "（Emergency要求が拒否されました）"
            + ` [${code}]`
            + detail
        );
    }

    return (
        "Emergency operation failed."
        + "（緊急処理に失敗しました）"
        + ` [${code}]`
        + detail
    );
};

const formatUnlockError = (
    error
) => {
    const code = (
        error?.code
        || error?.data?.detail?.reason
        || error?.data?.reason
        || (
            error?.status
                ? `HTTP_${error.status}`
                : null
        )
        || "EMERGENCY_UNLOCK_FAILED"
    );

    const messages = {
        PROCESSING: "緊急停止処理中のため解除できません",
        POSITION_REMAINING: "ポジションが残っているため解除できません",
        STATE_UNKNOWN: "取引状態を確認できないため解除できません",
        ACTION_REQUIRED: "手動確認が必要なため解除できません",
        EXECUTION_ENABLED: "自動取引が有効なため解除できません",
        NOT_LOCKED: "緊急ロック状態ではありません",
        NETWORK_ERROR: "サーバーへ接続できません",
        MALFORMED_RESPONSE: "解除応答を確認できません",
        STATUS_REFRESH_FAILED: "解除後の状態を取得できません",
        STATUS_MISMATCH: "解除後の安全状態を確認できません",
    };

    return (
        messages[code]
        || "緊急状態を解除できません"
    ) + ` [${code}]`;
};

const pickEmergencyValue = (
    value,
    ...keys
) => {
    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
        return undefined;
    }

    for (const key of keys) {
        if (
            Object.prototype.hasOwnProperty.call(
                value,
                key,
            )
        ) {
            return value[key];
        }
    }

    return undefined;
};

const normalizeEmergencyState = (
    emergency,
    emergencyLocked,
    emergencyState
) => {
    const state = (
        typeof emergency?.state === "string"
            && emergency.state.trim()
            ? emergency.state.trim().toUpperCase()
            : (
                typeof emergencyState === "string"
                    && emergencyState.trim()
                    ? emergencyState.trim().toUpperCase()
                    : null
            )
    );

    if (
        state === "READY"
        || state === "PROCESSING"
        || state === "LOCKED"
        || state === "ACTION_REQUIRED"
        || state === "FAILED"
        || state === "PARTIAL"
        || state === "STATE_UNKNOWN"
    ) {
        return state;
    }

    if (emergencyLocked === true || emergency?.locked === true) {
        return "LOCKED";
    }

    if (
        emergencyLocked === false
        || emergency?.locked === false
        || state === "UNLOCKED"
    ) {
        return "READY";
    }

    return "STATE_UNKNOWN";
};

const formatEmergencyTimestamp = (
    value
) => {
    if (!value) {
        return null;
    }

    return String(value).replace("T", " ").replace("Z", " UTC");
};

export default function BotControl({

    config,

    executionEnabled,

    botRunning,

    loopEnabled,

    loopState,

    emergencyLocked,

    emergencyState,

    emergency,

    pendingOrder,

    position,

    controlAuthority,

    controlRevision,

    activeSymbol,

    executionMode,

    runtimeHealth,

    onStatusRefresh,

    setExecutionEnabledState,

    onLegacyConfigChange,

}){

    const [, forceUpdate] =
        useState(0);
    const [
        loopPending,
        setLoopPending,
    ] = useState(false);
    const [botPending, setBotPending] = useState(false);
    const [armPending, setArmPending] = useState(false);
    const [botError, setBotError] = useState(null);
    const [, setLoopPendingAction] = useState(null);
    const [
        loopError,
        setLoopError,
    ] = useState(null);
    const [
        autoTradePending,
        setAutoTradePending,
    ] = useState(false);
    const [
        autoTradeError,
        setAutoTradeError,
    ] = useState(null);
    const [
        controlPending,
        setControlPending,
    ] = useState(false);
    const [
        controlError,
        setControlError,
    ] = useState(null);
    const [
        manualTradePending,
        setManualTradePending,
    ] = useState(false);
    const [
        manualTradeError,
        setManualTradeError,
    ] = useState(null);
    const [
        emergencyPending,
        setEmergencyPending,
    ] = useState(false);
    const [
        emergencyError,
        setEmergencyError,
    ] = useState(null);
    const [
        emergencyConfirmOpen,
        setEmergencyConfirmOpen,
    ] = useState(false);
    const [
        liveConfirmOpen,
        setLiveConfirmOpen,
    ] = useState(false);
    const [
        unlockPending,
        setUnlockPending,
    ] = useState(false);
    const [
        unlockError,
        setUnlockError,
    ] = useState(null);
    const [, setUnlockNotice] = useState(null);
    const loopPendingRef =
        useRef(false);
    const botPendingRef = useRef(false);
    const autoTradePendingRef =
        useRef(false);
    const controlPendingRef =
        useRef(false);
    const manualTradePendingRef =
        useRef(false);
    const armPendingRef = useRef(false);
    const emergencyPendingRef =
        useRef(false);
    const unlockPendingRef =
        useRef(false);
    const {
        status: mmStatus,
        configuration: mmConfiguration,
        configurationDraft: mmDraft,
        configurationDraftInvalid: mmDraftInvalid,
        isUpdatingConfiguration: mmUpdating,
        isInitialLoading: mmLoading,
        configurationError: mmConfigurationError,
        updateError: mmUpdateError,
        configurationConflict: mmConflict,
        updateConfigurationDraft,
        saveConfiguration,
        resetConfigurationDraft,
    } = useMoneyManagement();
    const lifecycleState = mmStatus?.lifecycleState;
    const capitalAuthorityStatus = mmStatus?.capitalAuthorityStatus;
    const availableCapital = mmStatus?.capitalEligibility?.availableCapital;
    const capitalBasis = mmStatus?.capitalEligibility?.capitalBasis;
    const riskBudget = mmStatus?.capitalEligibility?.riskBudget;
    const executionEntryAllowed = mmStatus?.executionEntryAllowed;
    const recommendedAction = mmStatus?.recommendedAction;
    const riskState = mmStatus?.riskState;
    const mmBlockReasons = mmStatus?.blockReasons ?? [];
    const mmRecoveryRequired = mmStatus?.recoveryRequired === true;

    const handleMmDraftChange = (patch) => updateConfigurationDraft(patch);
    const handleMmSave = () => saveConfiguration();
    const handleMmReset = () => resetConfigurationDraft();

    /* =======================================================
       STATUS
    const emergencyPendingRef =
        useRef(false);
    const unlockPendingRef =
        useRef(false);

    /* =======================================================
       STATUS
    ======================================================= */

    const autoTradeChecked =
        executionEnabled === true;
    const loopChecked = (
        typeof loopEnabled === "boolean"
            ? loopEnabled
            : botRunning === true
    );
    const loopStateText = (
        loopState
            ? String(loopState).toUpperCase()
            : (
                loopChecked
                    ? "RUNNING"
                    : "STOPPED"
            )
    );
    const loopStateTone = (
        loopStateText === "RUNNING"
            ? "running"
            : (
                loopStateText === "STARTING"
                || loopStateText === "STOPPING"
            )
                ? "pending"
                : "stopped"
    );
    const emergencyStatus = (
        emergency
        && typeof emergency === "object"
        && !Array.isArray(emergency)
            ? emergency
            : null
    );
    const emergencyStateCode = normalizeEmergencyState(
        emergencyStatus,
        emergencyLocked,
        emergencyState,
    );
    const autoTradeActivity = getAutoTradeActivity({
        enabled: autoTradeChecked,
        emergencyState: emergencyStateCode,
        runtimeAvailable: runtimeHealth?.snapshotPresent !== false,
        governance: runtimeHealth?.governance,
        tradingAction: runtimeHealth?.tradingAction?.status,
        decision: runtimeHealth?.tradingAction?.decision,
    });
    const autoTradeStateText = autoTradeActivity.state;
    const lastEmergencyResult = (
        emergencyStatus?.lastResult
        && typeof emergencyStatus.lastResult === "object"
            ? emergencyStatus.lastResult
            : null
    );
    const emergencyIsLocked = (
        typeof emergencyStatus?.locked === "boolean"
            ? emergencyStatus.locked
            : emergencyStateCode === "LOCKED"
    );
    const emergencyBlocksOperations = (
        emergencyStateCode === "PROCESSING"
        || emergencyStateCode === "LOCKED"
        || emergencyStateCode === "ACTION_REQUIRED"
    );
    const positionRemaining = pickEmergencyValue(
        lastEmergencyResult,
        "positionRemaining",
        "position_remaining",
    );
    const stateUnknown = pickEmergencyValue(
        lastEmergencyResult,
        "stateUnknown",
        "state_unknown",
    );
    const cancelResult = pickEmergencyValue(
        lastEmergencyResult,
        "cancelResult",
        "cancel_result",
        "cancel",
    );
    const flattenResult = pickEmergencyValue(
        lastEmergencyResult,
        "flattenResult",
        "flatten_result",
        "flatten",
    );
    const completedAt = formatEmergencyTimestamp(
        pickEmergencyValue(
            lastEmergencyResult,
            "completedAt",
            "completed_at",
        )
    );
    const emergencyPath = pickEmergencyValue(
        lastEmergencyResult,
        "path",
        "execution_path",
    );
    const emergencyResultCode = String(
        pickEmergencyValue(
            lastEmergencyResult,
            "result",
        ) || ""
    ).toUpperCase();
    const cancelCompleted = (
        cancelResult
        && typeof cancelResult === "object"
        && (
            cancelResult.completed === true
            || cancelResult.success === true
            || cancelResult.status === "COMPLETED"
        )
    );
    const cancelFailed = (
        cancelResult
        && typeof cancelResult === "object"
        && (
            cancelResult.success === false
            || cancelResult.completed === false
            || cancelResult.status === "FAILED"
        )
    );
    const rawOrdersCancelled = pickEmergencyValue(
        cancelResult,
        "orders_cancelled",
        "ordersCancelled",
    );
    const ordersCancelled = (
        rawOrdersCancelled !== null
        && rawOrdersCancelled !== undefined
            ? Number(rawOrdersCancelled)
            : NaN
    );
    const flattenCompleted = (
        flattenResult
        && typeof flattenResult === "object"
        && (
            flattenResult.completed === true
            || flattenResult.success === true
            || flattenResult.status === "COMPLETED"
        )
    );
    const flattenFailed = (
        flattenResult
        && typeof flattenResult === "object"
        && (
            flattenResult.success === false
            || flattenResult.completed === false
            || flattenResult.status === "FAILED"
        )
    );
    const positionClosed = (
        flattenResult
        && typeof flattenResult === "object"
        && (
            flattenResult.position_closed === true
            || flattenResult.positionClosed === true
        )
    );
    const lockedFacts = [];

    if (loopChecked === false || loopStateText === "STOPPED") {
        lockedFacts.push("BOT STOPPED");
    }

    if (autoTradeChecked === false) {
        lockedFacts.push("EXECUTION DISABLED");
    }

    if (cancelCompleted && Number.isFinite(ordersCancelled)) {
        lockedFacts.push(
            ordersCancelled > 0
                ? "OPEN ORDERS CANCELLED"
                : "OPEN ORDERS NONE"
        );
    }

    if (flattenCompleted && positionClosed) {
        lockedFacts.push("POSITION CLOSED");
    }

    if (completedAt) {
        lockedFacts.push(`COMPLETED AT ${completedAt}`);
    }

    const actionWarnings = [];

    if (positionRemaining === true) {
        actionWarnings.push("POSITION REMAINING");
    }

    if (stateUnknown === true) {
        actionWarnings.push("STATE UNKNOWN");
    }

    if (cancelFailed) {
        actionWarnings.push("CANCEL FAILED");
    }

    if (flattenFailed) {
        actionWarnings.push("FLATTEN FAILED");
    }

    if (
        actionWarnings.length === 0
        && emergencyResultCode
        && emergencyResultCode !== "SUCCESS"
    ) {
        actionWarnings.push(emergencyResultCode);
    }

    const lastResultMessage = pickEmergencyValue(
        lastEmergencyResult,
        "message",
    );
    const emergencyOperationGuardReason = (
        emergencyBlocksOperations
            ? (
                "Emergency state blocks this operation."
                + "（Emergency状態のため操作できません）"
            )
            : null
    );
    const autoTradeDisabledReason = (
        emergencyOperationGuardReason
            ? emergencyOperationGuardReason
            : !autoTradeChecked && loopEnabled === false
                ? (
                    "Loop must be running before Auto Trade can be enabled."
                    + "（LOOPを開始してからAUTO TRADEを有効にしてください）"
                )
                : null
    );
    const autoTradeDisabled =
        autoTradePending
        || emergencyBlocksOperations
        || Boolean(autoTradeDisabledReason);
    const liveOrderEntryArmed = (
        config?.liveOrderEntryAllowed === true
        && config?.realOrderAllowed === true
        && config?.executionEntryAllowed === true
    );
    const armDisabled = (
        armPending
        || botRunning !== true
        || String(config?.mode || "").toUpperCase() !== "LIVE"
        || emergencyBlocksOperations
    );
    const loopDisabled = (
        loopPending
        || botRunning !== true
        || emergencyBlocksOperations
        || (String(config?.mode || "").toUpperCase() === "LIVE"
            && !liveOrderEntryArmed
            && !loopChecked)
    );
    const unlockAllowed = (
        emergencyStateCode !== "READY"
        && emergencyStateCode !== "PROCESSING"
        && unlockPending !== true
    );
    const emergencyButtonDisabled = (
        emergencyPending
        || emergencyConfirmOpen
        || unlockPending
        || emergencyStateCode !== "READY"
    );
    const emergencyLockValue = (
        emergencyIsLocked
            ? (
                emergencyStateCode === "ACTION_REQUIRED"
                    ? "ACTION REQUIRED"
                    : "LOCKED"
            )
            : "UNLOCKED"
    );
    const emergencyLockClass = (
        emergencyStateCode === "LOCKED"
            ? "locked"
            : emergencyStateCode === "READY"
                ? "unlocked"
                : "unknown"
    );

    const startSettings = createOperationPreparationSettings(config);
    // WF: Final Preparation must stay authoritative even when the one-shot
    // standalone configuration request has not populated mmConfiguration.
    // The polled money-management status carries the SAME normalized
    // configuration (mmStatus.configuration), so it is used as the fallback.
    // Both sources already share the normalized frontend contract.
    const effectiveMmConfiguration = resolveEffectiveMmConfiguration(
        mmConfiguration,
        mmStatus?.configuration,
    );
    const effectiveSelectionMode = startSettings.selectionMode;
    const effectiveStartSymbol = effectiveSelectionMode === "AUTO"
        ? config?.displaySymbol
        : startSettings.manualSymbol;
    const startReadiness = deriveOperationReadiness({
        botRunning,
        tradingMode: startSettings.tradingMode,
        dryRun: startSettings.tradingMode === "PAPER",
        selectionMode: effectiveSelectionMode,
        autoMarketState: config?.autoMarketState,
        displaySymbol: config?.displaySymbol,
        emergencyState: emergencyStateCode,
        position,
        pendingOrder,
        governanceStatus: runtimeHealth?.governance?.status,
        realOrderAllowed: config?.realOrderAllowed === true,
        allowLive: config?.allowLive,
        tradeMode: config?.tradeMode,
        executionEnabled,
        executionEntryAllowed,
        recommendedAction,
        riskState,
        requestedLeverage: startSettings.requestedLeverage,
        maximumLeverage: effectiveMmConfiguration?.maximumLeverage,
        mmConfiguration: effectiveMmConfiguration,
        mmBlockReasons: mmStatus?.blockReasons || [],
        mmRecoveryRequired: mmStatus?.recoveryRequired || false,
        mmConfigurationError: Boolean(mmConfigurationError),
        paperBootstrapEligible: config?.paperBootstrapEligible,
        loopOnStart: startSettings.loopOnStart,
        autoTradeOnStart: startSettings.autoTradeOnStart,
    });
    const { startReady } = startReadiness;
    const startRiskPercent = Number(effectiveMmConfiguration?.riskPerTradePercent);
    const startRiskAvailable = (
        Number.isFinite(startRiskPercent)
        && startRiskPercent > 0
    );
    const startMaxDrawdownPercent = Number(
        effectiveMmConfiguration?.maximumDrawdownPercent,
    );
    const startMaxDrawdownAvailable = (
        Number.isFinite(startMaxDrawdownPercent)
        && startMaxDrawdownPercent > 0
    );
    const isLiveMode = startSettings?.tradingMode === "LIVE";
    // Problem 1/9: an invalid MM draft must never become authoritative and
    // must not be silently ignored. START fails closed while the draft cannot
    // be safely reconciled/persisted.
    const startConfigSafe = startReady === true && mmDraftInvalid !== true;
    const paperStartAllowed = !botRunning && !botPending && !isLiveMode && startConfigSafe;
    const liveStartTriggerAllowed = !botRunning && !botPending && isLiveMode && !liveConfirmOpen;
    const liveConfirmAllowed = (
        !botRunning
        && !botPending
        && isLiveMode
        && startConfigSafe
        && startRiskAvailable
        && startMaxDrawdownAvailable
        && !emergencyBlocksOperations
        && emergencyStateCode === "READY"
    );
    const liveReadinessDetails = [
        ["EMERGENCY", startReadiness.emergencyReadiness],
        ["POSITION", startReadiness.positionState],
        ["PENDING ORDER", startReadiness.orderAuthority],
        ["MARKET SELECTION", startReadiness.selectionReadiness],
        ["MONEY MANAGEMENT", startReadiness.mmReadiness],
        ["GOVERNANCE", startReadiness.governanceReadiness],
        ["EXECUTION", startReadiness.executionReadiness],
        ["LEVERAGE", startReadiness.leverageReadiness],
        ["LIVE AUTHORITY", startReadiness.liveAuthorityReadiness],
    ];
    const liveBlockReasons = [
        ...liveReadinessDetails
            .filter(([, value]) => !["READY", "SAFE", "NOT_RELEVANT"].includes(value))
            .map(([label, value]) => `${label}: ${value}`),
        ...mmBlockReasons,
        ...(!startRiskAvailable ? ["MM_RISK_PER_TRADE_UNAVAILABLE"] : []),
        ...(!startMaxDrawdownAvailable ? ["MM_MAXIMUM_DRAWDOWN_UNAVAILABLE"] : []),
    ].filter((reason, index, reasons) => reasons.indexOf(reason) === index);

    useEffect(() => {
        if (!liveConfirmOpen) {
            return;
        }

        if (startSettings?.tradingMode !== "LIVE") {
            setLiveConfirmOpen(false);
            return;
        }

        if (botRunning) {
            setLiveConfirmOpen(false);
            return;
        }
    }, [startSettings?.tradingMode, botRunning, liveConfirmOpen, setLiveConfirmOpen]);

    const refreshStatusSafely = async () => {
        if (typeof onStatusRefresh !== "function") {
            return;
        }

        try {
            await onStatusRefresh();
        } catch (error) {
            console.error("BOT STATUS REFRESH ERROR", error);
        }
    };

    const handleBotLifecycle = async () => {
        if (botPendingRef.current) return;
        if (botRunning) {
            await executeBotStop();
            return;
        }
        if (isLiveMode) {
            openLiveConfirm();
            return;
        }
        if (!paperStartAllowed) return;
        if (!startRiskAvailable) {
            setBotError("START failed: authoritative Money Management risk-per-trade is unavailable.");
            return;
        }
        if (!startMaxDrawdownAvailable) {
            setBotError("START failed: authoritative Money Management maximum drawdown is unavailable.");
            return;
        }
        await executeBotStart();
    };

    const executeBotStop = async () => {
        botPendingRef.current = true;
        setBotPending(true);
        setBotError(null);

        try {
            const response = await authenticatedControlRequest(API.botStop(), {
                method: "POST",
            });
            const result = await response.json().catch(() => null);

            const lifecycleConfirmed = result?.status === "stopped" && result?.success === true;

            if (!response.ok) {
                if (isAuthErrorStatus(response.status)) {
                    throw new Error(authErrorMessage(response.status));
                }
                throw new Error(result?.reason || result?.detail || "BOT STOP request was rejected.");
            }
            if (!lifecycleConfirmed) {
                throw new Error(result?.reason || result?.detail || "BOT STOP request was rejected.");
            }

            await refreshStatusSafely();
        } catch (error) {
            setBotError(`STOP failed: ${error?.message || "UNKNOWN ERROR"}`);
        } finally {
            botPendingRef.current = false;
            setBotPending(false);
        }
    };

    const executeBotStart = async () => {
        botPendingRef.current = true;
        setBotPending(true);
        setBotError(null);
        setLoopError(null);
        setAutoTradeError(null);

        let riskPercentValue = startRiskPercent;
        let maxDrawdownValue = startMaxDrawdownPercent;
        try {
            // Problem 1/9: flush any pending VALID MM draft so the START
            // payload uses the authoritative saved configuration the user
            // sees in Final Preparation. An invalid draft is never sent;
            // START fails closed rather than diverging from the saved config.
            const authoritativeConfig = effectiveMmConfiguration;
            if (mmDraft && authoritativeConfig) {
                const mmFieldsDirty = (
                    String(mmDraft.riskPerTradePercent)
                    !== String(authoritativeConfig.riskPerTradePercent)
                    || String(mmDraft.maximumDrawdownPercent)
                    !== String(authoritativeConfig.maximumDrawdownPercent)
                );
                if (
                    mmFieldsDirty
                    && !mmDraftInvalid
                    && typeof saveConfiguration === "function"
                ) {
                    const saveResult = await handleMmSave();
                    if (saveResult?.result?.configuration) {
                        const fresh = saveResult.result.configuration;
                        riskPercentValue = Number(fresh.riskPerTradePercent);
                        maxDrawdownValue = Number(fresh.maximumDrawdownPercent);
                    } else if (saveResult?.ok === false && !saveResult?.inProgress) {
                        // A genuine persistence failure: START must not
                        // silently diverge from the authoritative config.
                        setBotError("START failed: authoritative Money Management configuration could not be persisted.");
                        botPendingRef.current = false;
                        setBotPending(false);
                        return;
                    }
                    // in-progress: fall back to the current authoritative saved
                    // configuration already captured above (safe, non-divergent).
                }
            }

            const response = await authenticatedControlRequest(API.botStart(), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    symbol: effectiveStartSymbol,
                    selection_mode: startSettings.selectionMode,
                    exchange: String(config?.exchange || "KUCOIN").toLowerCase(),
                    risk_percent: riskPercentValue,
                    position_size: config?.positionSize ?? 0,
                    max_drawdown_pct: maxDrawdownValue,
                    sl_percent: config?.sl ?? 1,
                    leverage: startSettings.requestedLeverage,
                    timeframe: config?.timeframe || "1m",
                    tp_percent: config?.tp ?? 2,
                    trailing_stop: config?.trailing === true,
                    dry_run: startSettings.tradingMode === "PAPER",
                    mode: startSettings.tradingMode.toLowerCase(),
                    loop_on_start: isLiveMode ? false : startSettings.loopOnStart,
                    auto_trade_on_start: isLiveMode ? false : startSettings.autoTradeOnStart,
                }),
            });
            const result = await response.json().catch(() => null);

            const lifecycleConfirmed = result?.status === "started";

            if (!response.ok) {
                if (isAuthErrorStatus(response.status)) {
                    throw new Error(authErrorMessage(response.status));
                }
                throw new Error(result?.reason || result?.detail || "BOT lifecycle request was rejected.");
            }
            if (!lifecycleConfirmed) {
                throw new Error(result?.reason || result?.detail || "BOT lifecycle request was rejected.");
            }

            // LIVE confirmation authorizes START only. Order-entry ARM, Loop,
            // and Auto Trade remain separate authenticated operator actions.
            // The refreshed backend snapshot is the sole authority for the
            // resulting RUNNING / DISARMED UI state.

            if (result?.loopState === "RUNNING") {
                setLoopError(null);
            }
            if (result?.autoTradeEnabled === true) {
                updateExecutionRuntimeTelemetry({
                    executionAllowed: true,
                    governanceReason: "START_AUTO_TRADE_ENABLE",
                    suppressionReason: "NONE",
                });
                setExecutionEnabledState(true);
            }

            await refreshStatusSafely();
        } catch (error) {
            setBotError(`START failed: ${error?.message || "UNKNOWN ERROR"}`);
        } finally {
            botPendingRef.current = false;
            setBotPending(false);
        }
    };

    const startLoop = async () => {
        const response =
            await authenticatedControlRequest(
                API.loopStart(),
                {
                    method: "POST",
                }
            );

        if (!response.ok) {
            if (isAuthErrorStatus(response.status)) {
                const error = new Error(
                    authErrorMessage(response.status)
                );
                error.status = response.status;
                throw error;
            }
            const text =
                await response.text();

            console.error(
                "BOT START RESPONSE",
                text
            );

            const error = new Error(
                text
            );
            error.status = response.status;

            throw error;
        }

        let result;

        try {
            result = await response.json();
        } catch (error) {
            const parseError = new Error(
                "Loop start response was not valid JSON."
            );
            parseError.code = "MALFORMED_RESPONSE";
            parseError.cause = error;

            throw parseError;
        }

        if (result?.status !== "started") {
            const error = new Error(
                result?.reason
                || "Loop start did not confirm started status."
            );
            error.code = result?.status
                || "START_NOT_CONFIRMED";
            error.data = result;

            throw error;
        }

        console.log(
            "START RESULT",
            result
        );

        forceUpdate(
            v => v + 1
        );

        return result;
    };

    const stopLoop = async () => {
        console.log(
            "STOP BUTTON CLICKED"
        );

        const result = await requestBotStop({
            endpoint: API.loopStop(),
        });

        if (result?.status !== "stopped") {
            const error = new Error(
                result?.reason
                || "Loop stop did not confirm stopped status."
            );
            error.code = result?.status
                || "STOP_NOT_CONFIRMED";
            error.data = result;

            throw error;
        }

        console.log(
            "STOP RESULT",
            result
        );

        forceUpdate(v => v + 1);

        return result;
    };

    const handleLiveOrderEntryChange = async (nextArmed) => {
        if (armPendingRef.current || armDisabled) return;

        armPendingRef.current = true;
        setArmPending(true);
        setBotError(null);
        try {
            const response = await authenticatedControlRequest(
                nextArmed ? API.liveOrderEntryArm() : API.liveOrderEntryDisarm(),
                { method: "POST" },
            );
            const result = await response.json().catch(() => null);
            if (!response.ok) {
                if (isAuthErrorStatus(response.status)) {
                    throw new Error(authErrorMessage(response.status));
                }
                const detail = result && result.detail;
                throw new Error(
                    (result && result.reason)
                    || (detail && detail.reason)
                    || detail
                    || "LIVE order-entry authority was rejected."
                );
            }
            if (!result || result.success !== true || result.armed !== nextArmed) {
                throw new Error("LIVE order-entry authority was not confirmed.");
            }
            await refreshStatusSafely();
        } catch (error) {
            const message = error && error.message ? error.message : "UNKNOWN ERROR";
            setBotError("ARM failed: " + message);
        } finally {
            armPendingRef.current = false;
            setArmPending(false);
        }
    };

    const handleLoopChange = async (
        nextEnabled
    ) => {
        if (
            loopPendingRef.current
            || emergencyBlocksOperations
        ) {
            return;
        }

        loopPendingRef.current = true;
        setLoopPending(true);
        setLoopPendingAction(
            nextEnabled
                ? "STARTING"
                : "STOPPING"
        );
        setLoopError(null);

        try {
            if (nextEnabled) {
                await startLoop();
            } else {
                await stopLoop();
            }

            setLoopError(null);
        } catch (error) {
            console.error(
                "LOOP TOGGLE ERROR",
                error
            );
            setLoopError(
                formatLoopError(
                    error,
                    nextEnabled
                )
            );
        } finally {
            loopPendingRef.current = false;
            setLoopPending(false);
            setLoopPendingAction(null);
        }
    };

    const handleAutoTradeChange = async (
        nextEnabled
    ) => {
        if (
            autoTradePendingRef.current
            || emergencyBlocksOperations
        ) {
            return;
        }

        autoTradePendingRef.current = true;
        setAutoTradePending(true);
        setAutoTradeError(null);

        try {
            const result = await setExecutionEnabled(nextEnabled);

            if (result.execution_enabled !== nextEnabled) {
                const error = new Error(
                    "Governance response did not match requested Auto Trade state."
                );
                error.code = "AUTO_TRADE_STATE_MISMATCH";
                error.status = 200;
                error.data = result;

                throw error;
            }

            updateExecutionRuntimeTelemetry({
                executionAllowed: result.execution_enabled,
                governanceReason: result.execution_enabled
                    ? "MANUAL_EXECUTION_ENABLE"
                    : "MANUAL_EXECUTION_DISABLE",
                suppressionReason: result.execution_enabled
                    ? "NONE"
                    : "EXECUTION_DISABLED",
            });

            console.log("EXECUTION AUTHORITY RESULT", result);

            setExecutionEnabledState(result.execution_enabled);
            setAutoTradeError(null);
        } catch (error) {
            console.error("EXECUTION AUTHORITY ERROR", error);
            setAutoTradeError(
                formatAutoTradeError(error)
            );
        } finally {
            autoTradePendingRef.current = false;
            setAutoTradePending(false);
        }
    };

    const controlAuthorityValue = String(
        controlAuthority || "BOT"
    ).trim().toUpperCase();

    // The manual-trade stale-intent guard compares against the canonical
    // manual execution mode (paper / live) resolved by the backend from the
    // selected bot mode and the dry-run switch. `tradeMode` is only the
    // process-wide environment capability, never the destination, so it must
    // not be sent as the mode. The UI execution label (SIMULATION / REAL) is
    // presentation only as well.
    const manualExpectedMode = (() => {
        const selected = String(
            config?.selectedMode || ""
        ).trim().toLowerCase();
        if (selected === "paper" || selected === "live") {
            return selected;
        }
        const execution = String(
            config?.executionMode || executionMode || ""
        ).trim().toUpperCase();
        if (execution === "LIVE") {
            return "live";
        }
        if (execution === "SIMULATION") {
            return "paper";
        }
        const fallback = String(config?.tradeMode || "").trim().toLowerCase();
        return fallback === "paper" || fallback === "live"
            ? fallback
            : undefined;
    })();

    const handleExecutionControlChange = async (
        nextAuthority
    ) => {
        const normalized = String(
            nextAuthority || ""
        ).trim().toUpperCase();

        if (
            controlPendingRef.current
            || normalized === controlAuthorityValue
            || (normalized !== "BOT" && normalized !== "MANUAL")
        ) {
            return;
        }

        controlPendingRef.current = true;
        setControlPending(true);
        setControlError(null);

        try {
            const response = await authenticatedControlRequest(
                API.botControl(),
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        authority: normalized,
                        expectedRevision: Number.isInteger(controlRevision)
                            ? controlRevision
                            : undefined,
                    }),
                }
            );

            const data = await response.json().catch(() => null);

            if (!response.ok || !data || data.success !== true) {
                const code = (
                    data?.detail?.reason
                    || data?.reason
                    || `HTTP_${response.status}`
                );
                const error = new Error(code);
                error.code = code;
                error.status = response.status;
                error.data = data;
                throw error;
            }

            if (data.controlAuthority !== normalized) {
                const error = new Error(
                    "CONTROL_AUTHORITY_STATE_MISMATCH"
                );
                error.code = "CONTROL_AUTHORITY_STATE_MISMATCH";
                error.status = 200;
                error.data = data;
                throw error;
            }

            if (typeof data.execution_enabled === "boolean") {
                setExecutionEnabledState(data.execution_enabled);
            }

            setControlError(null);
        } catch (error) {
            if (isAuthErrorStatus(error?.status)) {
                setControlError(authErrorMessage(error.status));
            } else {
                setControlError(
                    error?.message
                    || "Execution control switch failed."
                );
            }
        } finally {
            controlPendingRef.current = false;
            setControlPending(false);

            if (typeof onStatusRefresh === "function") {
                onStatusRefresh();
            }
        }
    };

    const handleManualTrade = async (action) => {
        const normalized = String(
            action || ""
        ).trim().toUpperCase();

        if (
            manualTradePendingRef.current
            || (normalized !== "BUY" && normalized !== "SELL")
            || controlAuthorityValue !== "MANUAL"
        ) {
            return;
        }

        manualTradePendingRef.current = true;
        setManualTradePending(true);
        setManualTradeError(null);

        try {
            const positionId = (
                position?.position_id
                || position?.order_id
                || undefined
            );

            const response = await authenticatedControlRequest(
                API.botManualTrade(),
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        action: normalized,
                        requestId: [
                            "manual",
                            Date.now(),
                            Math.random().toString(36).slice(2, 10),
                        ].join("-"),
                        expectedControlRevision: (
                            Number.isInteger(controlRevision)
                                ? controlRevision
                                : undefined
                        ),
                        expectedSymbol: activeSymbol || undefined,
                        expectedMode: manualExpectedMode,
                        expectedPositionId: positionId,
                    }),
                }
            );

            const data = await response.json().catch(() => null);

            if (!response.ok || !data || data.success !== true) {
                const code = (
                    data?.detail?.reason
                    || data?.reason
                    || `HTTP_${response.status}`
                );
                const error = new Error(code);
                error.code = code;
                error.status = response.status;
                error.data = data;
                throw error;
            }

            // No optimistic position update: the authoritative status refresh
            // below is the only source of the new position state.
            setManualTradeError(null);
        } catch (error) {
            if (isAuthErrorStatus(error?.status)) {
                setManualTradeError(authErrorMessage(error.status));
            } else {
                setManualTradeError(
                    error?.message
                    || "Manual trade failed."
                );
            }
        } finally {
            manualTradePendingRef.current = false;
            setManualTradePending(false);

            if (typeof onStatusRefresh === "function") {
                onStatusRefresh();
            }
        }
    };


    const openEmergencyConfirm = () => {
        if (
            emergencyPendingRef.current
            || emergencyConfirmOpen
            || emergencyStateCode !== "READY"
        ) {
            return;
        }

        setEmergencyConfirmOpen(true);
    };

    const cancelEmergencyConfirm = () => {
        if (emergencyPendingRef.current) {
            return;
        }

        setEmergencyConfirmOpen(false);
    };

    const openLiveConfirm = () => {
        if (botPendingRef.current || botRunning || !isLiveMode || liveConfirmOpen) {
            return;
        }

        setLiveConfirmOpen(true);
    };

    const cancelLiveConfirm = () => {
        if (botPendingRef.current) {
            return;
        }

        setLiveConfirmOpen(false);
    };

    const confirmLiveStart = async () => {
        if (botPendingRef.current) {
            return;
        }

        if (!liveConfirmAllowed) {
            return;
        }

        setLiveConfirmOpen(false);
        await executeBotStart();
    };

    const confirmEmergency = async () => {
        if (emergencyPendingRef.current) {
            return;
        }

        emergencyPendingRef.current = true;
        setEmergencyPending(true);
        setEmergencyError(null);
        setUnlockError(null);
        setUnlockNotice(null);

        try {
            await runEmergencyOrchestrator();

            setEmergencyConfirmOpen(false);
        } catch (error) {
            console.error("EMERGENCY ORCHESTRATOR ERROR", error);
            setEmergencyError(
                formatEmergencyError(error)
            );
            setEmergencyConfirmOpen(false);
        } finally {
            await refreshStatusSafely();
            emergencyPendingRef.current = false;
            setEmergencyPending(false);
        }
    };

    const handleReturnToNormal = async () => {
        if (
            unlockPendingRef.current
            || !unlockAllowed
        ) {
            return;
        }

        unlockPendingRef.current = true;
        setUnlockPending(true);
        setUnlockError(null);
        setEmergencyError(null);
        setUnlockNotice(null);
        let statusRefreshed = false;

        try {
            await unlockEmergency();

            if (typeof onStatusRefresh !== "function") {
                const error = new Error("Status refresh is unavailable.");
                error.code = "STATUS_REFRESH_FAILED";
                throw error;
            }

            const status = await onStatusRefresh();
            statusRefreshed = true;
            if (
                !status
                || status.emergencyLocked !== false
                || status.emergencyState !== "READY"
                || status.loopEnabled !== false
                || status.autoTradeEnabled !== false
                || status.executionEnabled !== false
            ) {
                const error = new Error("Return status could not be verified.");
                error.code = "STATUS_MISMATCH";
                throw error;
            }

            setUnlockNotice(
                "緊急状態は解除されました。"
            );
        } catch (error) {
            console.error("EMERGENCY UNLOCK ERROR", error);
            setUnlockError(
                formatUnlockError(error)
            );
        } finally {
            if (!statusRefreshed) {
                await refreshStatusSafely();
            }
            unlockPendingRef.current = false;
            setUnlockPending(false);
        }
    };

    /* =======================================================
       UI
    ======================================================= */


    return (

        <div className="terminal-panel operation-console">

            <OperationPreparation
                botRunning={botRunning}
                config={config}
                emergencyState={emergencyStateCode}
                lockedFacts={lockedFacts}
                actionWarnings={actionWarnings}
                emergencyPath={emergencyPath}
                emergencyError={emergencyError}
                unlockError={unlockError}
                lastResultMessage={lastResultMessage}
                emergencyLocked={emergencyIsLocked}
                emergencyConfirmOpen={emergencyConfirmOpen}
                emergencyPending={emergencyPending}
                unlockPending={unlockPending}
                unlockAllowed={unlockAllowed}
                emergencyButtonDisabled={emergencyButtonDisabled}
                emergencyLockValue={emergencyLockValue}
                emergencyLockClass={emergencyLockClass}
                openEmergencyConfirm={openEmergencyConfirm}
                cancelEmergencyConfirm={cancelEmergencyConfirm}
                confirmEmergency={confirmEmergency}
                handleReturnToNormal={handleReturnToNormal}
                executionEnabled={executionEnabled}
                governanceStatus={runtimeHealth?.governance?.status}
                onLegacyConfigChange={onLegacyConfigChange}
                pendingOrder={pendingOrder}
                position={position}
                realOrderAllowed={config?.realOrderAllowed === true}
                liveOrderEntryArmed={liveOrderEntryArmed}
                armDisabled={armDisabled}
                handleLiveOrderEntryChange={handleLiveOrderEntryChange}
                loopChecked={loopChecked}
                loopState={loopStateText}
                loopStateTone={loopStateTone}
                loopPending={loopPending}
                loopDisabled={loopDisabled}
                handleLoopChange={handleLoopChange}
                autoTradeChecked={autoTradeChecked}
                autoTradeStateText={autoTradeStateText}
                autoTradeDisabled={autoTradeDisabled}
                autoTradePending={autoTradePending}
                handleAutoTradeChange={handleAutoTradeChange}
                controlAuthority={controlAuthorityValue}
                controlRevision={controlRevision}
                controlPending={controlPending}
                controlError={controlError}
                handleExecutionControlChange={handleExecutionControlChange}
                manualTradePending={manualTradePending}
                manualTradeError={manualTradeError}
                handleManualTrade={handleManualTrade}
                activeSymbol={activeSymbol}
                mmDraft={mmDraft}
                mmConfiguration={effectiveMmConfiguration}
                mmDraftInvalid={mmDraftInvalid}
                capitalBasis={capitalBasis}
                leverageAuthority={config?.leverageAuthority}
                mmUpdating={mmUpdating}
                mmLoading={mmLoading}
                mmConfigurationError={mmConfigurationError}
                mmUpdateError={mmUpdateError}
                mmConflict={mmConflict}
                onMmDraftChange={handleMmDraftChange}
                onMmSave={handleMmSave}
                onMmReset={handleMmReset}
                mmRuntime={lifecycleState || "UNKNOWN"}
                lifecycleState={lifecycleState}
                capitalAuthorityStatus={capitalAuthorityStatus}
                availableCapital={availableCapital}
                riskBudget={riskBudget}
                executionEntryAllowed={executionEntryAllowed}
                recommendedAction={recommendedAction}
                riskState={riskState}
                mmBlockReasons={mmBlockReasons}
                mmRecoveryRequired={mmRecoveryRequired}
            >
                <div className="operation-prep-existing-start" data-testid="ready-start-step">
                    <button className={botRunning ? "operation-bot-action operation-bot-action--stop" : "operation-bot-action"} disabled={botRunning ? botPending : isLiveMode ? !liveStartTriggerAllowed : !paperStartAllowed} onClick={handleBotLifecycle} type="button">
                        {botPending ? (botRunning ? "STOPPING..." : "STARTING...") : (botRunning ? "STOP BOT" : "START BOT")}
                    </button>
                    <div className="operation-bot-state">BOT {botRunning ? "RUNNING" : "STOPPED"}</div>
                    {botError && <div className="operation-inline-error" role="alert">{botError}</div>}
                    {loopError && <div className="operation-inline-error" role="alert">{loopError}</div>}
                    {autoTradeError && <div className="operation-inline-error" role="alert">{autoTradeError}</div>}
                </div>
            </OperationPreparation>

            {/* LIVE START Confirmation Modal */}
            {liveConfirmOpen && (
                <div
                    className="operation-live-confirm"
                    role="dialog"
                    aria-modal="true"
                    aria-label="Confirm LIVE start"
                    onClick={(e) => {
                        // Close on backdrop click
                        if (e.target === e.currentTarget) {
                            cancelLiveConfirm();
                        }
                    }}
                    onKeyDown={(e) => {
                        // ESC to cancel
                        if (e.key === "Escape") {
                            cancelLiveConfirm();
                        }
                        if (e.key === "Tab") {
                            const buttons = [...e.currentTarget.querySelectorAll("button:not(:disabled)")];
                            if (buttons.length === 1) {
                                e.preventDefault();
                                buttons[0].focus();
                            } else if (buttons.length > 1) {
                                const first = buttons[0];
                                const last = buttons[buttons.length - 1];
                                if (e.shiftKey && document.activeElement === first) {
                                    e.preventDefault();
                                    last.focus();
                                } else if (!e.shiftKey && document.activeElement === last) {
                                    e.preventDefault();
                                    first.focus();
                                }
                            }
                        }
                    }}
                >
                    <div className="operation-live-confirm__content">
                        <div className="operation-live-confirm__title">
                            LIVE取引を開始します
                        </div>

                        <div className="operation-live-confirm__body">
                            <p>
                                LIVE runtimeを監視専用のDISARMED状態で開始します。
                                注文権限のARM、Runtime Loop、Auto Tradeは開始後に個別の操作が必要です。
                                この確認だけでは注文権限は有効にならず、注文も行われません。
                            </p>

                            <div className="operation-live-confirm__details">
                                <div className="operation-live-confirm__detail-row">
                                    <span>START READINESS:</span>
                                    <strong>{startReadiness.startReadiness}</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Mode:</span>
                                    <strong>{startSettings?.tradingMode}</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Market Selection:</span>
                                    <strong>{selectionModeDisplayLabel(startSettings?.selectionMode)}</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Symbol:</span>
                                    <strong>{effectiveStartSymbol}</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Risk / Trade:</span>
                                    <strong>{startRiskPercent}%</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Leverage:</span>
                                    <strong>{startSettings?.requestedLeverage}x</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Execution Authority:</span>
                                    <strong>DISARMED</strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Real Order Authority:</span>
                                    <strong className="operation-live-confirm__danger">
                                        DISARMED
                                    </strong>
                                </div>
                                <div className="operation-live-confirm__detail-row">
                                    <span>Loop / Auto Trade:</span>
                                    <strong>OFF / OFF</strong>
                                </div>
                            </div>
                            {!liveConfirmAllowed && (
                                <div className="operation-live-confirm__blocked" id="live-confirm-block-reasons">
                                    <strong>現在はLIVEを開始できません。</strong>
                                    <span>設定またはRuntime Authorityを確認してください。</span>
                                    <ul>
                                        {liveBlockReasons.map((reason) => <li key={reason}>{reason}</li>)}
                                    </ul>
                                </div>
                            )}
                        </div>

                        <div className="operation-live-confirm__actions">
                            <button
                                className="operation-live-confirm__cancel"
                                onClick={cancelLiveConfirm}
                                type="button"
                                autoFocus
                            >
                                キャンセル
                            </button>

                            <button
                                className="operation-live-confirm__confirm"
                                aria-describedby={!liveConfirmAllowed ? "live-confirm-block-reasons" : undefined}
                                onClick={confirmLiveStart}
                                disabled={!liveConfirmAllowed}
                                type="button"
                            >
                                {botPending ? "STARTING..." : "LIVEを開始"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

        </div>

    );

}
