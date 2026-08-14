import { useState } from "react";
import { getRuntimeSourceLabel } from "../../runtime/runtimeDisplay";

const hasContent = (value) => {
    if (value === null || value === undefined || value === "") return false;
    if (value === "--") return false;
    if (value === "None") return false;
    return true;
};

const formatJson = (value) => {
    if (!hasContent(value)) return "--";
    try {
        const parsed = JSON.parse(value);
        return JSON.stringify(parsed, null, 2);
    } catch {
        return String(value);
    }
};

export default function StageInspectorPanel({ stage }) {
    const [open, setOpen] = useState(false);
    const [showFullInput, setShowFullInput] = useState(false);
    const [showFullOutput, setShowFullOutput] = useState(false);

    const status = stage?.status ?? "ERROR";
    const exception = stage?.exception;
    const hasException = exception && exception !== "None" && exception !== "--";

    const fields = [
        { label: "BACKEND FILE", value: stage?.backendFile },
        { label: "FUNCTION", value: stage?.functionName },
        { label: "DURATION", value: stage?.duration },
        { label: "REASON", value: stage?.reason },
        { label: "RELATED FILES", value: stage?.relatedFiles },
    ].filter((f) => hasContent(f.value));

    return (
        <section className="stage-inspector-card">
            <button
                aria-expanded={open}
                className="stage-inspector-toggle"
                onClick={() => setOpen((v) => !v)}
                type="button"
            >
                <span aria-hidden="true" className="stage-inspector-chevron">
                    {open ? "▼" : "▶"}
                </span>
                <span className="stage-inspector-toggle-title">
                    STAGE INSPECTOR
                </span>
            </button>

            <div className="stage-inspector-content" hidden={!open}>
                <div className="stage-inspector-selection">
                    <div className="stage-inspector-summary">
                        <span>CURRENT STAGE</span>
                        <strong>{getRuntimeSourceLabel(stage?.name ?? "Runtime Health Snapshot")}</strong>
                    </div>

                    <div className="stage-inspector-summary">
                        <span>STATUS</span>
                        <strong className={`runtime-status runtime-status-${status.toLowerCase()}`}>
                            {status}
                        </strong>
                    </div>
                </div>

                <div className="stage-inspector-fields">
                    {fields.map((field) => (
                        <div
                            className="stage-inspector-field"
                            key={field.label}
                        >
                            <span>{field.label}</span>
                            <code title={field.value}>{field.value}</code>
                        </div>
                    ))}

                    {hasContent(stage?.input) && (
                        <div className="stage-inspector-field expanded">
                            <span>INPUT</span>
                            <div className="stage-inspector-code-block">
                                <button
                                    className="stage-inspector-expand-btn"
                                    onClick={() => setShowFullInput((v) => !v)}
                                    type="button"
                                >
                                    {showFullInput ? "COLLAPSE" : "EXPAND"}
                                </button>
                                <pre className={showFullInput ? "expanded" : "collapsed"}>
                                    <code>{formatJson(stage.input)}</code>
                                </pre>
                            </div>
                        </div>
                    )}

                    {hasContent(stage?.output) && (
                        <div className="stage-inspector-field expanded">
                            <span>OUTPUT</span>
                            <div className="stage-inspector-code-block">
                                <button
                                    className="stage-inspector-expand-btn"
                                    onClick={() => setShowFullOutput((v) => !v)}
                                    type="button"
                                >
                                    {showFullOutput ? "COLLAPSE" : "EXPAND"}
                                </button>
                                <pre className={showFullOutput ? "expanded" : "collapsed"}>
                                    <code>{formatJson(stage.output)}</code>
                                </pre>
                            </div>
                        </div>
                    )}

                    <div className="stage-inspector-field">
                        <span>EXCEPTION</span>
                        <code className={hasException ? "exception-active" : "exception-none"}>
                            {hasException ? exception : "None"}
                        </code>
                    </div>
                </div>
            </div>
        </section>
    );
}
