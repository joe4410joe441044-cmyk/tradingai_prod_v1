import React, {
    useRef,
    useState,
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
import OperationToggle from "./common/OperationToggle";

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

    return "READY";
};

const formatEmergencyTimestamp = (
    value
) => {
    if (!value) {
        return null;
    }

    return String(value).replace("T", " ").replace("Z", " UTC");
};

const emergencyStateCopy = {
    READY: {
        label: "READY",
        text: "緊急停止は作動していません",
        tone: "ready",
    },
    PROCESSING: {
        label: "PROCESSING",
        text: "緊急停止処理を実行中です",
        tone: "processing",
    },
    LOCKED: {
        label: "STOPPED SAFELY",
        text: "緊急停止が正常に完了しました",
        tone: "locked",
    },
    ACTION_REQUIRED: {
        label: "ACTION REQUIRED",
        text: "緊急停止は一部完了、失敗、または確認不能です",
        tone: "action",
    },
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

    onStatusRefresh,

    setExecutionEnabledState,

}){

    const [, forceUpdate] =
        useState(0);
    const [
        loopPending,
        setLoopPending,
    ] = useState(false);
    const [
        loopPendingAction,
        setLoopPendingAction,
    ] = useState(null);
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
        unlockPending,
        setUnlockPending,
    ] = useState(false);
    const [
        unlockError,
        setUnlockError,
    ] = useState(null);
    const [
        unlockNotice,
        setUnlockNotice,
    ] = useState(null);
    const [
        unlockConfirmOpen,
        setUnlockConfirmOpen,
    ] = useState(false);
    const loopPendingRef =
        useRef(false);
    const autoTradePendingRef =
        useRef(false);
    const emergencyPendingRef =
        useRef(false);
    const unlockPendingRef =
        useRef(false);

    /* =======================================================
       STATUS
    ======================================================= */

    const autoTradeChecked =
        executionEnabled === true;
    const autoTradeStateText = autoTradeChecked
        ? "ENABLED"
        : "DISABLED";
    const autoTradeStateReason = autoTradeChecked
        ? null
        : "Reason: DISABLED_BY_OPERATOR";
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
    const loopStateDisplay = (
        loopStateText
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
    const loopStatusText = (
        loopPending && loopPendingAction
            ? `${loopPendingAction}...（処理中）`
            : loopStateDisplay
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
    const emergencyStateDetails = (
        emergencyStateCopy[emergencyStateCode]
        || emergencyStateCopy.READY
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
    const loopDisabled = (
        loopPending
        || emergencyBlocksOperations
    );
    const unlockAllowed = (
        emergencyStateCode === "LOCKED"
        && emergencyIsLocked
        && autoTradeChecked === false
        && positionRemaining !== true
        && stateUnknown !== true
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

    const startLoop = async () => {
        console.log(
            "START BUTTON CLICKED"
        );

        console.log(
            "START CONFIG",
            config
        );

        console.log(
            "POST BODY",
            config
        );

        const response =
            await fetch(
                API.botStart(),
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json",
                    },

                    body: JSON.stringify({
                        symbol: config.symbol,
                        exchange: String(config.exchange || "kucoin").toLowerCase(),
                        risk_percent: Number(config.risk_percent ?? 1),
                        position_size: Number(config.position_size ?? config.positionSize ?? 0),
                        max_drawdown_pct: Number(config.max_drawdown_pct ?? config.maxDd ?? 5),
                        sl_percent: Number(config.sl_percent ?? config.sl ?? 1),
                        leverage: Number(config.leverage ?? 1),
                        timeframe: String(config.timeframe || "1m"),
                        tp_percent: Number(config.tp_percent ?? config.tp ?? 1),
                        trailing_stop: Boolean(config.trailing_stop ?? config.trailing ?? false),
                        mode: String(config.mode || "paper").toLowerCase()
                    })

                }
            );

        if (!response.ok) {
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
            endpoint: API.botStop(),
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

    const openUnlockConfirm = () => {
        if (
            unlockPendingRef.current
            || unlockConfirmOpen
            || !unlockAllowed
        ) {
            return;
        }

        setUnlockError(null);
        setUnlockConfirmOpen(true);
    };

    const cancelUnlockConfirm = () => {
        if (unlockPendingRef.current) {
            return;
        }

        setUnlockConfirmOpen(false);
    };

    const confirmUnlock = async () => {
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

        try {
            await unlockEmergency();

            setUnlockNotice(
                "緊急状態は解除されました。BOTは停止中です。"
            );
            setUnlockConfirmOpen(false);
        } catch (error) {
            console.error("EMERGENCY UNLOCK ERROR", error);
            setUnlockError(
                formatUnlockError(error)
            );
            setUnlockConfirmOpen(false);
        } finally {
            await refreshStatusSafely();
            unlockPendingRef.current = false;
            setUnlockPending(false);
        }
    };

    /* =======================================================
       UI
    ======================================================= */

    return (

        <div className="terminal-panel">

            {/* =======================================================
               SECTION TITLE
            ======================================================= */}

            <div className="left-card-header operation-card-header">

                <div className="left-card-title section-number-title">

                    OPERATION（操作）

                </div>

            </div>

            {/* =======================================================
               LOOP
            ======================================================= */}

            <div className="operation-section operation-section--loop">

                <OperationToggle
                    ariaLabel="Toggle trading loop"
                    checked={loopChecked}
                    disabled={loopDisabled}
                    label="LOOP"
                    loading={loopPending}
                    offText="OFF"
                    onChange={handleLoopChange}
                    onText="ON"
                />

                <div className="operation-state-row">

                    <span className="operation-state-label">
                        LOOP STATE（ループ状態）
                    </span>

                    <span
                        className={
                            "operation-state-value "
                            + `operation-state-value--${loopStateTone}`
                        }
                    >
                        {loopStateDisplay}
                    </span>
                </div>

                {loopPending && loopPendingAction && (
                    <div className="operation-state-reason operation-state-reason--pending">
                        Operation: {loopStatusText}
                    </div>
                )}

                {emergencyOperationGuardReason && (
                    <div className="operation-state-reason operation-state-reason--warning">
                        {emergencyOperationGuardReason}
                    </div>
                )}

                {loopError && (
                    <div
                        className="operation-inline-error"
                        data-testid="loop-error"
                        role="alert"
                    >
                        {loopError}
                    </div>
                )}

            </div>

            <div className="operation-section operation-section--auto-trade">

                <OperationToggle
                    ariaLabel="Toggle automatic trading"
                    checked={autoTradeChecked}
                    disabled={autoTradeDisabled}
                    label="AUTO TRADE"
                    loading={autoTradePending}
                    offText="OFF"
                    onChange={handleAutoTradeChange}
                    onText="ON"
                />

                <div className="operation-state-row">

                    <span className="operation-state-label">
                        AUTO TRADE STATE（自動注文状態）
                    </span>

                    <span
                        className={
                            "operation-state-value "
                            + (
                                autoTradeChecked
                                    ? "operation-state-value--enabled"
                                    : "operation-state-value--disabled"
                            )
                        }
                    >
                        {autoTradeStateText}
                    </span>

                </div>

                {autoTradeStateReason && (
                    <div className="operation-state-reason">
                        {autoTradeStateReason}
                    </div>
                )}

                {autoTradeDisabledReason && (
                    <div
                        className="operation-state-reason operation-state-reason--warning"
                        data-testid="auto-trade-disabled-reason"
                    >
                        {autoTradeDisabledReason}
                    </div>
                )}

                {autoTradeError && (
                    <div
                        className="operation-auto-trade-error"
                        data-testid="auto-trade-error"
                        role="alert"
                    >
                        {autoTradeError}
                    </div>
                )}

            </div>

            <div className="operation-section operation-emergency-section">

                <div className="operation-section-title">
                    EMERGENCY
                </div>

                <div
                    className={
                        "operation-emergency-status "
                        + `operation-emergency-status--${emergencyStateDetails.tone}`
                    }
                >
                    <span className="operation-emergency-status__eyebrow">
                        EMERGENCY STATUS
                    </span>

                    <strong className="operation-emergency-status__state">
                        {emergencyStateDetails.label}
                    </strong>

                    <span className="operation-emergency-status__message">
                        {emergencyStateDetails.text}
                    </span>

                    {emergencyStateCode === "PROCESSING" && (
                        <span className="operation-emergency-status__pending">
                            PROCESSING
                        </span>
                    )}

                    {emergencyStateCode === "LOCKED" && lockedFacts.length > 0 && (
                        <div className="operation-emergency-facts">
                            {lockedFacts.map((fact) => (
                                <span key={fact}>
                                    {fact}
                                </span>
                            ))}
                        </div>
                    )}

                    {emergencyStateCode === "ACTION_REQUIRED"
                        && actionWarnings.length > 0 && (
                        <div className="operation-emergency-warnings">
                            {actionWarnings.map((warning) => (
                                <span key={warning}>
                                    {warning}
                                </span>
                            ))}
                        </div>
                    )}

                    {lastResultMessage && emergencyStateCode !== "READY" && (
                        <span className="operation-emergency-status__message">
                            {lastResultMessage}
                        </span>
                    )}

                    {unlockNotice && emergencyStateCode === "READY" && (
                        <span className="operation-emergency-status__message operation-emergency-status__message--safe">
                            {unlockNotice}
                        </span>
                    )}
                </div>

                <button
                    className="emergency-stop-button operation-emergency-button"
                    disabled={emergencyButtonDisabled}
                    onClick={openEmergencyConfirm}
                    aria-busy={emergencyPending ? "true" : undefined}
                    type="button"
                >

                    {emergencyPending
                        ? "EMERGENCY IN PROGRESS...（処理中）"
                        : "EMERGENCY STOP（緊急停止）"
                    }

                </button>

                {emergencyStateCode === "LOCKED" && (
                    <div className="operation-emergency-note">
                        Emergency Lock is active.（Emergency Lockが有効です）
                    </div>
                )}

                {emergencyConfirmOpen && (
                    <div
                        className="operation-emergency-confirm"
                        role="dialog"
                        aria-modal="true"
                        aria-label="Confirm emergency stop"
                    >
                        <div className="operation-emergency-confirm__title">
                            EMERGENCY STOP
                        </div>

                        <div className="operation-emergency-confirm__body">
                            This action will activate Emergency Lock, disable Auto Trade,
                            cancel eligible open orders, and flatten eligible positions.
                        </div>

                        <div className="operation-emergency-confirm__actions">
                            <button
                                className="operation-emergency-confirm__cancel"
                                disabled={emergencyPending}
                                onClick={cancelEmergencyConfirm}
                                type="button"
                            >
                                CANCEL
                            </button>

                            <button
                                className="operation-emergency-confirm__confirm"
                                disabled={emergencyPending}
                                onClick={confirmEmergency}
                                type="button"
                            >
                                CONFIRM EMERGENCY
                            </button>
                        </div>
                    </div>
                )}

                {emergencyStateCode === "LOCKED" && (
                    <button
                        className="operation-emergency-unlock"
                        disabled={!unlockAllowed || unlockPending}
                        onClick={openUnlockConfirm}
                        aria-busy={unlockPending ? "true" : undefined}
                        type="button"
                    >
                        {unlockPending
                            ? "解除中..."
                            : "緊急状態を解除"
                        }
                    </button>
                )}

                {unlockConfirmOpen && (
                    <div
                        className="operation-emergency-confirm"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="emergency-unlock-title"
                    >
                        <div
                            className="operation-emergency-confirm__title"
                            id="emergency-unlock-title"
                        >
                            緊急状態を解除しますか？
                        </div>

                        <div className="operation-emergency-confirm__body">
                            解除後もBOTは起動しません。
                            <br />
                            LOOPとAUTO TRADEもOFFのままです。
                        </div>

                        <div className="operation-emergency-confirm__actions">
                            <button
                                className="operation-emergency-confirm__cancel"
                                disabled={unlockPending}
                                onClick={cancelUnlockConfirm}
                                type="button"
                            >
                                キャンセル
                            </button>

                            <button
                                className="operation-emergency-confirm__confirm"
                                disabled={unlockPending}
                                onClick={confirmUnlock}
                                type="button"
                            >
                                緊急状態を解除
                            </button>
                        </div>
                    </div>
                )}

                <div className="operation-emergency-lock">
                    <span className="operation-state-label">
                        EMERGENCY LOCK（緊急ロック）
                    </span>

                    <strong className={emergencyLockClass}>
                        {emergencyLockValue}
                    </strong>
                </div>

                {emergencyPath && emergencyStateCode !== "READY" && (
                    <div className="operation-emergency-detail">
                        Execution path: {String(emergencyPath).toUpperCase()}
                    </div>
                )}

                {emergencyError && (
                    <div
                        className="operation-emergency-error"
                        data-testid="emergency-error"
                        role="alert"
                    >
                        {emergencyError}
                    </div>
                )}

                {unlockError && (
                    <div
                        className="operation-emergency-error"
                        data-testid="emergency-unlock-error"
                        role="alert"
                    >
                        {unlockError}
                    </div>
                )}

            </div>

        </div>

    );

}
