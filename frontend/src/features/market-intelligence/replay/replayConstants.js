export const REPLAY_EVENT_TYPES = Object.freeze([
    "MARKET_SNAPSHOT",
    "DETECTOR_SIGNAL",
    "STRATEGY_DECISION",
    "AI_DECISION",
    "GOVERNANCE_DECISION",
    "ORDER_SUBMITTED",
    "ORDER_ACKNOWLEDGED",
    "POSITION_OPENED",
    "POSITION_UPDATED",
    "POSITION_CLOSED",
    "EXECUTION_REJECTED",
]);

export const REPLAY_EVENT_SOURCES = Object.freeze([
    "MARKET",
    "DETECTOR",
    "STRATEGY",
    "AI",
    "GOVERNANCE",
    "EXECUTION",
    "POSITION",
    "SYSTEM",
]);

export const REPLAY_DATA_QUALITY = Object.freeze([
    "UNKNOWN",
    "VALID",
    "PARTIAL",
    "STALE",
    "INVALID",
]);
