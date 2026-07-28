import { useEffect, useMemo, useState } from "react";
import {
    CartesianGrid,
    Line,
    LineChart,
    ReferenceDot,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

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

function HistoryChart({ data, metric, title, unit = null }) {
    const available = data.some((point) => point[metric] !== null);
    if (!available) {
        return <p className="mm-card__placeholder">{title}: No data</p>;
    }
    return (
        <section aria-label={title}>
            <h3>{title}</h3>
            <ResponsiveContainer height={200} width="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" minTickGap={24} />
                    <YAxis domain={["auto", "auto"]} unit={unit} />
                    <Tooltip />
                    <Line
                        connectNulls={false}
                        dataKey={metric}
                        dot={false}
                        isAnimationActive={false}
                        type="monotone"
                    />
                    {data
                        .filter((point) => (
                            point.transition && point[metric] !== null
                        ))
                        .map((point) => (
                            <ReferenceDot
                                key={`${metric}-${point.sequence}`}
                                label={point.state}
                                r={3}
                                x={point.timestamp}
                                y={point[metric]}
                            />
                        ))}
                </LineChart>
            </ResponsiveContainer>
        </section>
    );
}

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
    const [events, setEvents] = useState([]);
    const [eventType, setEventType] = useState("");
    const [state, setState] = useState("");
    const [limit, setLimit] = useState("100");
    const [nextCursor, setNextCursor] = useState(null);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = async ({ append = false } = {}) => {
        setLoading(true);
        setError(null);
        try {
            const response = await getMoneyManagementHistory({
                limit,
                eventType,
                state,
                ...(append && nextCursor ? { before: nextCursor } : {}),
            });
            const incoming = Array.isArray(response.events)
                ? response.events
                : [];
            setEvents((current) => append
                ? [...current, ...incoming]
                : incoming);
            setNextCursor(response.nextCursor ?? null);
            setHasMore(response.hasMore === true);
        } catch (failure) {
            setError(failure?.code ?? "HISTORY_UNAVAILABLE");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, [eventType, state, limit]);

    const chartData = useMemo(() => (
        [...events]
            .sort((left, right) => left.sequence - right.sequence)
            .slice(-500)
            .map((event) => ({
                sequence: event.sequence,
                timestamp: event.timestamp,
                state: event.state,
                transition: [
                    "LOSS_STATE_CHANGED",
                    "RECOVERY_STATE_CHANGED",
                    "MONEY_MANAGEMENT_LOCKED",
                    "MONEY_MANAGEMENT_UNLOCKED",
                ].includes(event.eventType),
                equity: event.metrics?.equity ?? null,
                drawdownPercent: event.metrics?.drawdownPercent ?? null,
                exposureUtilization:
                    event.metrics?.exposureUtilization ?? null,
                riskUtilization: event.metrics?.riskUtilization ?? null,
            }))
    ), [events]);
    const hasChartData = chartData.some((point) => (
        point.equity !== null ||
        point.drawdownPercent !== null ||
        point.exposureUtilization !== null ||
        point.riskUtilization !== null
    ));

    return (
        <MoneyManagementCardShell
            className="mm-card--runtime-history"
            title="Runtime History"
        >
            <p className="mm-card__data-note">
                Runtime events only（実行イベントのみ）— Simulation excluded.
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
            {hasChartData && (
                <div className="mm-history-charts">
                    <HistoryChart
                        data={chartData}
                        metric="equity"
                        title="Capital / Equity History"
                        unit=" USDT"
                    />
                    <HistoryChart
                        data={chartData}
                        metric="drawdownPercent"
                        title="Drawdown History"
                        unit="%"
                    />
                    <HistoryChart
                        data={chartData}
                        metric="exposureUtilization"
                        title="Exposure Utilization History"
                        unit="%"
                    />
                    <HistoryChart
                        data={chartData}
                        metric="riskUtilization"
                        title="Risk Utilization History"
                        unit="%"
                    />
                </div>
            )}
        </MoneyManagementCardShell>
    );
}
