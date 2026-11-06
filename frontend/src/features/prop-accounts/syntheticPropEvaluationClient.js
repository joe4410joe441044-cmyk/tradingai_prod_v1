import { authenticatedControlRequest } from "../auth/operatorAuth.js";

export const SYNTHETIC_PROP_ENDPOINTS = Object.freeze({
    create: "/api/prop-accounts/synthetic/accounts",
    revise: "/api/prop-accounts/synthetic/accounts/revise",
    evaluate: "/api/prop-accounts/synthetic/evaluate",
});

export function createSyntheticPropEvaluationClient({ request = authenticatedControlRequest } = {}) {
    const requestPost = async (path, payload, signal) => {
        const response = await request(path, {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            cache: "no-store",
            signal,
        });
        let document;
        try {
            document = await response.json();
        } catch {
            throw { code: "INVALID_BOUNDARY_RESPONSE", message: "安全なJSON応答を取得できませんでした", fields: {} };
        }
        if (!response.ok || !document?.ok) {
            throw document?.error ?? { code: "SYNTHETIC_BOUNDARY_ERROR", message: "隔離評価に失敗しました", fields: {} };
        }
        return document;
    };
    return Object.freeze({
        createOfflineAccount: (payload, signal) => requestPost(SYNTHETIC_PROP_ENDPOINTS.create, payload, signal),
        reviseOfflineAccount: (payload, signal) => requestPost(SYNTHETIC_PROP_ENDPOINTS.revise, payload, signal),
        evaluateOfflineAccount: (payload, signal) => requestPost(SYNTHETIC_PROP_ENDPOINTS.evaluate, payload, signal),
    });
}

export const syntheticPropEvaluationClient = createSyntheticPropEvaluationClient();
