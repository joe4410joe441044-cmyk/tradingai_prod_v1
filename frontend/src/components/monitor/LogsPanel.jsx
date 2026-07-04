import {
    useEffect,
    useMemo,
    useRef,
} from "react";

import "../../styles/dashboard.css";

const safeArray = (value) => (Array.isArray(value) ? value : []);

const formatTime = (value) => {
    if (!value) {
        return "--:--:--";
    }

    if (/^\d{2}:\d{2}:\d{2}$/.test(String(value))) {
        return String(value);
    }

    const date = new Date(value);

    return Number.isNaN(date.getTime())
        ? "--:--:--"
        : date.toLocaleTimeString();
};

const normalizeSource = (type = "") => {
    const normalized = String(type).toLowerCase();

    if (normalized.includes("router")) return "ROUTER";
    if (normalized.includes("market")) return "MARKET";
    if (normalized.includes("micro")) return "MICRO";
    if (normalized.includes("risk")) return "ENGINE";
    if (normalized.includes("execution")) return "EXEC";
    if (normalized.includes("restriction")) return "ENGINE";
    if (normalized.includes("runtime")) return "SYSTEM";

    return "SYSTEM";
};

const normalizeLevel = (type = "") => {
    const normalized = String(type).toLowerCase();

    if (normalized.includes("error") || normalized.includes("failure")) {
        return "ERROR";
    }

    if (normalized.includes("risk") || normalized.includes("restriction")) {
        return "WARN";
    }

    return "INFO";
};

const normalizeState = (entry = {}) => {
    const value = String(
        entry.state ?? entry.message ?? entry.type ?? ""
    ).toUpperCase();

    const knownStates = [
        "RECONNECT",
        "STALE",
        "BLOCKED",
        "DEGRADED",
        "FAILURE",
        "DISCONNECTED",
        "RECOVERY",
        "WAIT",
    ];

    return knownStates.find((state) => value.includes(state)) ?? "UNKNOWN";
};

const categoryClass = (level = "") => {
    const normalized = String(level).toLowerCase();

    if (normalized.includes("error")) return "error";
    if (normalized.includes("warn")) return "warning";

    return "system";
};

const mapLogEntry = (entry = {}) => ({
    timestamp: entry.timestamp ?? Date.now(),
    source: entry.source ?? normalizeSource(entry.type),
    level: entry.level ?? normalizeLevel(entry.type),
    state: normalizeState(entry),
});

const buildRuntimeEvents = ({
    logs,
    signalLogs,
    tradeLogs,
    unifiedTelemetry,
    journalTelemetry,
}) => {
    const runtimeEvents = [];

    if (unifiedTelemetry?.market?.marketHostility > 0.7) {
        runtimeEvents.push({
            timestamp: Date.now(),
            source: "MARKET",
            level: "WARN",
            state: "HOSTILE",
        });
    }

    if (unifiedTelemetry?.runtime?.streamStale) {
        runtimeEvents.push({
            timestamp: Date.now(),
            source: "SYSTEM",
            level: "WARN",
            state: "STALE",
        });
    }

    if (unifiedTelemetry?.runtime?.reconnectInProgress) {
        runtimeEvents.push({
            timestamp: Date.now(),
            source: "SYSTEM",
            level: "WARN",
            state: "RECONNECT",
        });
    }

    if (unifiedTelemetry?.risk?.restrictionReason
        && unifiedTelemetry.risk.restrictionReason !== "NONE") {
        runtimeEvents.push({
            timestamp: Date.now(),
            source: "ENGINE",
            level: "WARN",
            state: "BLOCKED",
        });
    }

    if (journalTelemetry?.crashRecoveryDetected) {
        runtimeEvents.push({
            timestamp: Date.now(),
            source: "SYSTEM",
            level: "INFO",
            state: "RECOVERY",
        });
    }

    [logs, signalLogs, tradeLogs].forEach((entries) => {
        safeArray(entries).slice(-30).forEach((entry) => {
            runtimeEvents.push(mapLogEntry(entry));
        });
    });

    return runtimeEvents
        .sort((a, b) => Number(a.timestamp) - Number(b.timestamp))
        .slice(-120);
};

export default function LogsPanel({
    logs = [],
    signalLogs = [],
    tradeLogs = [],
    unifiedTelemetry = {},
    journalTelemetry = {},
    events,
    title = "CENTER | EVENT STREAM",
    showLevel = true,
    embedded = false,
    loading = false,
    error = false,
}) {
    const streamRef = useRef(null);

    const runtimeEvents = useMemo(() => {
        if (Array.isArray(events)) {
            return events;
        }

        return buildRuntimeEvents({
            logs,
            signalLogs,
            tradeLogs,
            unifiedTelemetry,
            journalTelemetry,
        });
    }, [
        events,
        journalTelemetry,
        logs,
        signalLogs,
        tradeLogs,
        unifiedTelemetry,
    ]);

    useEffect(() => {
        if (streamRef.current) {
            streamRef.current.scrollTop = streamRef.current.scrollHeight;
        }
    }, [runtimeEvents]);

    const rowClassName = showLevel
        ? "log-stream-line"
        : "log-stream-line timeline-row";

    return (
        <section className={embedded
            ? "terminal-monitor-section logs-panel execution-timeline"
            : "panel-card logs-panel"
        }>
            <div className={embedded ? "terminal-section-header" : "panel-title"}>
                {title}
            </div>

            <div ref={streamRef} className="log-stream">
                <div className={rowClassName}>
                    <div>TIME（時刻）</div>
                    <div>SOURCE（実行元）</div>
                    {showLevel && <div>LEVEL</div>}
                    <div>STATE（状態）</div>
                    {!showLevel && <div>REASON（理由）</div>}
                </div>

                {loading && (
                    <div className={rowClassName}>
                        <div>--:--:--</div>
                        <div>SYSTEM</div>
                        {showLevel && <div>INFO</div>}
                        <div>LOADING</div>
                        {!showLevel && <div>--</div>}
                    </div>
                )}

                {error && (
                    <div className={rowClassName}>
                        <div>--:--:--</div>
                        <div>SYSTEM</div>
                        {showLevel && <div className="terminal-red">ERROR</div>}
                        <div>FAILURE</div>
                        {!showLevel && <div>--</div>}
                    </div>
                )}

                {runtimeEvents.map((event, index) => (
                    <div
                        className={rowClassName}
                        key={`${event.time ?? event.timestamp}-${event.source}-${index}`}
                    >
                        <div>{formatTime(event.time ?? event.timestamp)}</div>
                        <div>{event.source ?? "SYSTEM"}</div>
                        {showLevel && (
                            <div className={categoryClass(event.level)}>
                                {event.level ?? "INFO"}
                            </div>
                        )}
                        <div>{event.state ?? "UNKNOWN"}</div>
                        {!showLevel && <div>{event.reason ?? "--"}</div>}
                    </div>
                ))}

                {runtimeEvents.length === 0 && !loading && !error && (
                    <div className={rowClassName}>
                        <div>--:--:--</div>
                        <div>SYSTEM</div>
                        {showLevel && <div>INFO</div>}
                        <div>NO EVENTS</div>
                        {!showLevel && <div>SNAPSHOT_TIMELINE_EMPTY</div>}
                    </div>
                )}
            </div>
        </section>
    );
}
