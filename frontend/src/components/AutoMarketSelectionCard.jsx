import { useState } from "react";

import { buildAutoMarketSelectionModel, buildAutoMarketSelectionReasons, deriveReselectControl, displayAmsValue } from "../features/auto-market-selection/autoMarketSelectionModel.js";
import { selectionModeDisplayLabel } from "./operation/operationPreparationModel.js";

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

export default function AutoMarketSelectionCard({
    status, requestedSymbol, collapsible = false,
    onReselect, reselectDisabled = false, reselectBusy = false, reselectReason = null,
}) {
    const [expanded, setExpanded] = useState(!collapsible);
    const model = buildAutoMarketSelectionModel(status, requestedSymbol);
    const top = model.topCandidate;
    const capital = model.capitalEligibility;
    const switching = model.switch;
    const autoRuntime = model.autoRuntime;
    const { historical: lastCycleReasons, current: currentReasons } = buildAutoMarketSelectionReasons(model);
    const reselect = deriveReselectControl(status, {
        disabled: reselectDisabled,
        reason: reselectReason,
    });
    const reselectBlocked = reselect.disabled || reselectBusy;
    const reselectLabel = reselectBusy ? "↻ RESELECTING…" : "↻ SKIP / RESELECT";
    const reselectTitle = reselectBlocked ? (reselect.reason || "RESELECT_UNAVAILABLE") : "SKIP / RESELECT";

    return (
        <section className={`panel-card ams-card${collapsible ? " ams-card--collapsible" : ""}`} aria-labelledby="ams-card-title" data-testid="auto-market-selection-card">
            <div className="ams-card-header">
                <button
                    className="ams-card-heading-toggle"
                    type="button"
                    aria-expanded={expanded}
                    aria-controls="ams-card-details"
                    onClick={() => collapsible && setExpanded((value) => !value)}
                    disabled={!collapsible}
                >
                    <span className="ams-card-heading">
                        <span id="ams-card-title" className="governance-card-title">AUTO MARKET SELECTION</span>
                        <span className="ams-card-subtitle">Market Scanner / Ranking / Selection</span>
                    </span>
                </button>
                <span className="ams-card-header-status">
                    <span className={`ams-read-status ${statusClass(model.availability)}`}>{model.availability}</span>
                    {collapsible && <span className="ams-disclosure-icon" aria-hidden="true">{expanded ? "▴" : "▾"}</span>}
                </span>
            </div>

            {collapsible && !expanded && (
                <div className="ams-summary" data-testid="auto-market-selection-summary">
                    <Field label="MODE" value={selectionModeDisplayLabel(model.selectionMode)} />
                    <Field label="TOP CANDIDATE" value={top.symbol} />
                    <Field label="ACTIVE SYMBOL" value={model.activeSymbol} className="ams-active-symbol" />
                    <Field label="SELECTION STATE" value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} />
                </div>
            )}

            {expanded && <div id="ams-card-details" data-testid="auto-market-selection-details">

            <div className="ams-symbol-grid">
                <Field label="SELECTION MODE" value={selectionModeDisplayLabel(model.selectionMode)} />
                <Field label="ACTIVE SYMBOL · RUNTIME" value={model.activeSymbol} className="ams-active-symbol" />
                <Field label="NEXT REQUESTED SYMBOL" value={model.requestedSymbol} />
                <Field label="TOP CANDIDATE · PREVIEW" value={top.symbol} />
                <Field label="AUTO RUNTIME MODE" value={autoRuntime.mode} />
                <Field label="RUNTIME STATE" value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} />
                <Field label="CYCLE STATUS" value={autoRuntime.status} className={statusClass(autoRuntime.status)} />
                <Field label="CYCLE ID" value={autoRuntime.cycleId} />
                <Field label="LAST CYCLE STATUS" value={autoRuntime.lastCycleStatus} className={statusClass(autoRuntime.lastCycleStatus)} />
                <Field label="LAST CYCLE ID" value={autoRuntime.lastCycleId} />
                <Field label="LAST EVALUATED" value={autoRuntime.evaluatedAt} />
                <div className="ams-reselect-cell">
                    <button
                        className={`ams-reselect${reselectBlocked ? " ams-reselect--disabled" : ""}`}
                        type="button"
                        data-testid="auto-market-selection-reselect"
                        title={reselectTitle}
                        aria-label={`SKIP / RESELECT${reselectBlocked ? ` (${reselectTitle})` : ""}`}
                        disabled={reselectBlocked}
                        onClick={() => { if (typeof onReselect === "function") onReselect(); }}
                    >
                        {reselectLabel}
                    </button>
                </div>
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
                <div className="ams-reasons" aria-label="Last cycle reasons">
                    <span>LAST CYCLE REASONS</span>
                    <strong>{lastCycleReasons.length ? lastCycleReasons.join(" · ") : "—"}</strong>
                </div>
                <div className="ams-reasons" aria-label="Current reasons">
                    <span>CURRENT REASONS</span>
                    <strong>{currentReasons.length ? currentReasons.join(" · ") : "—"}</strong>
                </div>
            </div>
            </div>}
        </section>
    );
}
