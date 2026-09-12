import { HISTORY_AUTHORITIES } from "../../features/money-management/contracts/moneyManagementMonitoringContracts.js";
import { useEffect, useRef, useState } from "react";

import { getMoneyManagementHistory } from "../../features/money-management";
import MoneyManagementCardShell from "./MoneyManagementCardShell";

const EVENT_TYPES = [
    "",
    "APPLICATION_STARTED",
    "CONFIGURATION_UPDATED",
    "RUNTIME_METRICS_UPDATED",
    "LOSS_STATE_CHANGED",
    "RECOVERY_STATE_CHANGED",
    "EXPOSURE_STATE_CHANGED",
    "RISK_BUDGET_CHANGED",
    "POSITION_STATE_CHANGED",
    "MONEY_MANAGEMENT_LOCKED",
    "MONEY_MANAGEMENT_UNLOCKED",
    "DIAGNOSTIC_RAISED",
    "DIAGNOSTIC_CLEARED",
];

function EventRow({ event }) {
    const groups = event.changes?.reasonGroups ?? {};
    const changes = event.changes ?? {};
    const metricChange = changes.field
        ? `${changes.field}: ${changes.from ?? "—"} → ${changes.to ?? "—"}`
        : changes.from !== undefined
            ? `${changes.from ?? "—"} → ${changes.to ?? "—"}`
            : Object.keys(changes).length > 0
                ? JSON.stringify(changes)
                : "No detailed change";
    return (
        <li>
            <time dateTime={event.timestamp}>{event.timestamp}</time>
            <strong>{event.eventType}</strong>
            <span>{event.authority === "UNKNOWN" ? "UNKNOWN / LEGACY" : event.authority ?? "UNKNOWN / LEGACY"}</span>
            <span>{event.previousState ?? "—"} → {event.state}</span>
            <span>{metricChange}</span>
            {["block", "hold", "warning"].map((kind) => (
                Array.isArray(groups[kind]) && groups[kind].length > 0
                    ? <span key={kind}>{kind}: {groups[kind].join(", ")}</span>
                    : null
            ))}
            {event.reasonCodes?.length > 0 && (
                <span>Reason: {event.reasonCodes.join(", ")}</span>
            )}
            {event.diagnostics?.length > 0 && (
                <span>Diagnostic: {event.diagnostics.join(", ")}</span>
            )}
        </li>
    );
}

export default function MoneyManagementRuntimeHistoryCard() {
    const [authority, setAuthority] = useState("ALL");
    return <div>
        <div role="group" aria-label="Runtime History authority" className="mm-analytics-periods mm-history-authorities">
            {HISTORY_AUTHORITIES.map((value) => <button type="button" key={value} aria-pressed={authority === value} onClick={() => setAuthority(value)}>
                {value === "UNKNOWN" ? "UNKNOWN / LEGACY" : value}
            </button>)}
        </div>
        <RuntimeHistory key={authority} authority={authority} />
    </div>;
}

function RuntimeHistory({ authority }) {
    const requestRef = useRef(0);
    const controllerRef = useRef(null);
    const [events, setEvents] = useState([]);
    const [eventType, setEventType] = useState("");
    const [state, setState] = useState("");
    const [limit, setLimit] = useState("100");
    const [nextCursor, setNextCursor] = useState(null);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = async ({ append = false } = {}) => {
        const requestId = ++requestRef.current;
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;
        setLoading(true);
        if (!append) setEvents([]);
        setError(null);
        try {
            const response = await getMoneyManagementHistory({
                authority,
                limit,
                eventType,
                state,
                ...(append && nextCursor ? { before: nextCursor } : {}),
            }, { signal: controller.signal });
            if (controller.signal.aborted || requestId !== requestRef.current) return;
            const incoming = Array.isArray(response.events)
                ? response.events
                : [];
            setEvents((current) => append
                ? [...current, ...incoming]
                : incoming);
            setNextCursor(response.nextCursor ?? null);
            setHasMore(response.hasMore === true);
        } catch (failure) {
            if (controller.signal.aborted || requestId !== requestRef.current) return;
            setError(failure?.code ?? "HISTORY_UNAVAILABLE");
        } finally {
            if (!controller.signal.aborted && requestId === requestRef.current) setLoading(false);
        }
    };

    useEffect(() => {
        void load();
        return () => { requestRef.current += 1; controllerRef.current?.abort(); };
    }, [authority, eventType, state, limit]);

    return (
        <MoneyManagementCardShell
            className="mm-card--runtime-history"
            title="Runtime History"
        >
            <p className="mm-card__data-note">
                監査履歴: {authority} — Monitoring View とは独立しています。UNKNOWN / LEGACY を含む実行イベント。Simulation excluded.
            </p>
            <div className="mm-action-row mm-history-toolbar">
                <label className="mm-configuration-field mm-history-filter">
                    <span>Event Type</span>
                    <select
                        onChange={(event) => setEventType(event.target.value)}
                        value={eventType}
                    >
                        {EVENT_TYPES.map((value) => (
                            <option key={value || "ALL"} value={value}>
                                {value || "All"}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="mm-configuration-field mm-history-filter">
                    <span>State</span>
                    <input
                        onChange={(event) => setState(event.target.value)}
                        placeholder="All states"
                        type="text"
                        value={state}
                    />
                </label>
                <label className="mm-configuration-field mm-history-filter">
                    <span>Display Count</span>
                    <select
                        onChange={(event) => setLimit(event.target.value)}
                        value={limit}
                    >
                        {["25", "50", "100", "250"].map((value) => (
                            <option key={value} value={value}>{value}</option>
                        ))}
                    </select>
                </label>
                <button disabled={loading} onClick={() => load()} type="button">
                    Refresh（更新）
                </button>
            </div>
            {error && <p className="mm-operation-notice mm-operation-notice--danger" role="alert">{error}</p>}
            {loading && events.length === 0 ? (
                <p className="mm-card__placeholder">Loading runtime history</p>
            ) : events.length === 0 ? (
                <p className="mm-card__placeholder">
                    No runtime history yet（実行履歴データはまだありません）
                </p>
            ) : (
                <>
                    <ol className="mm-runtime-timeline">
                        {events.map((event) => (
                            <EventRow event={event} key={event.eventId} />
                        ))}
                    </ol>
                    {hasMore && (
                        <div className="mm-action-row">
                            <button
                                disabled={loading}
                                onClick={() => load({ append: true })}
                                type="button"
                            >
                                Load More
                            </button>
                        </div>
                    )}
                </>
            )}
        </MoneyManagementCardShell>
    );
}
