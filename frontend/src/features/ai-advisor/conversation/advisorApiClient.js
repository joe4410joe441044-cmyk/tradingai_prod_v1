import {
    AdvisorAuthenticationUnavailableError,
    isAdvisorAuthProviderAvailable,
} from "./advisorAuth.js";

export const ADVISOR_ADVICE_PATH = "/api/ai-advisor/advice";
// Backend owns a 35 second deadline; one second permits its safe timeout response.
export const ADVISOR_CLIENT_TIMEOUT_MS = 36_000;

export class AdvisorApiError extends Error {
    constructor(code, message, { retryable = false, httpStatus = null } = {}) {
        super(message);
        this.name = "AdvisorApiError";
        this.code = code;
        this.retryable = retryable === true;
        this.httpStatus = httpStatus;
    }
}

const HTTP_CODE_MAP = Object.freeze({
    AUTHENTICATION_REQUIRED: "AUTHENTICATION_REQUIRED",
    AUTHORIZATION_DENIED: "ACCESS_DENIED",
    REQUEST_INVALID: "REQUEST_INVALID",
    REQUEST_TOO_LARGE: "REQUEST_INVALID",
    RATE_LIMIT_EXCEEDED: "RATE_LIMITED",
    CONCURRENCY_LIMIT_EXCEEDED: "CONCURRENCY_LIMITED",
    ENDPOINT_TIMEOUT: "TIMED_OUT",
    ENDPOINT_DISABLED: "ENDPOINT_UNAVAILABLE",
    ADVISOR_UNAVAILABLE: "PROVIDER_UNAVAILABLE",
    INTERNAL_ERROR: "INTERNAL_FAILURE",
});

const FAILURE_CODE_MAP = Object.freeze({
    ADVISOR_INVALID_CONVERSATION: "REQUEST_INVALID",
    ADVISOR_CONTEXT_INVALID: "REQUEST_INVALID",
    ADVISOR_PROMPT_INVALID: "REQUEST_INVALID",
    ADVISOR_PROVIDER_REQUEST_INVALID: "REQUEST_INVALID",
    ADVISOR_PROVIDER_FAILURE: "PROVIDER_UNAVAILABLE",
    ADVISOR_PROVIDER_RESPONSE_INVALID: "INVALID_PROVIDER_RESPONSE",
    ADVISOR_PARSE_FAILURE: "INVALID_PROVIDER_RESPONSE",
    ADVISOR_RESPONSE_INVALID: "INVALID_PROVIDER_RESPONSE",
});

const isRecord = (value) => (
    value !== null && typeof value === "object" && !Array.isArray(value)
);
const hasOnlyKeys = (value, allowed) => (
    Object.keys(value).every((key) => allowed.includes(key))
);

function validateEnvelope(value) {
    const keys = [
        "responseVersion", "requestId", "promptVersion", "receivedAt", "status",
        "summary", "facts", "inferences", "unknowns", "warnings",
        "sourceReferences", "freshnessDisclosures", "safetyDisclosures",
        "forbiddenClaims", "validationWarnings", "primaryRejectionReason",
        "responseCategory", "conclusion", "groundedClaims", "citations",
        "limitations", "safeAlternative", "refusalCategory",
    ];
    const arrays = [
        "facts", "inferences", "unknowns", "warnings", "sourceReferences",
        "freshnessDisclosures", "safetyDisclosures", "forbiddenClaims",
        "validationWarnings",
    ];
    return isRecord(value)
        && hasOnlyKeys(value, keys)
        && value.responseVersion === "1.0"
        && typeof value.requestId === "string"
        && typeof value.promptVersion === "string"
        && typeof value.receivedAt === "string"
        && ["VALID", "VALID_WITH_WARNINGS", "REJECTED"].includes(value.status)
        && typeof value.summary === "string"
        && arrays.every((field) => Array.isArray(value[field]))
        && (value.primaryRejectionReason === null
            || typeof value.primaryRejectionReason === "string");
}

function parseSuccess(body) {
    if (!isRecord(body)
        || !hasOnlyKeys(body, ["status", "advisorResponse", "failureCode", "safeMessage"])
        || body.status !== "SUCCEEDED"
        || !validateEnvelope(body.advisorResponse)
        || body.failureCode != null
        || body.safeMessage != null) {
        throw new AdvisorApiError(
            "INVALID_PROVIDER_RESPONSE",
            "The advisor returned an invalid response.",
        );
    }
    return Object.freeze({ ...body.advisorResponse });
}

function mappedError(body, httpStatus) {
    const wireCode = isRecord(body)
        ? (typeof body.errorCode === "string" ? body.errorCode : body.failureCode)
        : null;
    const code = HTTP_CODE_MAP[wireCode]
        || FAILURE_CODE_MAP[wireCode]
        || (httpStatus === 502 ? "INVALID_PROVIDER_RESPONSE" : "UNKNOWN_SAFE_FAILURE");
    return new AdvisorApiError(code, "The advisor request could not be completed.", {
        retryable: body?.retryable === true,
        httpStatus,
    });
}

export function createAdvisorApiClient({
    authProvider,
    fetchImpl = globalThis.fetch,
    timeoutMs = ADVISOR_CLIENT_TIMEOUT_MS,
    setTimer = setTimeout,
    clearTimer = clearTimeout,
} = {}) {
    return Object.freeze({
        async requestAdvice(serviceInput, { signal } = {}) {
            if (!isAdvisorAuthProviderAvailable(authProvider)) {
                throw new AdvisorApiError(
                    "AUTHENTICATION_REQUIRED",
                    "Authentication is required before sending.",
                );
            }
            const authorization = await authProvider.getAuthorizationHeader();
            if (typeof authorization !== "string"
                || !authorization.startsWith("Bearer ")
                || authorization.length <= 7) {
                throw new AdvisorAuthenticationUnavailableError();
            }
            if (!isRecord(serviceInput)) {
                throw new AdvisorApiError("REQUEST_INVALID", "The request is invalid.");
            }

            const controller = new AbortController();
            let timedOut = false;
            const abort = () => controller.abort();
            if (signal?.aborted) controller.abort();
            signal?.addEventListener("abort", abort, { once: true });
            const timer = setTimer(() => {
                timedOut = true;
                controller.abort();
            }, timeoutMs);
            try {
                if (controller.signal.aborted) {
                    throw new AdvisorApiError(
                        "CANCELLED",
                        "The advisor request was cancelled.",
                    );
                }
                const response = await fetchImpl(ADVISOR_ADVICE_PATH, {
                    method: "POST",
                    headers: {
                        Accept: "application/json",
                        Authorization: authorization,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ serviceInput }),
                    signal: controller.signal,
                });
                let body = null;
                try {
                    body = await response.json();
                } catch {
                    body = null;
                }
                if (!response.ok) throw mappedError(body, response.status);
                return parseSuccess(body);
            } catch (error) {
                if (timedOut) {
                    throw new AdvisorApiError("TIMED_OUT", "The advisor request timed out.");
                }
                if (signal?.aborted || error?.name === "AbortError") {
                    throw new AdvisorApiError("CANCELLED", "The advisor request was cancelled.");
                }
                if (error instanceof AdvisorApiError) throw error;
                throw new AdvisorApiError(
                    "ENDPOINT_UNAVAILABLE",
                    "AI Advisor is currently unavailable.",
                    { retryable: true },
                );
            } finally {
                clearTimer(timer);
                signal?.removeEventListener("abort", abort);
            }
        },
    });
}
