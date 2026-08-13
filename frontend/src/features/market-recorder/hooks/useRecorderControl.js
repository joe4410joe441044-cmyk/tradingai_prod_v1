import { useState, useCallback, useRef } from "react";
import {
    RECORDER_CONTROL_CAPABILITY, RECORDER_CONTROL_STATE, RECORDER_STATUS_STATE,
} from "../contracts/recorderContracts.js";
import { createRecorderError, RECORDER_ERROR_CODE } from "../contracts/recorderError.js";
import { recorderClient } from "../services/recorderClient.js";

function resolveCapability(status) {
    if (status === null || status === undefined) {
        return RECORDER_CONTROL_CAPABILITY.UNAVAILABLE;
    }
    if (status.status === RECORDER_STATUS_STATE.RUNNING
            || status.status === RECORDER_STATUS_STATE.STOPPED) {
        return RECORDER_CONTROL_CAPABILITY.AVAILABLE;
    }
    return RECORDER_CONTROL_CAPABILITY.UNAVAILABLE;
}

export function useRecorderControl(statusResource, relatedResources) {
    var status = statusResource?.data;
    var statusLoading = statusResource?.isLoading === true;
    var refreshStatus = statusResource?.refresh;

    var capability = resolveCapability(status);
    var capabilityAvailable = capability === RECORDER_CONTROL_CAPABILITY.AVAILABLE;

    var [controlState, setControlState] = useState(RECORDER_CONTROL_STATE.IDLE);
    var [controlError, setControlError] = useState(null);
    var [controlResult, setControlResult] = useState(null);
    var inFlightRef = useRef(false);

    var isStarting = controlState === RECORDER_CONTROL_STATE.STARTING;
    var isStopping = controlState === RECORDER_CONTROL_STATE.STOPPING;
    var isIdle = controlState === RECORDER_CONTROL_STATE.IDLE;

    var isDisabled = !capabilityAvailable || statusLoading || !isIdle;
    var canStart = !isDisabled && status?.status === RECORDER_STATUS_STATE.STOPPED;
    var canStop = !isDisabled && status?.status === RECORDER_STATUS_STATE.RUNNING;

    var runControl = useCallback(async function (operation) {
        if (inFlightRef.current) {
            return;
        }
        inFlightRef.current = true;
        setControlState(operation === "start"
            ? RECORDER_CONTROL_STATE.STARTING : RECORDER_CONTROL_STATE.STOPPING);
        setControlError(null);
        setControlResult(null);
        try {
            var result = await recorderClient[operation]();
            if (!result || result.successful !== true) {
                throw createRecorderError(
                    RECORDER_ERROR_CODE.CONTROL_CONFLICT,
                    "Recorder " + operation + " rejected: "
                        + (result?.result || result?.status || result?.message || "unknown result"),
                    { retryable: false, source: "server" },
                );
            }
            setControlResult(result);
            var refreshes = [];
            if (typeof refreshStatus === "function") refreshes.push(refreshStatus());
            if (Array.isArray(relatedResources)) {
                relatedResources.forEach(function (resource) {
                    if (typeof resource?.refresh === "function") refreshes.push(resource.refresh());
                });
            }
            await Promise.all(refreshes);
        } catch (err) {
            setControlError(err);
        } finally {
            inFlightRef.current = false;
            setControlState(RECORDER_CONTROL_STATE.IDLE);
        }
    }, [refreshStatus, relatedResources]);

    var startRecorder = useCallback(async function () {
        if (!canStart) {
            return;
        }
        await runControl("start");
    }, [canStart, runControl]);

    var stopRecorder = useCallback(async function () {
        if (!canStop) {
            return;
        }
        await runControl("stop");
    }, [canStop, runControl]);

    return {
        capability: capability,
        capabilityAvailable: capabilityAvailable,
        controlState: controlState,
        controlError: controlError,
        controlResult: controlResult,
        isDisabled: isDisabled,
        canStart: canStart,
        canStop: canStop,
        isStarting: isStarting,
        isStopping: isStopping,
        isIdle: isIdle,
        startRecorder: startRecorder,
        stopRecorder: stopRecorder,
    };
}
