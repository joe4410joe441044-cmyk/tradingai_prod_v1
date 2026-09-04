// frontend/src/runtime/governanceRuntime.js

import {
    authenticatedControlRequest,
    authErrorMessage,
    isAuthErrorStatus,
} from "../features/auth/operatorAuth.js";

const API_BASE =
    "/api/governance";

/* =================================================
   MODE
================================================= */

export async function setMode(
    mode
) {

    const response = await authenticatedControlRequest(

        `${API_BASE}/mode`,

        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json",
            },

            body: JSON.stringify({
                mode,
            }),
        }

    );

    return await response.json();

}
/* =================================================
   EXECUTION ENABLE
================================================= */

export class GovernanceApiError extends Error {
    constructor({
        status = null,
        code = "GOVERNANCE_API_ERROR",
        message = "Governance request failed.",
        data = null,
    } = {}) {
        super(message);

        this.name = "GovernanceApiError";
        this.status = status;
        this.code = code;
        this.data = data;
    }
}

const readJsonSafely = async (
    response
) => {
    try {
        return await response.json();
    } catch {
        return null;
    }
};

const extractGovernanceErrorCode = (
    data
) => {
    const detail = data?.detail;

    if (
        detail
        && typeof detail === "object"
        && !Array.isArray(detail)
    ) {
        return (
            detail.reason
            || detail.code
            || detail.error_code
            || "GOVERNANCE_API_ERROR"
        );
    }

    return (
        data?.reason
        || data?.code
        || data?.error_code
        || (
            typeof detail === "string"
                ? detail
                : null
        )
        || "GOVERNANCE_API_ERROR"
    );
};

const extractGovernanceErrorMessage = (
    data,
    fallback
) => {
    const detail = data?.detail;

    if (typeof detail === "string") {
        return detail;
    }

    if (
        detail
        && typeof detail === "object"
        && !Array.isArray(detail)
    ) {
        return (
            detail.message
            || detail.reason
            || fallback
        );
    }

    return (
        data?.message
        || data?.error
        || fallback
    );
};

export async function setExecutionEnabled(
    enabled
) {

    let response;

    try {
        response = await authenticatedControlRequest(

            `${API_BASE}/execution`,

            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body: JSON.stringify({
                    enabled,
                }),
            }

        );
    } catch (error) {
        throw new GovernanceApiError({
            status: null,
            code: "NETWORK_ERROR",
            message: "Unable to reach the server.",
            data: {
                error: error?.message || String(error),
            },
        });
    }

    const data = await readJsonSafely(
        response
    );

    if (!response.ok) {
        if (isAuthErrorStatus(response.status)) {
            throw new GovernanceApiError({
                status: response.status,
                code: response.status === 403
                    ? "AUTHORIZATION_DENIED"
                    : "AUTHENTICATION_REQUIRED",
                message: authErrorMessage(response.status),
                data,
            });
        }
        throw new GovernanceApiError({
            status: response.status,
            code: extractGovernanceErrorCode(
                data
            ),
            message: extractGovernanceErrorMessage(
                data,
                "Governance request failed."
            ),
            data,
        });
    }

    if (!data) {
        throw new GovernanceApiError({
            status: response.status,
            code: "MALFORMED_RESPONSE",
            message: "Governance response was not valid JSON.",
            data: null,
        });
    }

    if (
        data.success !== true
        || typeof data.execution_enabled !== "boolean"
    ) {
        throw new GovernanceApiError({
            status: response.status,
            code: extractGovernanceErrorCode(
                data
            ),
            message: extractGovernanceErrorMessage(
                data,
                "Governance response did not confirm Auto Trade state."
            ),
            data,
        });
    }

    return data;

}

/* =================================================
   EMERGENCY ORCHESTRATOR
================================================= */

const hasOwn = (
    value,
    key
) => (
    Object.prototype.hasOwnProperty.call(
        value,
        key,
    )
);

const validateEmergencyOrchestratorResponse = (
    data
) => {
    if (
        !data
        || typeof data !== "object"
        || Array.isArray(data)
    ) {
        return false;
    }

    const booleanFields = [
        "success",
        "completed",
        "partial",
        "state_unknown",
        "emergency_locked",
        "auto_trade_disabled",
        "retryable",
    ];

    for (const field of booleanFields) {
        if (
            !hasOwn(data, field)
            || typeof data[field] !== "boolean"
        ) {
            return false;
        }
    }

    if (
        !hasOwn(data, "position_remaining")
        || (
            data.position_remaining !== null
            && typeof data.position_remaining !== "boolean"
        )
    ) {
        return false;
    }

    if (!hasOwn(data, "error_code")) {
        return false;
    }

    return true;
};

export function classifyEmergencyResult(
    result
) {
    if (
        !result
        || typeof result !== "object"
        || Array.isArray(result)
    ) {
        return {
            key: "failed",
            label: "EMERGENCY FAILED",
            text: "EMERGENCY FAILED（緊急処理に失敗しました）",
            severity: "danger",
        };
    }

    if (result.state_unknown === true) {
        return {
            key: "state_unknown",
            label: "EXCHANGE STATE UNKNOWN",
            text: "EXCHANGE STATE UNKNOWN（取引所状態を確認できません）",
            severity: "danger",
        };
    }

    if (result.position_remaining === true) {
        return {
            key: "position_remaining",
            label: "POSITION MAY REMAIN",
            text: "POSITION MAY REMAIN（Positionが残っている可能性があります）",
            severity: "danger",
        };
    }

    if (result.partial === true) {
        return {
            key: "partial",
            label: "PARTIAL COMPLETION",
            text: "PARTIAL COMPLETION（一部処理のみ完了）",
            severity: "warning",
        };
    }

    if (
        result.completed === true
        && result.partial !== true
        && result.position_remaining !== true
        && result.state_unknown !== true
    ) {
        return {
            key: "completed",
            label: "EMERGENCY COMPLETED",
            text: "EMERGENCY COMPLETED（緊急処理完了）",
            severity: "safe",
        };
    }

    return {
        key: "failed",
        label: "EMERGENCY FAILED",
        text: "EMERGENCY FAILED（緊急処理に失敗しました）",
        severity: "danger",
    };
}

export async function runEmergencyOrchestrator() {

    let response;

    try {
        response = await authenticatedControlRequest(
            `${API_BASE}/emergency-orchestrate`,
            {
                method: "POST",
            }
        );
    } catch (error) {
        throw new GovernanceApiError({
            status: null,
            code: "NETWORK_ERROR",
            message: "Unable to reach the server.",
            data: {
                error: error?.message || String(error),
            },
        });
    }

    const data = await readJsonSafely(
        response
    );

    if (!response.ok) {
        if (isAuthErrorStatus(response.status)) {
            throw new GovernanceApiError({
                status: response.status,
                code: response.status === 403
                    ? "AUTHORIZATION_DENIED"
                    : "AUTHENTICATION_REQUIRED",
                message: authErrorMessage(response.status),
                data,
            });
        }
        throw new GovernanceApiError({
            status: response.status,
            code: extractGovernanceErrorCode(
                data
            ),
            message: extractGovernanceErrorMessage(
                data,
                "Emergency request failed."
            ),
            data,
        });
    }

    if (
        !data
        || !validateEmergencyOrchestratorResponse(data)
    ) {
        throw new GovernanceApiError({
            status: response.status,
            code: "MALFORMED_RESPONSE",
            message: "Emergency response could not be verified.",
            data,
        });
    }

    return data;

}

export async function unlockEmergency() {

    let response;

    try {
        response = await authenticatedControlRequest(
            `${API_BASE}/emergency/unlock`,
            {
                method: "POST",
            }
        );
    } catch (error) {
        throw new GovernanceApiError({
            status: null,
            code: "NETWORK_ERROR",
            message: "Unable to reach the server.",
            data: {
                error: error?.message || String(error),
            },
        });
    }

    const data = await readJsonSafely(
        response
    );

    if (!response.ok) {
        if (isAuthErrorStatus(response.status)) {
            throw new GovernanceApiError({
                status: response.status,
                code: response.status === 403
                    ? "AUTHORIZATION_DENIED"
                    : "AUTHENTICATION_REQUIRED",
                message: authErrorMessage(response.status),
                data,
            });
        }
        throw new GovernanceApiError({
            status: response.status,
            code: extractGovernanceErrorCode(
                data
            ),
            message: extractGovernanceErrorMessage(
                data,
                "Emergency unlock failed."
            ),
            data,
        });
    }

    if (
        !data
        || data.success !== true
        || data.unlocked !== true
    ) {
        throw new GovernanceApiError({
            status: response.status,
            code: extractGovernanceErrorCode(
                data
            ),
            message: extractGovernanceErrorMessage(
                data,
                "Emergency unlock response could not be verified."
            ),
            data,
        });
    }

    return data;

}

/* =================================================
   RISK PROFILE
================================================= */

export async function setRiskProfile(
    profile
) {

    const response = await authenticatedControlRequest(

        `${API_BASE}/risk-profile`,

        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json",
            },

            body: JSON.stringify({
                risk_profile:
                    profile,
            }),
        }

    );

    return await response.json();

}

/* =================================================
   EMERGENCY STOP
================================================= */

export async function triggerEmergencyStop() {

    const response = await authenticatedControlRequest(

        `${API_BASE}/emergency-stop`,

        {
            method: "POST",
        }

    );

    return await response.json();

}

/* =================================================
   GOVERNANCE STATUS
================================================= */

export async function getGovernanceStatus() {

    const response = await fetch(

        `${API_BASE}/status`

    );

    return await response.json();

}
