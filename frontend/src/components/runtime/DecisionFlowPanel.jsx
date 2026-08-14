const FLOW_STAGES = [
    { id: "market", label: "MARKET", sourceKey: "marketFeed" },
    { id: "strategy", label: "STRATEGY", sourceKey: "strategy" },
    { id: "ai-advisor", label: "AI ADVISOR", sourceKey: "ai" },
    { id: "money-management", label: "MONEY MANAGEMENT", sourceKey: "moneyManagement" },
    { id: "governance", label: "GOVERNANCE", sourceKey: "governance" },
    { id: "execution", label: "EXECUTION", sourceKey: "executionEngine" },
    { id: "recorder", label: "RECORDER", sourceKey: "recorder" },
];

const STATUS_COLOR_MAP = {
    OK: "flow-ok",
    REACHED: "flow-ok",
    COMPLETED: "flow-ok",
    SUCCESS: "flow-ok",
    HEALTHY: "flow-ok",
    RUNNING: "flow-running",
    ACTIVE: "flow-running",
    PROCESSING: "flow-running",
    EVALUATED: "flow-running",
    CONNECTED: "flow-running",
    WAIT: "flow-hold",
    WAITING: "flow-hold",
    IDLE: "flow-hold",
    HOLD: "flow-hold",
    SUSPENDED: "flow-hold",
    STOPPED: "flow-stopped",
    DISABLED: "flow-stopped",
    BLOCKED: "flow-stopped",
    DEGRADED: "flow-warning",
    WARNING: "flow-warning",
    ERROR: "flow-error",
    CRITICAL: "flow-error",
    FAILURE: "flow-error",
    EXCEPTION: "flow-error",
    UNAVAILABLE: "flow-unavailable",
    UNKNOWN: "flow-unavailable",
    "NOT STARTED": "flow-unavailable",
    "NOT ACTIVE": "flow-unavailable",
    PENDING: "flow-unavailable",
};

const LOOP_STATUS_OVERRIDES = {
    "money-management": ["money_management", "money-management", "portfolio-sync"],
    recorder: ["recorder", "market-recorder"],
};

const classifyStatus = (value) => {
    if (value === null || value === undefined || value === "") {
        return { label: "N/A", color: "flow-unavailable" };
    }
    const upper = String(value).toUpperCase().trim();
    const color = STATUS_COLOR_MAP[upper] || "flow-unavailable";
    return { label: upper, color };
};

const findLoopStatus = (loops, stageId) => {
    const keys = LOOP_STATUS_OVERRIDES[stageId];
    if (!keys) return null;
    for (const loop of loops) {
        const id = String(loop.id || "").toLowerCase();
        if (keys.some((k) => id.includes(k))) {
            return loop.status;
        }
    }
    return null;
};

export default function DecisionFlowPanel({ runtimeHealth }) {
    const loops = runtimeHealth?.loops || [];

    return (
        <section className="decision-flow-panel">
            <div className="governance-card-title">
                DECISION FLOW
            </div>

            <div className="decision-flow-list">
                {FLOW_STAGES.map((stage, index) => {
                    const source = runtimeHealth?.[stage.sourceKey];
                    const loopStatus = findLoopStatus(loops, stage.id);
                    const rawStatus = source?.status
                        || loopStatus
                        || runtimeHealth?.pipelineStatus;
                    const { label, color } = classifyStatus(rawStatus);

                    return (
                        <div className="decision-flow-row" key={stage.id}>
                            {index > 0 && (
                                <div className="decision-flow-arrow">
                                    <span className="flow-arrow-line" />
                                    <span className="flow-arrow-head">▼</span>
                                </div>
                            )}
                            <div className="decision-flow-item">
                                <span className="decision-flow-label">
                                    {stage.label}
                                </span>
                                <span
                                    className={`decision-flow-status ${color}`}
                                    title={label}
                                >
                                    {label}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
