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
import {
    filterMoneyManagementAnalyticsEvents,
    loadMoneyManagementAnalyticsHistory,
    MONEY_MANAGEMENT_ANALYTICS_PERIOD,
} from "../../features/money-management/analytics/moneyManagementAnalytics.js";
import MoneyManagementCardShell from "./MoneyManagementCardShell";

const PERIODS = Object.values(MONEY_MANAGEMENT_ANALYTICS_PERIOD);

function parseMetricAsNumber(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "number") return Number.isFinite(value) ? value : null;
    if (typeof value === "string") {
        const parsed = Number.parseFloat(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}

function CapitalChart({ data, loading }) {
    if (loading) {
        return (
            <MoneyManagementCardShell loading title="Equity / Peak Equity" />
        );
    }

    const available = data.some((point) => (
        point.equity !== null || point.peakEquity !== null
    ));

    if (!available) {
        return (
            <MoneyManagementCardShell
                className="mm-card--top-graph"
                title="Equity / Peak Equity"
            >
                <p className="mm-card__placeholder">No capital history</p>
            </MoneyManagementCardShell>
        );
    }

    const chartLines = [];
    if (data.some((p) => p.equity !== null)) {
        chartLines.push({ metric: "equity", name: "Equity", stroke: "#10b981" });
    }
    if (data.some((p) => p.peakEquity !== null)) {
        chartLines.push({ metric: "peakEquity", name: "Peak Equity", stroke: "#6366f1" });
    }

    return (
        <MoneyManagementCardShell
            className="mm-card--top-graph"
            title="Equity / Peak Equity"
        >
            <ResponsiveContainer height={220} width="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" minTickGap={24} />
                    <YAxis domain={["auto", "auto"]} unit=" USDT" />
                    <Tooltip />
                    {chartLines.map(({ metric, name, stroke }) => (
                        <Line
                            connectNulls={false}
                            dataKey={metric}
                            dot={false}
                            isAnimationActive={false}
                            key={metric}
                            name={name}
                            stroke={stroke}
                            type="monotone"
                        />
                    ))}
                    {data
                        .filter((point) => (
                            point.transition && point.equity !== null
                        ))
                        .map((point) => (
                            <ReferenceDot
                                key={`equity-${point.sequence}`}
                                label={point.state}
                                r={3}
                                x={point.timestamp}
                                y={point.equity}
                            />
                        ))}
                </LineChart>
            </ResponsiveContainer>
        </MoneyManagementCardShell>
    );
}

function DrawdownChart({ data, loading }) {
    if (loading) {
        return (
            <MoneyManagementCardShell loading title="Drawdown" />
        );
    }

    const available = data.some((point) => point.drawdownPercent !== null);

    if (!available) {
        return (
            <MoneyManagementCardShell
                className="mm-card--top-graph"
                title="Drawdown"
            >
                <p className="mm-card__placeholder">No drawdown history</p>
            </MoneyManagementCardShell>
        );
    }

    return (
        <MoneyManagementCardShell
            className="mm-card--top-graph"
            title="Drawdown"
        >
            <ResponsiveContainer height={220} width="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" minTickGap={24} />
                    <YAxis domain={["auto", 0]} unit="%" />
                    <Tooltip />
                    <Line
                        connectNulls={false}
                        dataKey="drawdownPercent"
                        dot={false}
                        isAnimationActive={false}
                        name="Drawdown %"
                        stroke="#ef4444"
                        type="monotone"
                    />
                    {data
                        .filter((point) => (
                            point.transition && point.drawdownPercent !== null
                        ))
                        .map((point) => (
                            <ReferenceDot
                                key={`drawdown-${point.sequence}`}
                                label={point.state}
                                r={3}
                                x={point.timestamp}
                                y={point.drawdownPercent}
                            />
                        ))}
                </LineChart>
            </ResponsiveContainer>
        </MoneyManagementCardShell>
    );
}

export default function MoneyManagementCapitalDrawdownSection() {
    const [events, setEvents] = useState([]);
    const [period, setPeriod] = useState(
        MONEY_MANAGEMENT_ANALYTICS_PERIOD.THIRTY_DAYS,
    );
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const controller = new AbortController();
        const load = async () => {
            try {
                const history = await loadMoneyManagementAnalyticsHistory({
                    client: getMoneyManagementHistory,
                    signal: controller.signal,
                });
                if (!controller.signal.aborted) {
                    setEvents(history);
                }
            } catch {
                if (!controller.signal.aborted) {
                    setError(true);
                }
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        };
        void load();
        return () => controller.abort();
    }, []);

    const filteredEvents = useMemo(
        () => filterMoneyManagementAnalyticsEvents(events, period),
        [events, period],
    );

    const data = useMemo(() => {
        return [...filteredEvents]
            .sort((left, right) => left.sequence - right.sequence)
            .map((event) => {
                const equity = parseMetricAsNumber(event.metrics?.equity);
                const peakEquity = parseMetricAsNumber(event.metrics?.peakEquity);

                return {
                    sequence: event.sequence,
                    timestamp: event.timestamp,
                    state: event.state,
                    transition: [
                        "LOSS_STATE_CHANGED",
                        "RECOVERY_STATE_CHANGED",
                        "MONEY_MANAGEMENT_LOCKED",
                        "MONEY_MANAGEMENT_UNLOCKED",
                    ].includes(event.eventType),
                    equity,
                    peakEquity,
                    drawdownPercent: parseMetricAsNumber(event.metrics?.drawdownPercent),
                };
            });
    }, [filteredEvents]);

    const hasData = data.some((point) => (
        point.equity !== null ||
        point.peakEquity !== null ||
        point.drawdownPercent !== null
    ));

    return (
        <section aria-label="Capital / Drawdown Graph" className="mm-top-graph-section">
            <div className="mm-analytics-header">
                <h2 className="mm-section-title">Capital / Drawdown</h2>
                <div
                    aria-label="Graph period"
                    className="mm-analytics-periods"
                    role="group"
                >
                    {PERIODS.map((value) => (
                        <button
                            aria-pressed={period === value}
                            key={value}
                            onClick={() => setPeriod(value)}
                            type="button"
                        >
                            {value}
                        </button>
                    ))}
                </div>
            </div>
            {error && (
                <p
                    className="mm-operation-notice mm-operation-notice--danger"
                    role="alert"
                >
                    Capital / Drawdown history unavailable
                </p>
            )}
            {!error && !loading && !hasData && (
                <div className="mm-top-graph">
                    <MoneyManagementCardShell
                        className="mm-card--top-graph"
                        title="Equity / Peak Equity"
                    >
                        <p className="mm-card__placeholder">No runtime history yet</p>
                    </MoneyManagementCardShell>
                    <MoneyManagementCardShell
                        className="mm-card--top-graph"
                        title="Drawdown"
                    >
                        <p className="mm-card__placeholder">No runtime history yet</p>
                    </MoneyManagementCardShell>
                </div>
            )}
            {!error && (loading || hasData) && (
                <div className="mm-top-graph">
                    <CapitalChart data={data} loading={loading} />
                    <DrawdownChart data={data} loading={loading} />
                </div>
            )}
        </section>
    );
}
