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
    executionAllowed = false,
    runtimePhase,
    websocketStatus,
    latency,
    balance,
    equity,
    positionSide,
}) {
    const metrics = [
        {
            label: "STATUS（状態）",
            value: executionAllowed ? "ON" : "OFF",
            className: executionAllowed ? "terminal-green" : "terminal-red",
        },
        { label: "PHASE（実行段階）", value: displayValue(runtimePhase) },
        { label: "WS（通信）", value: displayValue(websocketStatus) },
        { label: "LATENCY（遅延）", value: displayLatency(latency) },
        { label: "BALANCE（残高）", value: displayAmount(balance) },
        { label: "EQUITY（純資産）", value: displayAmount(equity) },
        { label: "POSITION（ポジション）", value: displayValue(positionSide) },
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
