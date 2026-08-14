const SOURCE_LABELS = {
    TradingRuntime: "Trading Runtime",
    RuntimeAdapter: "Runtime Data Updated",
    RuntimeState: "Market State Updated",
    "Strategy Plugin": "Strategy Evaluation",
    "AI Plugin": "Trading AI (Optional / Off)",
    "Trading AI (Optional)": "Trading AI (Optional / Off)",
    "Governance Runtime": "Safety / Governance Check",
    "Execution Runtime": "Execution Check",
    Emergency: "Emergency Operation",
};

const REASON_LABELS = {
    LIQUIDITY_DETERIORATION: "Liquidity deterioration",
    AI_HOLD: "AI HOLD",
    IDLE_BY_AI_HOLD: "Waiting — AI HOLD",
    ENABLED_IDLE_BY_AI_HOLD: "Enabled — waiting for AI signal",
    ACCOUNT_EXCHANGE_MISMATCH: "Account exchange mismatch",
    ACCOUNT_GENERATION_MISMATCH: "Account generation mismatch",
    IP_NOT_ALLOWED: "IP not allowed by exchange",
    SUSPENDED_BY_BOT_STOP: "Suspended — bot stopped",
};

export const getRuntimeSourceLabel = (value) => SOURCE_LABELS[value] || value || "SYSTEM";

export const getRuntimeReasonLabel = (value) => {
    if (value === null || value === undefined || value === "") return "--";
    const text = String(value);
    if (REASON_LABELS[text]) return REASON_LABELS[text];
    return /^[A-Z0-9_]+$/.test(text)
        ? text.toLowerCase().replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase())
        : text;
};

export const formatLatency = (value) => {
    if (value === null || value === undefined || value === "") return "--";
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `${numeric.toFixed(2)} ms` : "--";
};

export const getAutoTradeActivity = ({ enabled, emergencyState, runtimeAvailable = true,
    governance, tradingAction, decision, positionActive } = {}) => {
    if (!enabled) return { state: "DISABLED", detail: null };
    if (["LOCKED", "PROCESSING", "ACTION_REQUIRED"].includes(emergencyState)) {
        return { state: "ENABLED", detail: "BLOCKED BY EMERGENCY" };
    }
    if (!runtimeAvailable) return { state: "ENABLED", detail: "RUNTIME UNAVAILABLE" };
    if (String(governance?.status).toUpperCase() === "BLOCKED") {
        return { state: "ENABLED", detail: "BLOCKED BY GOVERNANCE" };
    }
    if (/ORDER|PROCESSING|SUBMITTING/.test(String(tradingAction).toUpperCase())) {
        return { state: "ENABLED", detail: "ORDER PROCESSING" };
    }
    if (positionActive === true) return { state: "ENABLED", detail: "POSITION ACTIVE" };
    if (String(decision).toUpperCase() === "HOLD"
        && String(tradingAction).toUpperCase() === "IDLE_BY_AI_HOLD") {
        return { state: "ENABLED", detail: "WAITING FOR SIGNAL" };
    }
    return { state: "ENABLED", detail: null };
};

export const getLastExecutionActivity = (events = []) => {
    const ordered = Array.isArray(events) ? [...events].reverse() : [];
    const order = ordered.find((event) => /ORDER_(SUBMITTED|SENT|FILLED)|EXECUTED|FILL/.test(
        `${event?.state ?? ""} ${event?.event ?? ""} ${event?.label ?? ""}`.toUpperCase(),
    ));
    if (order) return { label: "LAST ORDER", timestamp: order.timestamp ?? order.time };
    const check = ordered.find((event) => /EXECUTION/.test(String(event?.source).toUpperCase()));
    if (check) return { label: "LAST EXECUTION CHECK", timestamp: check.timestamp ?? check.time };
    return { label: "LAST ORDER", timestamp: null };
};

export const formatActivityTime = (value) => {
    if (!value) return "NONE THIS SESSION";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "NONE THIS SESSION" : date.toLocaleTimeString(undefined, {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
};
