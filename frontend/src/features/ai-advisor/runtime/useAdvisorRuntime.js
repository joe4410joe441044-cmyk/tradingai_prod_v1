import { useCallback, useEffect, useRef, useState } from "react";

import {
    OPERATOR_AUTH_STATE,
    getOperatorAuthStatus,
    subscribeOperatorAuthStatus,
} from "../../auth/operatorAuth.js";
import {
    AdvisorRuntimeApiError,
    fetchAdvisorRuntime,
} from "./advisorRuntimeApi.js";
import { normalizeAdvisorRuntimeResponse } from "./advisorRuntimeModel.js";

export const ADVISOR_RUNTIME_POLL_MS = 5000;

export const initialAdvisorRuntimeState = {
    data: null,
    connectionState: "LOADING",
    loading: true,
    error: null,
    lastSuccessfulAt: null,
};

const isIntentionalAbort = (error) => error?.name === "AbortError";
const safeRuntimeError = (error) => (
    error instanceof AdvisorRuntimeApiError
        ? error
        : new AdvisorRuntimeApiError({
            code: "ADVISOR_RUNTIME_NETWORK_ERROR",
            message: "Runtime status request failed.",
            retryable: true,
        })
);

export function createAdvisorRuntimePoller({
    request,
    onState,
    intervalMs = ADVISOR_RUNTIME_POLL_MS,
    setTimer = setTimeout,
    clearTimer = clearTimeout,
}) {
    let stopped = false;
    let running = false;
    let controller = null;
    let timer = null;
    let lastGood = null;
    let lastSuccessfulAt = null;

    const schedule = () => {
        if (!stopped) {
            timer = setTimer(() => {
                timer = null;
                run();
            }, intervalMs);
        }
    };
    const run = async () => {
        if (stopped || running) return false;
        running = true;
        controller = new AbortController();
        onState((previous) => ({
            ...previous,
            loading: previous.data === null,
            connectionState: previous.data ? "REFRESHING" : "LOADING",
            error: null,
        }));
        try {
            const result = await request(controller.signal);
            if (stopped) return false;
            lastGood = result.data;
            lastSuccessfulAt = result.receivedAt;
            onState({
                data: result.data,
                connectionState: "CONNECTED",
                loading: false,
                error: null,
                lastSuccessfulAt: result.receivedAt,
            });
        } catch (error) {
            if (!stopped && !isIntentionalAbort(error)) {
                onState({
                    data: lastGood,
                    connectionState: lastGood ? "DEGRADED" : "DISCONNECTED",
                    loading: false,
                    error: safeRuntimeError(error),
                    lastSuccessfulAt,
                });
            }
        } finally {
            running = false;
            controller = null;
            schedule();
        }
        return true;
    };

    return {
        start: run,
        retry() {
            if (timer !== null) {
                clearTimer(timer);
                timer = null;
            }
            return run();
        },
        reset() {
            lastGood = null;
            lastSuccessfulAt = null;
            controller?.abort();
            onState({
                data: null,
                connectionState: "DISCONNECTED",
                loading: false,
                error: null,
                lastSuccessfulAt: null,
            });
        },
        stop() {
            stopped = true;
            if (timer !== null) clearTimer(timer);
            controller?.abort();
        },
        isRunning: () => running,
    };
}

const requestNormalizedRuntime = async (signal) => {
    const result = await fetchAdvisorRuntime({ signal });
    return {
        data: normalizeAdvisorRuntimeResponse(result.raw),
        receivedAt: result.receivedAt,
    };
};

export default function useAdvisorRuntime() {
    const [state, setState] = useState(initialAdvisorRuntimeState);
    const pollerRef = useRef(null);

    useEffect(() => {
        const poller = createAdvisorRuntimePoller({
            request: requestNormalizedRuntime,
            onState: setState,
        });
        pollerRef.current = poller;
        poller.start();
        return () => {
            poller.stop();
            pollerRef.current = null;
        };
    }, []);

    useEffect(() => {
        const applyAuth = (status) => {
            if (status === OPERATOR_AUTH_STATE.AUTHENTICATED) {
                // Login success: refetch runtime immediately.
                pollerRef.current?.retry();
            } else {
                // Logout/session-expiry: invalidate authenticated runtime state.
                pollerRef.current?.reset();
            }
        };
        const current = getOperatorAuthStatus();
        if (current !== null) applyAuth(current);
        return subscribeOperatorAuthStatus(applyAuth);
    }, []);

    const retry = useCallback(() => pollerRef.current?.retry(), []);
    return { ...state, retry };
}
