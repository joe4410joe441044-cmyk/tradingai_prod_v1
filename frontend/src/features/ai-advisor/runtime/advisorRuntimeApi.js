import { API } from "../../../api/index.js";

export const ADVISOR_RUNTIME_TIMEOUT_MS = 5000;

export class AdvisorRuntimeApiError extends Error {
    constructor({
        code,
        message,
        retryable,
        requestId = null,
        occurredAt = null,
        httpStatus = null,
    }) {
        super(message);
        this.name = "AdvisorRuntimeApiError";
        this.code = code;
        this.retryable = retryable;
        this.requestId = requestId;
        this.occurredAt = occurredAt;
        this.httpStatus = httpStatus;
    }
}

const safeError = (body, httpStatus) => {
    const detail = body?.error;
    const wireCode = typeof body?.errorCode === "string" ? body.errorCode : null;
    const code = typeof detail?.code === "string"
        ? detail.code
        : wireCode || "ADVISOR_RUNTIME_REQUEST_FAILED";
    const message = typeof detail?.message === "string"
        ? detail.message
        : typeof body?.safeMessage === "string"
            ? body.safeMessage
            : "Runtime status is unavailable.";
    const retryable = detail?.retryable === true || body?.retryable === true;
    return new AdvisorRuntimeApiError({
        code,
        message,
        retryable,
        requestId: typeof detail?.requestId === "string"
            ? detail.requestId
            : null,
        occurredAt: typeof detail?.occurredAt === "string"
            ? detail.occurredAt
            : null,
        httpStatus,
    });
};

export async function fetchAdvisorRuntime({
    signal,
    timeoutMs = ADVISOR_RUNTIME_TIMEOUT_MS,
    fetchImpl = globalThis.fetch,
    now = Date.now,
} = {}) {
    const controller = new AbortController();
    let timedOut = false;
    const abortFromCaller = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener("abort", abortFromCaller, { once: true });
    const timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, timeoutMs);

    try {
        const response = await fetchImpl(API.aiAdvisorRuntime(), {
            method: "GET",
            credentials: "same-origin",
            headers: {
                Accept: "application/json",
                "X-TradingAI-Client": "web",
            },
            signal: controller.signal,
        });
        let body = null;
        try {
            body = await response.json();
        } catch {
            body = null;
        }
        if (!response.ok) throw safeError(body, response.status);
        if (!body || typeof body !== "object" || Array.isArray(body)) {
            throw new AdvisorRuntimeApiError({
                code: "INVALID_RESPONSE",
                message: "Runtime status response was invalid.",
                retryable: true,
                httpStatus: response.status,
            });
        }
        return { raw: body, receivedAt: now() };
    } catch (error) {
        if (timedOut) {
            throw new AdvisorRuntimeApiError({
                code: "REQUEST_TIMEOUT",
                message: "Runtime status request timed out.",
                retryable: true,
            });
        }
        throw error;
    } finally {
        clearTimeout(timeoutId);
        signal?.removeEventListener("abort", abortFromCaller);
    }
}
