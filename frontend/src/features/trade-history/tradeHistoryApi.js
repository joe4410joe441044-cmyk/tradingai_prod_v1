import { API } from "../../api/index.js";

import { buildTradeHistoryQuery } from "./tradeHistoryModel.js";

/* =================================================
   TRADE HISTORY API client.

   Thin read-only client of the canonical completed-trade store:
     GET /api/trade-history
     GET /api/trade-history/detail?recordId=

   HTTP failures are returned as { ok:false, status, body } so the UI can
   render an explicit error state without throwing.
================================================ */

const toResult = async (response) => {
    let body = null;
    try {
        body = await response.json();
    } catch {
        body = null;
    }
    return { ok: response.ok, status: response.status, body };
};

const requestJson = async (url) => {
    try {
        const response = await fetch(url, { credentials: "same-origin" });
        return await toResult(response);
    } catch {
        return { ok: false, status: 0, body: null };
    }
};

export const getTradeHistory = (filters = {}) => {
    const query = buildTradeHistoryQuery(filters);
    const base = API.tradeHistory();
    return requestJson(query ? `${base}?${query}` : base);
};

export const getTradeHistoryDetail = (recordId) => {
    if (recordId === null || recordId === undefined || recordId === "") {
        return Promise.resolve({ ok: false, status: 422, body: null });
    }
    const base = API.tradeHistoryDetail();
    return requestJson(
        `${base}?recordId=${encodeURIComponent(String(recordId))}`,
    );
};
