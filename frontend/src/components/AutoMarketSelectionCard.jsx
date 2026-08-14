import { buildAutoMarketSelectionModel, displayAmsValue } from "../features/auto-market-selection/autoMarketSelectionModel.js";

const statusClass = (value) => {
    const status = String(value || "").toUpperCase();
    if (["FAILED", "BLOCKED", "STALE"].includes(status)) return "status-danger";
    if (["UNAVAILABLE", "UNKNOWN", "IN_PROGRESS", "NO_ELIGIBLE_MARKET", "NO_RANKABLE_MARKET"].includes(status)) return "status-warning";
    if (["READY", "ELIGIBLE", "COMPLETED", "IDLE", "FRESH", "RANKED_CANDIDATES_AVAILABLE"].includes(status)) return "status-safe";
    return "";
};

const Field = ({ label, value, className = "" }) => (
    <div className="ams-field">
        <span className="ams-field-label">{label}</span>
        <strong className={`ams-field-value ${className}`}>{displayAmsValue(value)}</strong>
    </div>
);

export default function AutoMarketSelectionCard({ status, requestedSymbol }) {
    const model = buildAutoMarketSelectionModel(status, requestedSymbol);
    const top = model.topCandidate;
    const capital = model.capitalEligibility;
    const switching = model.switch;
    const autoRuntime = model.autoRuntime;
    const primaryReasons = [...(autoRuntime.reasonCodes || []), ...(switching.reasonCodes || []), ...model.reasons]
        .filter((value, index, values) => value && values.indexOf(value) === index)
        .slice(0, 3);

    return (
        <section className="panel-card ams-card" aria-labelledby="ams-card-title" data-testid="auto-market-selection-card">
            <div className="ams-card-header">
                <div id="ams-card-title" className="governance-card-title">AUTO MARKET SELECTION</div>
                <span className={`ams-read-status ${statusClass(model.availability)}`}>{model.availability}</span>
            </div>

            <div className="ams-symbol-grid">
                <Field label="SELECTION MODE" value={model.selectionMode} />
                <Field label="ACTIVE SYMBOL · RUNTIME" value={model.activeSymbol} className="ams-active-symbol" />
                <Field label="NEXT REQUESTED SYMBOL" value={model.requestedSymbol} />
                <Field label="TOP CANDIDATE · PREVIEW" value={top.symbol} />
                <Field label="AUTO RUNTIME MODE" value={autoRuntime.mode} />
                <Field label="RUNTIME STATE" value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} />
                <Field label="CYCLE STATUS" value={autoRuntime.status} className={statusClass(autoRuntime.status)} />
                <Field label="CYCLE ID" value={autoRuntime.cycleId} />
                <Field label="LAST EVALUATED" value={autoRuntime.evaluatedAt} />
            </div>

            <div className="ams-section-grid">
                <div className="ams-section">
                    <h3>SCANNER</h3>
                    <Field label="STATUS" value={model.scanner.status} className={statusClass(model.scanner.status)} />
                    <Field label="UNIVERSE" value={model.scanner.universeCount} />
                    <Field label="EVALUATED" value={model.scanner.evaluatedCount} />
                    <Field label="ELIGIBLE" value={model.scanner.eligibleCount} />
                    <Field label="REJECTED" value={model.scanner.rejectedCount} />
                    <Field label="EVALUATED AT" value={model.scanner.evaluatedAt} />
                </div>

                <div className="ams-section">
                    <h3>RANKING</h3>
                    <Field label="STATUS" value={model.ranking.status} className={statusClass(model.ranking.status)} />
                    <Field label="RANKED" value={model.ranking.rankedCount} />
                    <Field label="TOP SCORE" value={top.score} />
                    <Field label="SPREAD SCORE" value={top.spreadScore} />
                    <Field label="LIQUIDITY SCORE" value={top.liquidityScore} />
                    <Field label="ACTIVITY SCORE" value={top.activityScore} />
                </div>

                <div className="ams-section">
                    <h3>CAPITAL ELIGIBILITY</h3>
                    <Field label="STATUS" value={capital.status} className={statusClass(capital.status)} />
                    <Field label="AVAILABLE CAPITAL" value={capital.availableCapital} />
                    <Field label="RISK BUDGET" value={capital.riskBudget} />
                    <Field label="REMAINING EXPOSURE" value={capital.remainingExposure} />
                    <Field label="POSITION CAPACITY" value={capital.remainingPositionCapacity} />
                    <Field label="MM REGIME" value={capital.mmRegime} />
                </div>

                <div className="ams-section">
                    <h3>SYMBOL SWITCH</h3>
                    <Field label="STATE" value={switching.state} className={statusClass(switching.state)} />
                    <Field label="PREVIOUS" value={switching.previousSymbol} />
                    <Field label="PROPOSED" value={switching.proposedSymbol} />
                    <Field label="COMMITTED" value={switching.committedSymbol} />
                    <Field label="TRANSACTION" value={switching.transactionId} />
                    <Field label="NEW ENTRIES PAUSED" value={switching.entryPaused} className={switching.entryPaused ? "status-danger" : ""} />
                </div>
            </div>

            <div className="ams-footer">
                <div className="ams-freshness" aria-label="AMS freshness">
                    {Object.entries(model.freshness).map(([key, value]) => (
                        <span key={key} className={statusClass(value)}>{key.toUpperCase()}: {displayAmsValue(value)}</span>
                    ))}
                </div>
                <div className="ams-reasons" aria-label="Selection reasons">
                    <span>REASONS</span>
                    <strong>{primaryReasons.length ? primaryReasons.join(" · ") : "—"}</strong>
                </div>
            </div>
        </section>
    );
}
