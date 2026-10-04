const BUFFER_LIMIT = 64;
const GLOBAL_KEY = "__TRADINGAI_START_CHAIN_DIAGNOSTICS__";

export const START_CHAIN_EVENTS = Object.freeze({
    START_CLICK: "START_CLICK",
    LIVE_MODAL_OPEN: "LIVE_MODAL_OPEN",
    LIVE_CONFIRM_GATE: "LIVE_CONFIRM_GATE",
    LIVE_CONFIRM_CLICK: "LIVE_CONFIRM_CLICK",
    CONFIRM_HANDLER_ENTER: "CONFIRM_HANDLER_ENTER",
    EXECUTE_BOT_START_ENTER: "EXECUTE_BOT_START_ENTER",
    API_START_CALL: "API_START_CALL",
    API_START_RESPONSE: "API_START_RESPONSE",
});

const allowedEventNames = new Set(Object.values(START_CHAIN_EVENTS));
const events = [];
let sequence = 0;

const safeMetadata = (metadata) => {
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
        return {};
    }

    return Object.fromEntries(
        Object.entries(metadata).filter(([, value]) => (
            value === null
            || ["boolean", "number", "string"].includes(typeof value)
        )),
    );
};

export const getStartChainDiagnosticSnapshot = () => events.map(
    (event) => ({ ...event }),
);

export const resetStartChainDiagnosticsForTest = () => {
    events.length = 0;
    sequence = 0;
};

export const recordStartChainDiagnostic = (eventName, metadata = {}) => {
    try {
        if (!allowedEventNames.has(eventName)) return null;
        const event = Object.freeze({
            ...safeMetadata(metadata),
            event: eventName,
            timestamp: new Date().toISOString(),
            sequence: sequence += 1,
        });
        events.push(event);
        if (events.length > BUFFER_LIMIT) {
            events.splice(0, events.length - BUFFER_LIMIT);
        }
        return event;
    } catch {
        return null;
    }
};

try {
    if (typeof globalThis === "object" && !globalThis[GLOBAL_KEY]) {
        Object.defineProperty(globalThis, GLOBAL_KEY, {
            configurable: true,
            enumerable: false,
            value: Object.freeze({ snapshot: getStartChainDiagnosticSnapshot }),
            writable: false,
        });
    }
} catch {
    // Browser diagnostics are best-effort and never participate in authority.
}
