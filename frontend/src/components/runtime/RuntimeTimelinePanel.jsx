import { useState } from "react";
import { getRuntimeReasonLabel, getRuntimeSourceLabel } from "../../runtime/runtimeDisplay";

const formatTime = (value) => {
    if (!value) return "--:--:--";
    if (/^\d{2}:\d{2}:\d{2}$/.test(String(value))) return String(value);
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString();
};

export default function RuntimeTimelinePanel({ events = [] }) {
    const [open, setOpen] = useState(false);

    const hasEvents = Array.isArray(events) && events.length > 0;

    return (
        <section className="runtime-timeline-panel">
            <button
                aria-expanded={open}
                className="runtime-timeline-toggle"
                onClick={() => setOpen((v) => !v)}
                type="button"
            >
                <span aria-hidden="true" className="runtime-timeline-chevron">
                    {open ? "▼" : "▶"}
                </span>
                <span className="runtime-timeline-toggle-title">
                    RUNTIME TIMELINE
                </span>
            </button>

            <div className="runtime-timeline-content" hidden={!open}>
                {!hasEvents ? (
                    <p className="runtime-timeline-empty">
                        No runtime events in this session.
                    </p>
                ) : (
                    <div className="runtime-timeline-table">
                        <div className="runtime-timeline-header">
                            <span>TIME</span>
                            <span>SOURCE / STAGE</span>
                            <span>STATE</span>
                            <span>REASON</span>
                        </div>
                        {events.map((event, index) => (
                            <div
                                className="runtime-timeline-row"
                                key={`${event.time ?? event.timestamp}-${event.source}-${index}`}
                            >
                                <span>{formatTime(event.time ?? event.timestamp)}</span>
                                <span>{getRuntimeSourceLabel(event.source ?? event.stage)}</span>
                                <span className={`runtime-status runtime-status-${String(event.state ?? "").toLowerCase()}`}>
                                    {event.state ?? "--"}
                                </span>
                                <span title={event.reason}>
                                    {getRuntimeReasonLabel(event.reason ?? event.message)}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </section>
    );
}
