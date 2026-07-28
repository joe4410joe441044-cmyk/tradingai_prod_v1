import { useEffect, useState } from "react";
import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import { simulateMoneyManagement } from "../../features/money-management";
import MoneyManagementCardShell from "./MoneyManagementCardShell";

const initialDraft = {
    initialCapital: "1000",
    numberOfTrades: "100",
    winRatePercent: "55",
    averageWinPercent: "1.50",
    averageLossPercent: "1.00",
    riskPerTradePercent: "",
    maximumDrawdownPercent: "",
    feesPercent: "0.06",
    slippagePercent: "0.02",
    compoundingEnabled: true,
    scenario: "EXPECTED_SEQUENCE",
    customSequence: "",
};

const fields = [
    ["initialCapital", "Initial Capital"],
    ["numberOfTrades", "Number of Trades"],
    ["winRatePercent", "Win Rate"],
    ["averageWinPercent", "Average Win"],
    ["averageLossPercent", "Average Loss"],
    ["riskPerTradePercent", "Risk per Trade"],
    ["maximumDrawdownPercent", "Maximum Drawdown"],
    ["feesPercent", "Fees"],
    ["slippagePercent", "Slippage"],
];

function SimulationChart({ data, dataKey, title }) {
    if (!data.length) {
        return <p className="mm-card__placeholder">No projection data</p>;
    }
    return (
        <section aria-label={title}>
            <h3>{title}</h3>
            <ResponsiveContainer height={220} width="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="tradeNumber" />
                    <YAxis domain={["auto", "auto"]} />
                    <Tooltip />
                    <Line
                        dataKey={dataKey}
                        dot={false}
                        isAnimationActive={false}
                        type="monotone"
                    />
                </LineChart>
            </ResponsiveContainer>
        </section>
    );
}

export default function MoneyManagementSimulationCard({ configuration }) {
    const [draft, setDraft] = useState(initialDraft);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (!configuration) return;
        setDraft((current) => ({
            ...current,
            riskPerTradePercent:
                current.riskPerTradePercent ||
                configuration.riskPerTradePercent ||
                "",
            maximumDrawdownPercent:
                current.maximumDrawdownPercent ||
                configuration.maximumDrawdownPercent ||
                "",
        }));
    }, [configuration]);

    const run = async (event) => {
        event.preventDefault();
        setLoading(true);
        setError(null);
        setResult(null);
        const tradeCount = Number.parseInt(draft.numberOfTrades, 10);
        if (!Number.isSafeInteger(tradeCount)) {
            setError("SIMULATION_INPUT_INVALID");
            setLoading(false);
            return;
        }
        const payload = {
            initialCapital: draft.initialCapital,
            numberOfTrades: tradeCount,
            winRatePercent: draft.winRatePercent,
            averageWinPercent: draft.averageWinPercent,
            averageLossPercent: draft.averageLossPercent,
            riskPerTradePercent: draft.riskPerTradePercent,
            maximumDrawdownPercent: draft.maximumDrawdownPercent,
            compoundingEnabled: draft.compoundingEnabled,
            feesPercent: draft.feesPercent,
            slippagePercent: draft.slippagePercent,
            scenario: draft.scenario,
            ...(draft.scenario === "CUSTOM_SEQUENCE"
                ? {
                    customSequence: draft.customSequence
                        .split(",")
                        .map((item) => item.trim().toUpperCase())
                        .filter(Boolean),
                }
                : {}),
        };
        try {
            setResult(await simulateMoneyManagement(payload));
        } catch (failure) {
            setError(failure?.code ?? "SIMULATION_FAILED");
        } finally {
            setLoading(false);
        }
    };
    const summary = result?.summary ?? null;
    const projection = Array.isArray(result?.projection)
        ? result.projection
        : [];

    return (
        <MoneyManagementCardShell
            className="mm-card--simulation"
            title="Simulation"
        >
            <form className="mm-interaction-form" onSubmit={run}>
                <div className="mm-configuration-fields">
                    {fields.map(([key, label]) => (
                        <label className="mm-configuration-field" key={key}>
                            <span>{label}</span>
                            <input
                                autoComplete="off"
                                inputMode={key === "numberOfTrades" ? "numeric" : "decimal"}
                                onChange={(event) => setDraft({
                                    ...draft,
                                    [key]: event.target.value,
                                })}
                                required
                                type="text"
                                value={draft[key]}
                            />
                        </label>
                    ))}
                    <label className="mm-configuration-field">
                        <span>Scenario</span>
                        <select
                            onChange={(event) => setDraft({
                                ...draft,
                                scenario: event.target.value,
                            })}
                            value={draft.scenario}
                        >
                            {[
                                "EXPECTED_SEQUENCE",
                                "WORST_LOSS_STREAK",
                                "ALL_WINS",
                                "ALL_LOSSES",
                                "ALTERNATING",
                                "CUSTOM_SEQUENCE",
                            ].map((scenario) => (
                                <option key={scenario} value={scenario}>
                                    {scenario}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="mm-configuration-field">
                        <span>Compounding</span>
                        <input
                            checked={draft.compoundingEnabled}
                            onChange={(event) => setDraft({
                                ...draft,
                                compoundingEnabled: event.target.checked,
                            })}
                            type="checkbox"
                        />
                    </label>
                    {draft.scenario === "CUSTOM_SEQUENCE" && (
                        <label className="mm-configuration-field">
                            <span>Custom Sequence (WIN,LOSS,…)</span>
                            <input
                                onChange={(event) => setDraft({
                                    ...draft,
                                    customSequence: event.target.value,
                                })}
                                required
                                type="text"
                                value={draft.customSequence}
                            />
                        </label>
                    )}
                </div>
                <div className="mm-action-row">
                    <button disabled={loading} type="submit">
                        {loading ? "Simulating" : "Run Simulation"}
                    </button>
                </div>
            </form>
            {error && <p className="mm-operation-notice mm-operation-notice--danger" role="alert">{error}</p>}
            {!summary ? (
                <p className="mm-card__placeholder">Not calculated</p>
            ) : (
                <>
                    <dl className="mm-metric-list">
                        {[
                            ["Final Capital", summary.finalCapital, "USDT"],
                            ["Net Profit / Loss", summary.netProfitLoss, "USDT"],
                            ["Return", summary.returnPercent, "%"],
                            ["Maximum Drawdown", summary.maximumDrawdownPercent, "%"],
                            ["Largest Losing Streak", summary.largestLossStreak, null],
                            ["Recovery Required", summary.recoveryRequiredPercent ?? "—", "%"],
                            ["Ruin Status", summary.ruinReached ? "RUINED" : "NOT REACHED", null],
                            ["Lock Status", summary.lockReached ? "LOCKED" : "NOT REACHED", null],
                            ["Average Position Size", summary.averagePositionNotional ?? "—", "USDT"],
                        ].map(([label, value, unit]) => (
                            <div className="mm-metric-row" key={label}>
                                <dt>{label}</dt>
                                <dd>{value}{unit && <small>{unit}</small>}</dd>
                            </div>
                        ))}
                    </dl>
                    <SimulationChart
                        data={projection}
                        dataKey="capital"
                        title="Capital Curve"
                    />
                    <SimulationChart
                        data={projection}
                        dataKey="drawdownPercent"
                        title="Drawdown Curve"
                    />
                </>
            )}
            <p className="mm-card__data-note">
                Deterministic analysis only. Results are not runtime history
                and do not modify configuration or create orders.
            </p>
        </MoneyManagementCardShell>
    );
}
