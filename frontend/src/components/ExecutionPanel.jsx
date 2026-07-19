import { formatLatency } from "../runtime/runtimeDisplay";

const EMPTY_VALUES = new Set([
    "UNKNOWN",
    "NO DATA",
    "NONE",
    "UNDEFINED",
]);

const displayValue = (value) => {
    if (value === null || value === undefined || value === "") {
        return "--";
    }

    if (EMPTY_VALUES.has(String(value).trim().toUpperCase())) {
        return "--";
    }

    return String(value);
};

export default function ExecutionPanel({
    executionStatus = "UNKNOWN",
    runtimePhase,
    websocketStatus,
    latency,
}) {
    const metrics = [
        {
            label: "STATUS（状態）",
            value: executionStatus,
            className: ["READY", "EXECUTED", "ENABLED_IDLE_BY_AI_HOLD"].includes(
                executionStatus,
            ) ? "terminal-green" : "terminal-red",
        },
        { label: "PHASE（実行段階）", value: displayValue(runtimePhase) },
        { label: "WS（通信）", value: displayValue(websocketStatus) },
        { label: "LATENCY（遅延）", value: formatLatency(latency) },
    ];

    return (
        <section className="terminal-monitor-section execution-runtime-panel">
            <div className="terminal-section-header">
                3 | Execution Runtime
            </div>

            <div className="execution-runtime-grid">
                {metrics.map((metric) => (
                    <div className="runtime-metric" key={metric.label}>
                        <span className="runtime-metric-label">
                            {metric.label}
                        </span>
                        <span className={`runtime-metric-value ${metric.className ?? ""}`}>
                            {metric.value}
                        </span>
                    </div>
                ))}
            </div>
        </section>
    );
}
