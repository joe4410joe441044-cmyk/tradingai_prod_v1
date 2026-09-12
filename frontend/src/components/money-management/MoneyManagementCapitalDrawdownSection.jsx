import { useMemo, useState } from "react";
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

import { realizedPnlLabel } from "../../features/money-management/contracts/moneyManagementMonitoringContracts.js";
import {
    filterMoneyManagementAnalyticsEvents,
    MONEY_MANAGEMENT_ANALYTICS_PERIOD,
} from "../../features/money-management/analytics/moneyManagementAnalytics.js";
import MoneyManagementCardShell from "./MoneyManagementCardShell";
import { formatMoneyManagementAxisTimestamp } from "./moneyManagementChartFormatters.js";

const PERIODS = Object.values(MONEY_MANAGEMENT_ANALYTICS_PERIOD);

function PerformanceChart({ data, lines, loading, title, authority, unit = null }) {
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
                className="mm-card--top-graph"
                title={title}
            >
                <p className="mm-card__placeholder">No {authority} MM history available（履歴データなし）</p>
            </MoneyManagementCardShell>
        );
    }
    return (
        <MoneyManagementCardShell
            className="mm-card--top-graph"
            title={title}
        >
            <ResponsiveContainer height={176} width="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                        dataKey="timestamp"
                        minTickGap={24}
                        tickFormatter={formatMoneyManagementAxisTimestamp}
                    />
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

export default function MoneyManagementCapitalDrawdownSection({ viewAuthority, history }) {
    const [period, setPeriod] = useState(MONEY_MANAGEMENT_ANALYTICS_PERIOD.THIRTY_DAYS);
    const events = history.authority === viewAuthority ? history.history : [];
    const loading = history.authority !== viewAuthority || history.historyState === "LOADING";
    const error = history.authority === viewAuthority && history.historyState === "ERROR";
    const pnlLabel = realizedPnlLabel(viewAuthority);

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
                peakEquity: event.metrics?.peakEquity ?? null,
                realizedPnl: event.metrics?.realizedPnl ?? null,
                drawdownPercent: event.metrics?.drawdownPercent ?? null,
                exposureUtilization:
                    event.metrics?.exposureUtilization ?? null,
                riskUtilization: event.metrics?.riskUtilization ?? null,
            }))
    ), [filteredEvents]);
    return (
        <section aria-label="Capital / Performance Graphs" className="mm-top-graph-section">
            <div className="mm-analytics-header">
                <h2 className="mm-section-title">{viewAuthority} Capital / Performance</h2>
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
                    {viewAuthority} Capital / Performance history request error（取得失敗）
                </p>
            )}
            {!error && (
                <div className="mm-top-graph">
                    <PerformanceChart
                        authority={viewAuthority}
                        data={data}
                        loading={loading}
                        lines={[
                            { metric: "equity", name: "Equity" },
                            { metric: "peakEquity", name: "Peak Equity" },
                        ]}
                        title="Equity / Peak Equity"
                        unit=" USDT"
                    />
                    <PerformanceChart
                        authority={viewAuthority}
                        data={data}
                        loading={loading}
                        lines={[{
                            metric: "realizedPnl",
                            name: pnlLabel,
                        }]}
                        title={pnlLabel}
                        unit=" USDT"
                    />
                    <PerformanceChart
                        authority={viewAuthority}
                        data={data}
                        loading={loading}
                        lines={[{
                            metric: "drawdownPercent",
                            name: "Drawdown",
                        }]}
                        title="Drawdown"
                        unit="%"
                    />
                    <PerformanceChart
                        authority={viewAuthority}
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
