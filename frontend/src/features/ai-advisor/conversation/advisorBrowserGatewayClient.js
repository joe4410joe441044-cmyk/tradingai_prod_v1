export const ADVISOR_CONVERSATION_PATH = "/api/ai-advisor/conversation";
export const ADVISOR_CONVERSATION_STATUS_PATH =
    "/api/ai-advisor/conversation/status";
export const ADVISOR_CONVERSATION_HISTORY_PATH =
    "/api/ai-advisor/conversation/history";
export const ADVISOR_CONVERSATION_CLEAR_PATH =
    "/api/ai-advisor/conversation/clear";
export const ADVISOR_BROWSER_TIMEOUT_MS = 36_000;
export const ADVISOR_CONVERSATION_STORAGE_KEY =
    "tradingai_advisor_conversation";

const SERVER_ROLE_SET = Object.freeze(new Set(["USER", "ADVISOR"]));

export class AdvisorBrowserGatewayError extends Error {
    constructor(code, message, { retryable = false, httpStatus = null } = {}) {
        super(message);
        this.name = "AdvisorBrowserGatewayError";
        this.code = code;
        this.retryable = retryable === true;
        this.httpStatus = httpStatus;
    }
}

const ERROR_CODES = Object.freeze({
    AUTHENTICATION_REQUIRED: "AUTHENTICATION_REQUIRED",
    AUTHORIZATION_DENIED: "ACCESS_DENIED",
    REQUEST_TOO_LARGE: "REQUEST_INVALID",
    REQUEST_INVALID: "REQUEST_INVALID",
    RATE_LIMIT_EXCEEDED: "RATE_LIMITED",
    CONCURRENCY_LIMIT_EXCEEDED: "CONCURRENCY_LIMITED",
    ENDPOINT_TIMEOUT: "TIMED_OUT",
    ENDPOINT_DISABLED: "ENDPOINT_UNAVAILABLE",
    ADVISOR_UNAVAILABLE: "PROVIDER_UNAVAILABLE",
    INTERNAL_ERROR: "INTERNAL_FAILURE",
    ADVISOR_PROVIDER_FAILURE: "PROVIDER_UNAVAILABLE",
    ADVISOR_PROVIDER_RESPONSE_INVALID: "INVALID_PROVIDER_RESPONSE",
    ADVISOR_PARSE_FAILURE: "INVALID_PROVIDER_RESPONSE",
    ADVISOR_RESPONSE_INVALID: "INVALID_PROVIDER_RESPONSE",
});
const STATUS_VALUES = new Set([
    "AVAILABLE", "OFFLINE", "UNAVAILABLE", "AUTHENTICATION_REQUIRED",
]);
const isRecord = (value) => (
    value !== null && typeof value === "object" && !Array.isArray(value)
);

const safeError = (body, status) => {
    const wireCode = isRecord(body) ? body.errorCode || body.failureCode : null;
    return new AdvisorBrowserGatewayError(
        ERROR_CODES[wireCode]
            || (status === 502
                ? "INVALID_PROVIDER_RESPONSE"
                : "UNKNOWN_SAFE_FAILURE"),
        "The advisor request could not be completed.",
        { retryable: body?.retryable === true, httpStatus: status },
    );
};

async function parseJson(response) {
    try {
        return await response.json();
    } catch {
        return null;
    }
}

function validateResponse(body) {
    const envelope = body?.advisorResponse;
    if (!isRecord(body)
        || body.status !== "SUCCEEDED"
        || !isRecord(envelope)
        || envelope.responseVersion !== "1.0"
        || typeof envelope.requestId !== "string"
        || typeof envelope.summary !== "string"
        || !["VALID", "VALID_WITH_WARNINGS", "REJECTED"].includes(envelope.status)) {
        throw new AdvisorBrowserGatewayError(
            "INVALID_PROVIDER_RESPONSE",
            "The advisor returned an invalid response.",
        );
    }
    if (envelope.groundedClaims !== undefined) {
        if (!Array.isArray(envelope.groundedClaims)
            || !Array.isArray(envelope.citations)
            || !Array.isArray(envelope.limitations)
            || !Array.isArray(envelope.actionableUnknowns)) {
            throw new AdvisorBrowserGatewayError(
                "INVALID_PROVIDER_RESPONSE",
                "The advisor returned invalid grounding.",
            );
        }
        const citationIds = new Set(
            envelope.citations.map((citation) => citation?.sourceId),
        );
        for (const claim of envelope.groundedClaims) {
            if (!["FACT", "INTERPRETATION", "INFERENCE", "UNKNOWN"].includes(
                claim?.claimType,
            ) || typeof claim?.text !== "string"
                || !Array.isArray(claim?.citationSourceIds)
                || (claim.claimType !== "UNKNOWN"
                    && claim.citationSourceIds.length === 0)
                || !claim.citationSourceIds.every((id) => citationIds.has(id))) {
                throw new AdvisorBrowserGatewayError(
                    "INVALID_PROVIDER_RESPONSE",
                    "The advisor returned invalid grounding.",
                );
            }
        }
        const unknownClaimIds = new Set(
            envelope.groundedClaims
                .filter((claim) => claim?.claimType === "UNKNOWN")
                .map((claim) => claim.claimId),
        );
        const actionableIds = new Set();
        for (const item of envelope.actionableUnknowns) {
            if (typeof item?.unknownId !== "string"
                || !unknownClaimIds.has(item.unknownId)
                || actionableIds.has(item.unknownId)
                || typeof item?.subject !== "string"
                || typeof item?.reason !== "string"
                || typeof item?.missingInformation !== "string"
                || typeof item?.safeNextStep !== "string"
                || typeof item?.decisionImpact !== "string"
                || item?.operationalEffect !== "NONE") {
                throw new AdvisorBrowserGatewayError(
                    "INVALID_PROVIDER_RESPONSE",
                    "The advisor returned invalid unknown guidance.",
                );
            }
            actionableIds.add(item.unknownId);
        }
        if (actionableIds.size !== unknownClaimIds.size) {
            throw new AdvisorBrowserGatewayError(
                "INVALID_PROVIDER_RESPONSE",
                "The advisor returned incomplete unknown guidance.",
            );
        }
        for (const citation of envelope.citations) {
            if (typeof citation?.displayTitle !== "string"
                || citation.displayTitle.startsWith("/")
                || /https?:\/\//i.test(citation.displayTitle)
                || typeof citation?.version !== "string") {
                throw new AdvisorBrowserGatewayError(
                    "INVALID_PROVIDER_RESPONSE",
                    "The advisor returned an invalid citation.",
                );
            }
        }
    }
    return Object.freeze({ conversationId: body?.conversationId, ...envelope });
}

function readStoredConversationId() {
    try {
        if (typeof localStorage !== "undefined") {
            const value = localStorage.getItem(ADVISOR_CONVERSATION_STORAGE_KEY);
            if (typeof value === "string" && value.length > 0) return value;
        }
    } catch {
        return null;
    }
    return null;
}

function writeStoredConversationId(value) {
    try {
        if (typeof localStorage !== "undefined") {
            if (typeof value === "string" && value.length > 0) {
                localStorage.setItem(ADVISOR_CONVERSATION_STORAGE_KEY, value);
            } else {
                localStorage.removeItem(ADVISOR_CONVERSATION_STORAGE_KEY);
            }
        }
    } catch {
        // Storage failures must never break the advisor request path.
    }
}

function isStoredMessage(value) {
    return isRecord(value)
        && typeof value.messageId === "string"
        && typeof value.content === "string"
        && typeof value.createdAt === "string"
        && SERVER_ROLE_SET.has(value.role);
}

export function createAdvisorBrowserGatewayClient({
    fetchImpl = globalThis.fetch,
    timeoutMs = ADVISOR_BROWSER_TIMEOUT_MS,
    setTimer = setTimeout,
    clearTimer = clearTimeout,
} = {}) {
    const CSRF_TOKEN_COOKIE = "tradingai_csrf";
    const CSRF_TOKEN_HEADER = "X-TradingAI-CSRF";
    let currentConversationId = readStoredConversationId();

    function readCsrfToken() {
        if (typeof document === "undefined") return null;
        const match = document.cookie.match(
            new RegExp(`(?:^|;\\s*)${CSRF_TOKEN_COOKIE}=([^;]*)`),
        );
        return match ? decodeURIComponent(match[1]) : null;
    }

    async function request(path, options, callerSignal) {
        const controller = new AbortController();
        let timedOut = false;
        const abort = () => controller.abort();
        if (callerSignal?.aborted) controller.abort();
        callerSignal?.addEventListener("abort", abort, { once: true });
        const timer = setTimer(() => {
            timedOut = true;
            controller.abort();
        }, timeoutMs);

        const headers = {
            Accept: "application/json",
            "X-TradingAI-Client": "web",
            ...options.headers,
        };

        if (options.method === "POST") {
            const csrfToken = readCsrfToken();
            if (csrfToken) {
                headers[CSRF_TOKEN_HEADER] = csrfToken;
            }
        }

        try {
            if (controller.signal.aborted) {
                throw new AdvisorBrowserGatewayError("CANCELLED", "Request cancelled.");
            }
            return await fetchImpl(path, {
                ...options,
                credentials: "same-origin",
                headers,
                signal: controller.signal,
            });
        } catch (error) {
            if (timedOut) {
                throw new AdvisorBrowserGatewayError("TIMED_OUT", "Request timed out.");
            }
            if (callerSignal?.aborted || error?.name === "AbortError") {
                throw new AdvisorBrowserGatewayError("CANCELLED", "Request cancelled.");
            }
            if (error instanceof AdvisorBrowserGatewayError) throw error;
            throw new AdvisorBrowserGatewayError(
                "ENDPOINT_UNAVAILABLE",
                "AI Advisor is unavailable.",
                { retryable: true },
            );
        } finally {
            clearTimer(timer);
            callerSignal?.removeEventListener("abort", abort);
        }
    }

    async function getConversationHistory(conversationId, { signal } = {}) {
        if (typeof conversationId !== "string"
            || conversationId.length === 0) {
            return Object.freeze({ conversationId: null, messages: Object.freeze([]) });
        }
        const response = await request(
            `${ADVISOR_CONVERSATION_HISTORY_PATH}?conversationId=${encodeURIComponent(conversationId)}`,
            { method: "GET" },
            signal,
        );
        const body = await parseJson(response);
        if (!response.ok) throw safeError(body, response.status);
        if (!isRecord(body)
            || body.status !== "SUCCEEDED"
            || !Array.isArray(body.messages)
            || !body.messages.every(isStoredMessage)) {
            throw new AdvisorBrowserGatewayError(
                "INVALID_PROVIDER_RESPONSE",
                "The advisor history was invalid.",
            );
        }
        return Object.freeze({
            conversationId: body.conversationId,
            messages: Object.freeze(body.messages.map((message) => (
                Object.freeze({ ...message })
            ))),
        });
    }

    return Object.freeze({
        async getStatus({ signal } = {}) {
            const response = await request(
                ADVISOR_CONVERSATION_STATUS_PATH,
                { method: "GET" },
                signal,
            );
            const body = await parseJson(response);
            if (!response.ok) throw safeError(body, response.status);
            if (!isRecord(body) || !STATUS_VALUES.has(body.status)) {
                throw new AdvisorBrowserGatewayError(
                    "INVALID_PROVIDER_RESPONSE",
                    "Advisor status was invalid.",
                );
            }
            return body.status;
        },
        async requestAdvice(prompt, { signal } = {}) {
            if (typeof prompt !== "string") {
                throw new AdvisorBrowserGatewayError(
                    "REQUEST_INVALID",
                    "The request is invalid.",
                );
            }
            const body = { prompt };
            if (typeof currentConversationId === "string"
                && currentConversationId.length > 0) {
                body.conversationId = currentConversationId;
            }
            const response = await request(
                ADVISOR_CONVERSATION_PATH,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                },
                signal,
            );
            const parsed = await parseJson(response);
            if (!response.ok) throw safeError(parsed, response.status);
            const result = validateResponse(parsed);
            if (typeof parsed?.conversationId === "string"
                && parsed.conversationId.length > 0) {
                currentConversationId = parsed.conversationId;
                writeStoredConversationId(parsed.conversationId);
            }
            return result;
        },
        getConversationHistory,
        async loadConversation({ signal } = {}) {
            if (typeof currentConversationId !== "string"
                || currentConversationId.length === 0) {
                return Object.freeze({ conversationId: null, messages: Object.freeze([]) });
            }
            return getConversationHistory(currentConversationId, { signal });
        },
        async clearCurrentConversation({ signal } = {}) {
            if (typeof currentConversationId !== "string"
                || currentConversationId.length === 0) {
                return Object.freeze({ cleared: true, conversationId: null });
            }
            const conversationId = currentConversationId;
            const response = await request(
                ADVISOR_CONVERSATION_CLEAR_PATH,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ conversationId }),
                },
                signal,
            );
            const body = await parseJson(response);
            if (!response.ok) throw safeError(body, response.status);
            currentConversationId = null;
            writeStoredConversationId(null);
            return Object.freeze({
                cleared: body?.cleared === true,
                conversationId,
            });
        },
    });
}
