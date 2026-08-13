const DEFAULT_TIMEOUT_MS = 10_000;

const SUPERVISOR_PROVIDER_STATUS_ENDPOINT = "/api/supervisor/provider/status";
const SUPERVISOR_SNAPSHOT_ENDPOINT = "/api/supervisor/snapshot";

export class SupervisorStatusError extends Error {
    constructor(code, message) {
        super(message);
        this.name = "SupervisorStatusError";
        this.code = code;
    }
}

export const SUPERVISOR_CORE_SEVERITY = {
    AVAILABLE: "normal",
    DEGRADED: "warning",
    UNAVAILABLE: "error",
};

export const LLM_INTERPRETATION_SEVERITY = {
    AVAILABLE: "normal",
    DISABLED: "neutral",
    UNAVAILABLE: "degraded",
    ERROR: "error",
};

export function supervisorCoreSeverity(value) {
    return SUPERVISOR_CORE_SEVERITY[value] ?? "unknown";
}

export function llmInterpretationSeverity(value) {
    return LLM_INTERPRETATION_SEVERITY[value] ?? "unknown";
}

export function normalizeSupervisorProviderStatus(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    return {
        provider: typeof source.provider === "string" ? source.provider : "UNKNOWN",
        supervisorCore: typeof source.supervisorCore === "string" ? source.supervisorCore : "UNKNOWN",
        llmStatus: typeof source.llmStatus === "string" ? source.llmStatus : "UNKNOWN",
        providerConfigured: source.providerConfigured === true,
        providerEnabled: source.providerEnabled === true,
        providerAvailable: source.providerAvailable === true,
        llmInterpretationAvailable: source.llmInterpretationAvailable === true,
        operationalEffect: typeof source.operationalEffect === "string" ? source.operationalEffect : "NONE",
        availability: typeof source.availability === "string" ? source.availability : "UNKNOWN",
        model: typeof source.model === "string" ? source.model : "NONE",
        mode: typeof source.mode === "string" ? source.mode : "SHADOW",
    };
}

export function deriveProviderConnection(status) {
    if (status.providerEnabled && status.providerAvailable && status.llmInterpretationAvailable) {
        return "CONNECTED";
    }
    if (status.providerEnabled && status.providerConfigured) {
        return "ENABLED";
    }
    if (status.providerConfigured) {
        return "DISABLED";
    }
    return "NOT_CONFIGURED";
}

async function requestJson(endpoint, { signal, timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl = globalThis.fetch }) {
    if (typeof fetchImpl !== "function") {
        throw new SupervisorStatusError("NETWORK_UNAVAILABLE", "Supervisor status API is unavailable.");
    }
    const controller = new AbortController();
    const abortFromCaller = () => controller.abort(signal?.reason);
    signal?.addEventListener("abort", abortFromCaller, { once: true });
    const timer = globalThis.setTimeout(() => controller.abort("timeout"), timeoutMs);
    try {
        const response = await fetchImpl(endpoint, { signal: controller.signal });
        const body = await response.json().catch(() => null);
        if (!response.ok || !body) {
            throw new SupervisorStatusError(
                body?.code || "INVALID_RESPONSE",
                body?.message || "Supervisor status is unavailable.",
            );
        }
        return body;
    } catch (error) {
        if (controller.signal.aborted) {
            const code = signal?.aborted ? "CANCELLED" : "TIMEOUT";
            throw new SupervisorStatusError(code, code === "CANCELLED" ? "Request cancelled." : "Request timed out.");
        }
        if (error instanceof SupervisorStatusError) throw error;
        throw new SupervisorStatusError("NETWORK_ERROR", "Supervisor status is unavailable.");
    } finally {
        globalThis.clearTimeout(timer);
        signal?.removeEventListener("abort", abortFromCaller);
    }
}

export async function getSupervisorProviderStatus({ signal, timeoutMs, fetchImpl } = {}) {
    const body = await requestJson(SUPERVISOR_PROVIDER_STATUS_ENDPOINT, { signal, timeoutMs, fetchImpl });
    return normalizeSupervisorProviderStatus(body);
}

export async function getSupervisorSnapshot({ signal, timeoutMs, fetchImpl } = {}) {
    return requestJson(SUPERVISOR_SNAPSHOT_ENDPOINT, { signal, timeoutMs, fetchImpl });
}
