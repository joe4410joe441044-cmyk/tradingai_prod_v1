import { formatLatency } from "../../runtime/runtimeDisplay";

const STATUS_CLASS = {
    HEALTHY: "status-safe",
    RUNNING: "status-safe",
    DEGRADED: "status-warning",
    WARNING: "status-warning",
    CRITICAL: "status-danger",
    ERROR: "status-danger",
    STOPPED: "status-warning",
    DISABLED: "status-warning",
};

const resolveStatusClass = (value) => STATUS_CLASS[value] || "";

const display = (value) => {
    if (value === null || value === undefined || value === "") return "--";
    return String(value);
};

const isAvailable = (value) => {
    if (value === null || value === undefined || value === "") return false;
    const upper = String(value).toUpperCase().trim();
    return upper !== "NONE" && upper !== "UNKNOWN" && upper !== "--";
};

export default function RuntimeOverviewPanel({
    runtimeHealth,
    displayedHealth,
    displayedBlockingReason,
    browserWsConnected,
}) {
    const healthLabel = displayedHealth || runtimeHealth?.health || "UNKNOWN";
    const botRunning = runtimeHealth?.running === true;
    const botStateLabel = botRunning ? "RUNNING" : "STOPPED";
    const botStateClass = botRunning ? "status-safe" : "status-warning";

    const currentStageId = runtimeHealth?.activeStageId;
    const currentStage = runtimeHealth?.stages?.find(
        (s) => s.id === currentStageId,
    ) ?? runtimeHealth?.stages?.[0];
    const stageName = currentStage?.name || "--";
    const stageStatus = currentStage?.status || "--";
    const stageStatusClass = resolveStatusClass(stageStatus);

    const currentDecision = runtimeHealth?.tradingAction?.decision;
    const currentAction = runtimeHealth?.tradingAction?.status;
    const actionReason = runtimeHealth?.tradingAction?.reason;

    const pipelineStatus = runtimeHealth?.pipelineStatus;
    const latencyMs = runtimeHealth?.latencyMs;

    const lastUpdate = runtimeHealth?.generatedAt
        ? new Date(runtimeHealth.generatedAt).toLocaleTimeString()
        : runtimeHealth?.snapshotId
            ? runtimeHealth.snapshotId
            : "--";

    const reason = isAvailable(displayedBlockingReason)
        ? displayedBlockingReason
        : isAvailable(actionReason)
            ? actionReason
            : isAvailable(runtimeHealth?.blockingReason)
                ? runtimeHealth.blockingReason
                : "--";

    const items = [
        {
            label: "RUNTIME HEALTH",
            value: healthLabel,
            className: resolveStatusClass(healthLabel),
        },
        {
            label: "BOT STATE",
            value: botStateLabel,
            className: botStateClass,
        },
        {
            label: "CURRENT STAGE",
            value: stageName,
            className: "",
        },
        {
            label: "CURRENT DECISION",
            value: display(currentDecision),
            className: "",
        },
        {
            label: "CURRENT ACTION",
            value: display(currentAction),
            className: currentAction === "ORDER_SUBMITTED" ? "status-safe" : "",
        },
        {
            label: "PIPELINE",
            value: display(pipelineStatus),
            className: pipelineStatus === "OK" ? "status-safe" : "",
        },
        {
            label: "LATENCY",
            value: formatLatency(latencyMs),
            className: "",
        },
        {
            label: "LAST UPDATE",
            value: lastUpdate,
            className: "",
        },
        {
            label: "REASON",
            value: reason,
            className: "",
        },
    ];

    return (
        <section className="runtime-overview-panel">
            <div className="governance-card-title">
                RUNTIME OVERVIEW
            </div>

            <div className="runtime-overview-grid">
                {items.map((item) => (
                    <div className="runtime-overview-cell" key={item.label}>
                        <span className="runtime-overview-label">
                            {item.label}
                        </span>
                        <span
                            className={`runtime-overview-value ${item.className}`}
                            title={item.value}
                        >
                            {item.value}
                        </span>
                    </div>
                ))}
            </div>
        </section>
    );
}
