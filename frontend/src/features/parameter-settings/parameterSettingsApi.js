import { API } from "../../api/index.js";
import { authenticatedControlRequest } from "../auth/operatorAuth.js";

/* =================================================
   PARAMETER SETTINGS API client.

   Thin client of the canonical backend authority:
     GET  /api/parameter-settings/schema
     GET  /api/parameter-settings/configuration?scope=
     GET  /api/parameter-settings/effective?scope=
     GET  /api/parameter-settings/runtime?scope=
     GET  /api/parameter-settings/status
     PUT  /api/parameter-settings/configuration   (single write path)

   HTTP failures are returned as { ok:false, status, body } so the UI can
   distinguish 409 (stale revision) from 422 (validation) without throwing.
   The backend remains the authoritative validator.
================================================= */

const toResult = async (response) => {
    let body = null;
    try {
        body = await response.json();
    } catch {
        body = null;
    }
    return { ok: response.ok, status: response.status, body };
};

const requestJson = async (url, options = {}) => {
    try {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
        });
        return await toResult(response);
    } catch {
        return { ok: false, status: 0, body: null };
    }
};

const scopedUrl = (base, scope) => (
    `${base}?scope=${encodeURIComponent(String(scope ?? ""))}`
);

export const getParameterSettingsSchema = () => (
    requestJson(API.parameterSettingsSchema())
);

export const getParameterSettingsConfiguration = (scope) => (
    requestJson(scopedUrl(API.parameterSettingsConfiguration(), scope))
);

export const getParameterSettingsEffective = (scope) => (
    requestJson(scopedUrl(API.parameterSettingsEffective(), scope))
);

export const getParameterSettingsRuntime = (scope) => (
    requestJson(scopedUrl(API.parameterSettingsRuntime(), scope))
);

export const getParameterSettingsStatus = () => (
    requestJson(API.parameterSettingsStatus())
);

/* Read-only Parameter Performance history (E-PERF-3).  These helpers never
   issue a write and never influence configuration authority. */

export const getParameterSettingsPerformance = (scope) => (
    scope
        ? requestJson(scopedUrl(API.parameterSettingsPerformance(), scope))
        : requestJson(API.parameterSettingsPerformance())
);

export const getParameterSettingsPerformanceCompare = (
    scope,
    revisionA,
    revisionB,
) => (
    requestJson(
        `${API.parameterSettingsPerformanceCompare()}`
        + `?scope=${encodeURIComponent(String(scope ?? ""))}`
        + `&revisionA=${encodeURIComponent(String(revisionA ?? ""))}`
        + `&revisionB=${encodeURIComponent(String(revisionB ?? ""))}`,
    )
);

export const updateParameterSettingsConfiguration = async (payload) => {
    try {
        const response = await authenticatedControlRequest(
            API.parameterSettingsConfiguration(),
            {
                method: "PUT",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            },
        );
        return await toResult(response);
    } catch {
        return { ok: false, status: 0, body: null };
    }
};
