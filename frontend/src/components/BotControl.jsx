import React, {
    useRef,
    useState,
} from "react";

import {
    updateExecutionRuntimeTelemetry,
} from "../store/telemetryStore";

import {
    classifyEmergencyResult,
    runEmergencyOrchestrator,
    setExecutionEnabled,
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

export default function BotControl({

    config,

    executionEnabled,

    botRunning,

    loopEnabled,

    loopState,

    emergencyLocked,

    emergencyState,

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
        emergencyResult,
        setEmergencyResult,
    ] = useState(null);
    const [
        emergencyConfirmOpen,
        setEmergencyConfirmOpen,
    ] = useState(false);
    const loopPendingRef =
        useRef(false);
    const autoTradePendingRef =
        useRef(false);
    const emergencyPendingRef =
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
    const autoTradeDisabledReason = (
        !autoTradeChecked && emergencyLocked === true
            ? (
                "Auto Trade cannot be enabled while Emergency Lock is active."
                + "（Emergency Lock中はAUTO TRADEを有効にできません）"
            )
            : !autoTradeChecked && loopEnabled === false
                ? (
                    "Loop must be running before Auto Trade can be enabled."
                    + "（LOOPを開始してからAUTO TRADEを有効にしてください）"
                )
                : null
    );
    const autoTradeDisabled =
        autoTradePending || Boolean(autoTradeDisabledReason);
    const emergencyStateText = (
        typeof emergencyState === "string"
            && emergencyState.trim()
            ? emergencyState.trim().toUpperCase()
            : null
    );
    const emergencyLockValue = (
        emergencyLocked === true
            ? "LOCKED"
            : emergencyLocked === false
                ? "UNLOCKED"
                : emergencyStateText === "LOCKED"
                    ? "LOCKED"
                    : emergencyStateText === "UNLOCKED"
                        ? "UNLOCKED"
                        : "UNKNOWN"
    );
    const emergencyLockClass = (
        emergencyLockValue === "LOCKED"
            ? "locked"
            : emergencyLockValue === "UNLOCKED"
                ? "unlocked"
                : "unknown"
    );
    const emergencyButtonDisabled = (
        emergencyPending
        || emergencyConfirmOpen
    );
    const emergencyResultClassification = (
        emergencyError
            ? classifyEmergencyResult(null)
            : emergencyResult
                ? classifyEmergencyResult(emergencyResult)
                : null
    );

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
        if (loopPendingRef.current) {
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
        if (autoTradePendingRef.current) {
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
        setEmergencyResult(null);

        try {
            const result = await runEmergencyOrchestrator();

            setEmergencyResult(result);
            setEmergencyConfirmOpen(false);
        } catch (error) {
            console.error("EMERGENCY ORCHESTRATOR ERROR", error);
            setEmergencyError(
                formatEmergencyError(error)
            );
            setEmergencyConfirmOpen(false);
        } finally {
            emergencyPendingRef.current = false;
            setEmergencyPending(false);
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
                    disabled={loopPending}
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

                {emergencyLockValue === "LOCKED" && (
                    <div className="operation-emergency-note">
                        Emergency Lock is active.（Emergency Lockが有効です）
                    </div>
                )}

                {emergencyConfirmOpen && (
                    <div
                        className="operation-emergency-confirm"
                        role="dialog"
                        aria-modal="false"
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

                <div className="operation-emergency-lock">
                    <span className="operation-state-label">
                        EMERGENCY LOCK（緊急ロック）
                    </span>

                    <strong className={emergencyLockClass}>
                        {emergencyLockValue}
                    </strong>
                </div>

                {emergencyResultClassification && (
                    <div
                        className={
                            "operation-emergency-result "
                            + `operation-emergency-result--${emergencyResultClassification.severity}`
                        }
                        data-testid="emergency-result"
                    >
                        <strong>
                            {emergencyResultClassification.text}
                        </strong>

                        {emergencyResult?.error_code && (
                            <span>
                                Code: {emergencyResult.error_code}
                            </span>
                        )}

                        {emergencyResult && (
                            <span>
                                Path: {emergencyResult.execution_path || "UNKNOWN"}
                                {" / "}
                                Retryable: {emergencyResult.retryable ? "true" : "false"}
                            </span>
                        )}
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

            </div>

        </div>

    );

}
