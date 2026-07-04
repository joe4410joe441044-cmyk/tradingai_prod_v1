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

const displayAmount = (value) => {
    const numericValue = Number(value);

    if (value === null || value === undefined || !Number.isFinite(numericValue)) {
        return "--";
    }

    return numericValue.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
};

const displayLatency = (value) => {
    if (value === null || value === undefined || value === "") {
        return "--";
    }

    return typeof value === "number" ? `${value} ms` : String(value);
};

export default function ExecutionPanel({
    executionStatus = "UNKNOWN",
    runtimePhase,
    websocketStatus,
    latency,
    balance,
    equity,
    positionSide,
    accountSource,
}) {
    const paperSource = accountSource === "PAPER_SIMULATION";
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
        { label: "LATENCY（遅延）", value: displayLatency(latency) },
        {
            label: "Paper Balance:（模擬残高）",
            value: displayAmount(paperSource ? balance : undefined),
        },
        {
            label: "Paper Equity:（模擬純資産）",
            value: displayAmount(paperSource ? equity : undefined),
        },
        {
            label: "Paper Position:（模擬ポジション）",
            value: displayValue(paperSource ? positionSide : undefined),
        },
        { label: "Source:（データソース）", value: displayValue(accountSource) },
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
