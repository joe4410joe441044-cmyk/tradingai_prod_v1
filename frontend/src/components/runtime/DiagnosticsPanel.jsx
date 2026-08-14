import { useState } from "react";

const isMeaningful = (value) => {
    if (value === null || value === undefined || value === "") return false;
    if (value === "None" || value === "NONE") return false;
    if (value === "--") return false;
    return true;
};

const display = (value) => {
    if (!isMeaningful(value)) return "--";
    return String(value);
};

export default function DiagnosticsPanel({ runtimeHealth, displayedBlockingReason }) {
    const [open, setOpen] = useState(false);

    const issues = runtimeHealth?.issues || [];
    const blockingReason = displayedBlockingReason || runtimeHealth?.blockingReason;
    const executionReason = runtimeHealth?.executionReason;
    const stageExceptions = (runtimeHealth?.stages || []).filter(
        (s) => s?.exception && s.exception !== "None" && s.exception !== "--",
    );
    const engineStatus = runtimeHealth?.runtimeEngine?.status;
    const engineHealthy = runtimeHealth?.runtimeEngine?.healthy !== false;
    const exchangeWsConnected = runtimeHealth?.exchangeWebSocket?.connected;
    const browserWsConnected = runtimeHealth?.browserWebSocket?.connected;

    const diagnostics = [];

    if (isMeaningful(blockingReason)) {
        diagnostics.push({ type: "BLOCKING", label: "BLOCKING REASON", value: blockingReason, tone: "diag-danger" });
    }

    if (isMeaningful(executionReason) && executionReason !== blockingReason) {
        diagnostics.push({ type: "EXECUTION", label: "EXECUTION REASON", value: executionReason, tone: "diag-warning" });
    }

    issues.forEach((issue) => {
        diagnostics.push({ type: "ISSUE", label: "ISSUE", value: String(issue), tone: "diag-warning" });
    });

    stageExceptions.forEach((stage) => {
        diagnostics.push({
            type: "EXCEPTION",
            label: `STAGE: ${stage.name || stage.id}`,
            value: stage.exception,
            tone: "diag-danger",
        });
    });

    if (!engineHealthy && isMeaningful(engineStatus)) {
        diagnostics.push({ type: "ENGINE", label: "RUNTIME ENGINE", value: engineStatus, tone: "diag-danger" });
    }

    if (exchangeWsConnected === false && runtimeHealth?.running) {
        diagnostics.push({ type: "WS", label: "EXCHANGE WS", value: "DISCONNECTED", tone: "diag-danger" });
    }

    const count = diagnostics.length;
    const hasActiveDiag = count > 0;

    const headerText = hasActiveDiag
        ? `Diagnostics · ${count} ${count === 1 ? "item" : "items"}`
        : "Diagnostics";

    return (
        <section className="diagnostics-panel">
            <button
                aria-expanded={open}
                className="diagnostics-toggle"
                onClick={() => setOpen((v) => !v)}
                type="button"
            >
                <span aria-hidden="true" className="diagnostics-chevron">
                    {open ? "▼" : "▶"}
                </span>
                <span className="diagnostics-title">
                    {headerText}
                </span>
                {hasActiveDiag && (
                    <span className="diagnostics-badge diag-warning-badge">
                        {count}
                    </span>
                )}
            </button>

            <div className="diagnostics-content" hidden={!open}>
                {diagnostics.length === 0 ? (
                    <p className="diagnostics-empty">
                        No active warnings or errors.
                    </p>
                ) : (
                    <div className="diagnostics-list">
                        {diagnostics.map((diag, index) => (
                            <div className="diagnostics-row" key={`${diag.type}-${index}`}>
                                <span className="diagnostics-row-label">
                                    {diag.label}
                                </span>
                                <span
                                    className={`diagnostics-row-value ${diag.tone}`}
                                    title={diag.value}
                                >
                                    {diag.value}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </section>
    );
}
