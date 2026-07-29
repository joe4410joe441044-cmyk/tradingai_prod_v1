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

function AnalyticsChart({ data, lines, loading, title, unit = null }) {
    if (loading) {
        return (
            <MoneyManagementCardShell loading title={title} />
        );
    }
    const available = data.some((point) => (
        lines.some(({ metric }) => point[metric] !== null)
    ));
    if (!available) {
        return (
            <MoneyManagementCardShell
                className="mm-card--analytics"
                title={title}
            >
                <p className="mm-card__placeholder">No data</p>
            </MoneyManagementCardShell>
        );
    }
    return (
        <MoneyManagementCardShell
            className="mm-card--analytics"
            title={title}
        >
            <ResponsiveContainer height={220} width="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" minTickGap={24} />
                    <YAxis domain={["auto", "auto"]} unit={unit} />
                    <Tooltip />
                    {lines.map(({ metric, name }) => (
                        <Line
                            connectNulls={false}
                            dataKey={metric}
                            dot={false}
                            isAnimationActive={false}
                            key={metric}
                            name={name}
                            type="monotone"
                        />
                    ))}
                    {data
                        .filter((point) => (
                            point.transition &&
                            point[lines[0].metric] !== null
                        ))
                        .map((point) => (
                            <ReferenceDot
                                key={`${lines[0].metric}-${point.sequence}`}
                                label={point.state}
                                r={3}
                                x={point.timestamp}
                                y={point[lines[0].metric]}
                            />
                        ))}
                </LineChart>
            </ResponsiveContainer>
        </MoneyManagementCardShell>
    );
}

export default function MoneyManagementAnalyticsSection() {
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
    const data = useMemo(() => (
        [...filteredEvents]
            .sort((left, right) => left.sequence - right.sequence)
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
                realizedPnl: event.metrics?.realizedPnl ?? null,
                drawdownPercent: event.metrics?.drawdownPercent ?? null,
                exposureUtilization:
                    event.metrics?.exposureUtilization ?? null,
                riskUtilization: event.metrics?.riskUtilization ?? null,
            }))
    ), [filteredEvents]);
    const hasAnalytics = data.some((point) => (
        point.equity !== null ||
        point.realizedPnl !== null ||
        point.drawdownPercent !== null ||
        point.exposureUtilization !== null ||
        point.riskUtilization !== null
    ));

    return (
        <section aria-label="Money Management Analytics">
            <div className="mm-analytics-header">
                <h2 className="mm-section-title">Analytics</h2>
                <div
                    aria-label="Analytics period"
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
                    Analytics unavailable
                </p>
            )}
            {!error && !loading && !hasAnalytics && (
                <p className="mm-card__placeholder">
                    No runtime analytics yet
                </p>
            )}
            {!error && (loading || hasAnalytics) && (
                <div className="mm-analytics">
                    <AnalyticsChart
                        data={data}
                        loading={loading}
                        lines={[{ metric: "equity", name: "Equity" }]}
                        title="Equity Curve"
                        unit=" USDT"
                    />
                    <AnalyticsChart
                        data={data}
                        loading={loading}
                        lines={[{
                            metric: "realizedPnl",
                            name: "Cumulative Realized P&L",
                        }]}
                        title="Cumulative Realized P&L"
                        unit=" USDT"
                    />
                    <AnalyticsChart
                        data={data}
                        loading={loading}
                        lines={[{
                            metric: "drawdownPercent",
                            name: "Drawdown",
                        }]}
                        title="Drawdown"
                        unit="%"
                    />
                    <AnalyticsChart
                        data={data}
                        loading={loading}
                        lines={[
                            {
                                metric: "riskUtilization",
                                name: "Risk Utilization",
                            },
                            {
                                metric: "exposureUtilization",
                                name: "Exposure Utilization",
                            },
                        ]}
                        title="Risk / Exposure"
                        unit="%"
                    />
                </div>
            )}
        </section>
    );
}
