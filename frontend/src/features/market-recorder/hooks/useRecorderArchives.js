import { useState, useCallback, useEffect, useRef } from "react";
import {
    DATA_STATE,
    createSuccessDataState,
    createEmptyDataState,
    createErrorDataState,
    createLoadingDataState,
} from "../contracts/recorderDataState.js";
import { RECORDER_DATA_SOURCE } from "../contracts/recorderContracts.js";
import {
    createRecorderUnsupportedSourceError,
    RECORDER_ERROR_CODE,
} from "../contracts/recorderError.js";
import { MOCK_RECORDER_ARCHIVES } from "../mock/mockRecorderData.js";
import { toRecorderArchivesViewModel } from "../adapters/recorderAdapters.js";
import { recorderClient } from "../services/recorderClient.js";
import { getRecorderDataSource } from "./useRecorderStatus.js";

var ARCHIVE_PAGE_SIZE = 20;

function resolveMockState() {
    var vm = toRecorderArchivesViewModel(MOCK_RECORDER_ARCHIVES);
    if (vm.length === 0) {
        return createEmptyDataState();
    }
    return createSuccessDataState(vm);
}

async function resolveApiState(signal, page, pageSize) {
    try {
        var domain = await recorderClient.getArchives({
            page: page, page_size: pageSize, sort: "start_time", order: "desc",
        }, { signal: signal });
        if (signal && signal.aborted) {
            return { state: createEmptyDataState(), pagination: null };
        }
        if (domain === null || domain === undefined || !Array.isArray(domain.entries)) {
            return { state: createEmptyDataState(), pagination: null };
        }
        var vm = toRecorderArchivesViewModel(domain.entries);
        if (vm.length === 0) {
            return { state: createEmptyDataState(), pagination: {
                page: domain.page, pageSize: domain.pageSize,
                totalCount: domain.totalCount, totalPages: domain.totalPages,
            } };
        }
        return { state: createSuccessDataState(vm), pagination: {
            page: domain.page, pageSize: domain.pageSize,
            totalCount: domain.totalCount, totalPages: domain.totalPages,
        } };
    } catch (err) {
        if (signal && signal.aborted) {
            return { state: createEmptyDataState(), pagination: null };
        }
        if (err && err.code === RECORDER_ERROR_CODE.NETWORK) {
            return { state: {
                status: DATA_STATE.UNAVAILABLE,
                data: null,
                error: err,
                updatedAt: Date.now(),
                isLoading: false,
                isSuccess: false,
                isEmpty: false,
                isError: false,
                isUnavailable: true,
            }, pagination: null };
        }
        return { state: createErrorDataState(err), pagination: null };
    }
}

export function useRecorderArchives() {
    var mountedRef = useRef(true);
    var abortRef = useRef(null);
    var requestIdRef = useRef(0);
    var [page, setPage] = useState(1);
    var [pagination, setPagination] = useState(null);

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
            var requestId = ++requestIdRef.current;
            resolveApiState(signal, page, ARCHIVE_PAGE_SIZE).then(function (result) {
                if (mountedRef.current && requestId === requestIdRef.current) {
                    setState(result.state);
                    setPagination(result.pagination);
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
    }, [page]);

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
            var requestId = ++requestIdRef.current;
            return resolveApiState(signal, page, ARCHIVE_PAGE_SIZE).then(function (result) {
                if (mountedRef.current && requestId === requestIdRef.current) {
                    setState(result.state);
                    setPagination(result.pagination);
                }
            });
        }
        setState(createErrorDataState(
            createRecorderUnsupportedSourceError(getRecorderDataSource()),
        ));
    }, [page]);

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
        page: pagination?.page ?? page,
        pageSize: pagination?.pageSize ?? ARCHIVE_PAGE_SIZE,
        totalCount: pagination?.totalCount ?? 0,
        totalPages: pagination?.totalPages ?? 0,
        hasPreviousPage: (pagination?.page ?? page) > 1,
        hasNextPage: (pagination?.page ?? page) < (pagination?.totalPages ?? 0),
        previousPage: function () { setPage(function (value) { return Math.max(1, value - 1); }); },
        nextPage: function () { setPage(function (value) {
            var max = pagination?.totalPages ?? value;
            return Math.min(max, value + 1);
        }); },
    };
}
