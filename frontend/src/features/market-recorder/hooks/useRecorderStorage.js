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
import { MOCK_RECORDER_STORAGE } from "../mock/mockRecorderData.js";
import { toRecorderStorageViewModel } from "../adapters/recorderAdapters.js";
import { recorderClient } from "../services/recorderClient.js";
import { getRecorderDataSource } from "./useRecorderStatus.js";

function resolveMockState() {
    var vm = toRecorderStorageViewModel(MOCK_RECORDER_STORAGE);
    return createSuccessDataState(vm);
}

async function resolveApiState(signal) {
    try {
        var domain = await recorderClient.getStorage({ signal: signal });
        if (signal && signal.aborted) {
            return createUnavailableDataState();
        }
        if (domain === null || domain === undefined) {
            return createUnavailableDataState();
        }
        var vm = toRecorderStorageViewModel(domain);
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

export function useRecorderStorage() {
    var mountedRef = useRef(true);
    var abortRef = useRef(null);

    var [state, setState] = useState(function () {
        if (getRecorderDataSource() === RECORDER_DATA_SOURCE.MOCK) {
            return resolveMockState();
        }
        return createLoadingDataState();
    });

    useEffect(function () {
        mountedRef.current = true;
        if (getRecorderDataSource() === RECORDER_DATA_SOURCE.API) {
            abortRef.current = new AbortController();
            var signal = abortRef.current.signal;
            resolveApiState(signal).then(function (newState) {
                if (mountedRef.current) {
                    setState(newState);
                }
            });
        }
        return function () {
            mountedRef.current = false;
            if (abortRef.current) {
                abortRef.current.abort();
                abortRef.current = null;
            }
        };
    }, []);

    var refresh = useCallback(function () {
        if (getRecorderDataSource() === RECORDER_DATA_SOURCE.MOCK) {
            setState(resolveMockState());
            return;
        }
        if (getRecorderDataSource() === RECORDER_DATA_SOURCE.API) {
            if (abortRef.current) {
                abortRef.current.abort();
            }
            abortRef.current = new AbortController();
            var signal = abortRef.current.signal;
            resolveApiState(signal).then(function (newState) {
                if (mountedRef.current) {
                    setState(newState);
                }
            });
            return;
        }
        setState(createErrorDataState(
            createRecorderUnsupportedSourceError(getRecorderDataSource()),
        ));
    }, []);

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
