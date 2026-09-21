import { useCallback, useEffect, useRef, useState } from "react";

import {
    getTradeHistory,
    getTradeHistoryDetail,
} from "./tradeHistoryApi.js";
import {
    DEFAULT_FILTERS,
    isTradeHistoryQueryReady,
    parseTradeHistoryQuery,
} from "./tradeHistoryModel.js";

/* =================================================
   TRADE HISTORY data controller.

   Loads the read-only completed-trade history for the current filter state and
   fetches a single trade detail on demand.  It is fully isolated from any
   authority: a read failure never mutates configuration, execution or trading
   state.
================================================ */

export function useTradeHistory(initialSearch = "") {
    const [filters, setFilters] = useState(() => ({
        ...DEFAULT_FILTERS,
        ...parseTradeHistoryQuery(initialSearch),
    }));
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const detailRequest = useRef(0);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState(null);

    useEffect(() => {
        const sync = () => setFilters(parseTradeHistoryQuery(window.location.search));
        window.addEventListener("popstate", sync);
        return () => window.removeEventListener("popstate", sync);
    }, []);

    useEffect(() => {
        if (!isTradeHistoryQueryReady(filters)) {
            setLoading(false);
            setError(null);
            return undefined;
        }
        let active = true;
        (async () => {
            setLoading(true);
            setError(null);
            const result = await getTradeHistory(filters);
            if (!active) return;
            if (result?.ok) {
                setData(result.body);
            } else {
                setData(null);
                setError({ status: result?.status ?? 0 });
            }
            setLoading(false);
        })();
        return () => {
            active = false;
        };
    }, [filters]);

    const updateFilter = useCallback((key, value) => {
        setFilters((current) => ({
            ...current,
            [key]: value,
            ...(key === "mode" ? { scope: null } : {}),
            ...(key === "period" && value !== "custom" ? { fromTimestamp: null, toTimestamp: null } : {}),
            ...(key === "page" ? {} : { page: 1 }),
        }));
    }, []);

    const setPage = useCallback((page) => {
        setFilters((current) => ({
            ...current,
            page: Math.max(1, Math.trunc(Number(page) || 1)),
        }));
    }, []);

    const setSort = useCallback((field, direction = null) => {
        setFilters((current) => ({
            ...current,
            sort: field,
            direction: direction ?? current.direction,
            page: 1,
        }));
    }, []);

    const resetFilters = useCallback(() => {
        setFilters({ ...DEFAULT_FILTERS });
    }, []);

    const openDetail = useCallback(async (recordId) => {
        if (!recordId) return;
        const request = ++detailRequest.current;
        setDetail(null);
        setDetailLoading(true);
        setDetailError(null);
        const result = await getTradeHistoryDetail(recordId);
        if (request !== detailRequest.current) return;
        if (result?.ok) {
            setDetail(result.body);
        } else {
            setDetail(null);
            setDetailError({ status: result?.status ?? 0 });
        }
        setDetailLoading(false);
    }, []);

    const closeDetail = useCallback(() => {
        detailRequest.current += 1;
        setDetailLoading(false);
        setDetail(null);
        setDetailError(null);
    }, []);

    const reload = useCallback(() => {
        setFilters((current) => ({ ...current }));
    }, []);

    return {
        filters,
        data,
        loading,
        error,
        detail,
        detailLoading,
        detailError,
        updateFilter,
        setPage,
        setSort,
        resetFilters,
        openDetail,
        closeDetail,
        reload,
    };
}
