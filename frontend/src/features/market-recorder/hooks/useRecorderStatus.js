import { useState, useCallback, useEffect, useRef } from "react";
import {
    DATA_STATE,
    createSuccessDataState,
    createErrorDataState,
    createUnavailableDataState,
    createLoadingDataState,
} from "../contracts/recorderDataState.js";
import { RECORDER_DATA_SOURCE } from "../contracts/recorderContracts.js";
import {
    createRecorderUnsupportedSourceError,
    RECORDER_ERROR_CODE,
} from "../contracts/recorderError.js";
import { MOCK_RECORDER_STATUS } from "../mock/mockRecorderData.js";
import { toRecorderStatusViewModel } from "../adapters/recorderAdapters.js";
import { recorderClient } from "../services/recorderClient.js";

var currentSource = RECORDER_DATA_SOURCE.API;

export function setRecorderDataSource(source) {
    currentSource = source;
}

export function getRecorderDataSource() {
    return currentSource;
}

function resolveMockState() {
    var vm = toRecorderStatusViewModel(MOCK_RECORDER_STATUS);
    return createSuccessDataState(vm);
}

async function resolveApiState(signal) {
    try {
        var domain = await recorderClient.getStatus({ signal: signal });
        if (signal && signal.aborted) {
            return createUnavailableDataState();
        }
        if (domain === null || domain === undefined) {
            return createUnavailableDataState();
        }
        var vm = toRecorderStatusViewModel(domain);
        return createSuccessDataState(vm);
    } catch (err) {
        if (signal && signal.aborted) {
            return createUnavailableDataState();
        }
        if (err && err.code === RECORDER_ERROR_CODE.NETWORK) {
            return {
                status: DATA_STATE.UNAVAILABLE,
                data: null,
                error: err,
                updatedAt: Date.now(),
                isLoading: false,
                isSuccess: false,
                isEmpty: false,
                isError: false,
                isUnavailable: true,
            };
        }
        return createErrorDataState(err);
    }
}

export function useRecorderStatus() {
    var mountedRef = useRef(true);
    var abortRef = useRef(null);
    var requestIdRef = useRef(0);

    var [state, setState] = useState(function () {
        if (currentSource === RECORDER_DATA_SOURCE.MOCK) {
            return resolveMockState();
        }
        return createLoadingDataState();
    });

    var refresh = useCallback(function () {
        if (currentSource === RECORDER_DATA_SOURCE.MOCK) {
            setState(resolveMockState());
            return Promise.resolve();
        }
        if (currentSource === RECORDER_DATA_SOURCE.API) {
            if (abortRef.current) {
                abortRef.current.abort();
            }
            requestIdRef.current += 1;
            var requestId = requestIdRef.current;
            abortRef.current = new AbortController();
            var signal = abortRef.current.signal;
            return resolveApiState(signal).then(function (newState) {
                if (mountedRef.current && requestId === requestIdRef.current) {
                    setState(newState);
                }
            });
        }
        setState(createErrorDataState(
            createRecorderUnsupportedSourceError(currentSource),
        ));
        return Promise.resolve();
    }, []);

    useEffect(function () {
        mountedRef.current = true;
        refresh();
        var pollId = null;
        if (currentSource === RECORDER_DATA_SOURCE.API) {
            pollId = setInterval(refresh, 10000);
        }
        return function () {
            mountedRef.current = false;
            if (pollId !== null) {
                clearInterval(pollId);
            }
            if (abortRef.current) {
                abortRef.current.abort();
                abortRef.current = null;
            }
        };
    }, [refresh]);

    return {
        data: state.data,
        dataState: state.status,
        error: state.error,
        isLoading: state.isLoading,
        isEmpty: state.isEmpty,
        isError: state.isError,
        isUnavailable: state.isUnavailable,
        updatedAt: state.updatedAt,
        refresh: refresh,
    };
}
