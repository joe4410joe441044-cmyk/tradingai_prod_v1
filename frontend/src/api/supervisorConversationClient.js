const DEFAULT_TIMEOUT_MS = 10_000;

export class SupervisorConversationError extends Error {
    constructor(code, message) {
        super(message);
        this.name = "SupervisorConversationError";
        this.code = code;
    }
}

export function createConversationId(agentId) {
    const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${agentId.toLowerCase()}-${suffix}`;
}

export async function sendSupervisorConversation({
    agentId,
    message,
    conversationId,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    fetchImpl = globalThis.fetch,
}) {
    if (typeof fetchImpl !== "function") {
        throw new SupervisorConversationError("NETWORK_UNAVAILABLE", "Conversation API is unavailable.");
    }
    const endpoint = agentId === "MASTER_SUPERVISOR"
        ? "/api/supervisor/conversation/master"
        : agentId === "MM_SUPERVISOR"
            ? "/api/supervisor/conversation/mm"
            : null;
    if (!endpoint) {
        throw new SupervisorConversationError("UNKNOWN_AGENT", "Unknown Supervisor agent.");
    }

    const controller = new AbortController();
    const abortFromCaller = () => controller.abort(signal?.reason);
    signal?.addEventListener("abort", abortFromCaller, { once: true });
    const timer = globalThis.setTimeout(() => controller.abort("timeout"), timeoutMs);
    try {
        const response = await fetchImpl(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                schemaVersion: 1,
                agentId,
                message,
                conversationId,
                requestedAt: new Date().toISOString(),
            }),
            signal: controller.signal,
        });
        const body = await response.json().catch(() => null);
        if (!response.ok || !body || body.operationalEffect !== "NONE" || body.mode !== "SHADOW") {
            throw new SupervisorConversationError(
                body?.code || "INVALID_RESPONSE",
                body?.message || "Supervisor response is unavailable.",
            );
        }
        return body;
    } catch (error) {
        if (controller.signal.aborted) {
            const code = signal?.aborted ? "CANCELLED" : "TIMEOUT";
            throw new SupervisorConversationError(code, code === "CANCELLED" ? "Request cancelled." : "Request timed out.");
        }
        if (error instanceof SupervisorConversationError) throw error;
        throw new SupervisorConversationError("NETWORK_ERROR", "Supervisor response is unavailable.");
    } finally {
        globalThis.clearTimeout(timer);
        signal?.removeEventListener("abort", abortFromCaller);
    }
}
