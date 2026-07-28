import { useState } from "react";

import { previewMoneyManagementPositionSize } from "../../features/money-management";
import MoneyManagementCardShell from "./MoneyManagementCardShell";

const initialDraft = Object.freeze({
    symbol: "",
    entryPrice: "",
    stopLossPercent: "",
    effectiveCostPercent: "",
    riskPercent: "",
    quantityStep: "",
    contractMultiplier: "",
});

const fields = [
    ["symbol", "Symbol"],
    ["entryPrice", "Entry Price"],
    ["stopLossPercent", "Stop Loss"],
    ["effectiveCostPercent", "Fees + Slippage"],
    ["riskPercent", "Risk"],
    ["quantityStep", "Quantity Step"],
    ["contractMultiplier", "Contract Multiplier"],
];

export default function MoneyManagementPositionSizingCard({ viewModel }) {
    const [draft, setDraft] = useState(initialDraft);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);

    const calculate = async (event) => {
        event.preventDefault();
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            setResult(await previewMoneyManagementPositionSize(draft));
        } catch (failure) {
            setError(failure?.code ?? "POSITION_SIZE_PREVIEW_FAILED");
        } finally {
            setLoading(false);
        }
    };

    return (
        <MoneyManagementCardShell title="Position Size">
            <dl className="mm-metric-list">
                {viewModel.positionSizing.map((row) => (
                    <div className="mm-metric-row" key={row.label}>
                        <dt>{row.label}</dt>
                        <dd>
                            {row.value.text}
                            {row.value.unit && <small>{row.value.unit}</small>}
                        </dd>
                    </div>
                ))}
            </dl>
            <form className="mm-interaction-form" onSubmit={calculate}>
                <div className="mm-configuration-fields">
                    {fields.map(([key, label]) => (
                        <label className="mm-configuration-field" key={key}>
                            <span>{label}</span>
                            <input
                                autoComplete="off"
                                inputMode={key === "symbol" ? "text" : "decimal"}
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
                </div>
                <div className="mm-action-row">
                    <button disabled={loading} type="submit">
                        {loading ? "Calculating" : "Calculate Position Size"}
                    </button>
                </div>
            </form>
            {error && <p className="mm-operation-notice mm-operation-notice--danger" role="alert">{error}</p>}
            {result && (
                <dl aria-live="polite" className="mm-metric-list">
                    <div className="mm-metric-row">
                        <dt>Risk Amount</dt><dd>{result.riskAmount} USDT</dd>
                    </div>
                    <div className="mm-metric-row">
                        <dt>Recommended Notional</dt>
                        <dd>{result.finalPositionNotional} USDT</dd>
                    </div>
                    <div className="mm-metric-row">
                        <dt>Recommended Quantity</dt>
                        <dd>{result.positionQuantity}</dd>
                    </div>
                    <div className="mm-metric-row">
                        <dt>Applied Limit</dt>
                        <dd>{result.appliedLimits.join(", ") || "None"}</dd>
                    </div>
                    <div className="mm-metric-row">
                        <dt>Calculation Status</dt>
                        <dd>{result.calculationAllowed ? "AVAILABLE" : "UNAVAILABLE"}</dd>
                    </div>
                </dl>
            )}
            <p className="mm-card__data-note">
                Preview only. No order is created or submitted.
            </p>
        </MoneyManagementCardShell>
    );
}
