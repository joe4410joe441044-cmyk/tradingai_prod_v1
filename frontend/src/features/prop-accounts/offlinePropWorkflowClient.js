const OFFLINE_BOUNDARY = "http://127.0.0.1:4188";

async function post(path, payload, signal) {
    const response = await fetch(`${OFFLINE_BOUNDARY}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
        signal,
    });
    let document;
    try {
        document = await response.json();
    } catch {
        throw { code: "INVALID_BOUNDARY_RESPONSE", message: "隔離評価entryから安全なJSON応答を取得できませんでした", fields: {} };
    }
    if (!response.ok || !document?.ok) {
        throw document?.error ?? { code: "OFFLINE_BOUNDARY_ERROR", message: "隔離評価に失敗しました", fields: {} };
    }
    return document;
}

export const createOfflineAccount = (payload, signal) => post("/offline/accounts", payload, signal);
export const reviseOfflineAccount = (payload, signal) => post("/offline/accounts/revise", payload, signal);
export const evaluateOfflineAccount = (payload, signal) => post("/offline/evaluate", payload, signal);
