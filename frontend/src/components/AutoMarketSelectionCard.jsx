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

// wrap: critical operator values must never be ellipsized.
// title: machine identifiers may stay single-line but expose the full value.
const Field = ({ label, value, className = "", wrap = false, title }) => (
    <div className={`ams-field${wrap ? " ams-field--wrap" : ""}`}>
        <span className="ams-field-label">{label}</span>
        <strong className={`ams-field-value ${className}`} title={title}>{displayAmsValue(value)}</strong>
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
                <span className="ams-card-heading">
                    <span id="ams-card-title" className="governance-card-title">AUTO MARKET SELECTION</span>
                    <span className="ams-card-subtitle">Market Scanner / Ranking / Selection</span>
                </span>
                <span className="ams-card-header-status">
                    <span className={`ams-read-status ${statusClass(model.availability)}`}>{model.availability}</span>
                </span>
            </div>

            {/* ESSENTIAL OPERATOR VIEW — always visible */}
            <div className="ams-essential" data-testid="auto-market-selection-essential">
                <div className="ams-essential-grid">
                    <Field label="ACTIVE SYMBOL" value={model.activeSymbol} className="ams-active-symbol" wrap />
                    <Field label="TOP CANDIDATE · PREVIEW" value={top.symbol} wrap />
                    <Field label="STATUS" value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} wrap />
                    <Field label="LAST EVALUATED" value={autoRuntime.evaluatedAt} wrap />
                </div>

                <div className="ams-essential-actions">
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

                <div className="ams-capital-summary" data-testid="auto-market-selection-capital-summary">
                    <span className="ams-capital-title">CAPITAL</span>
                    <div className="ams-capital-grid">
                        <Field label="STATUS" value={capital.status} className={statusClass(capital.status)} wrap />
                        <Field label="AVAILABLE CAPITAL" value={capital.availableCapital} wrap />
                        <Field label="RISK BUDGET" value={capital.riskBudget} wrap />
                    </div>
                </div>

                <div className="ams-reasons ams-reasons--current" aria-label="Current reasons" data-testid="auto-market-selection-current-reasons">
                    <span>CURRENT REASONS</span>
                    <strong>{currentReasons.length ? currentReasons.join(" · ") : "—"}</strong>
                </div>
            </div>

            <button
                className="ams-details-toggle"
                type="button"
                aria-expanded={expanded}
                aria-controls="ams-card-details"
                data-testid="auto-market-selection-details-toggle"
                onClick={() => setExpanded((value) => !value)}
            >
                <span className="ams-disclosure-icon" aria-hidden="true">{expanded ? "▴" : "▾"}</span>
                DETAILS / DIAGNOSTICS
            </button>

            {expanded && <div id="ams-card-details" className="ams-details" data-testid="auto-market-selection-details">

            <div className="ams-symbol-grid">
                <Field label="SELECTION MODE" value={selectionModeDisplayLabel(model.selectionMode)} wrap />
                <Field label="NEXT REQUESTED SYMBOL" value={model.requestedSymbol} wrap />
                <Field label="AUTO RUNTIME MODE" value={autoRuntime.mode} wrap />
                <Field label="RUNTIME STATE" value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} wrap />
                <Field label="CYCLE STATUS" value={autoRuntime.status} className={statusClass(autoRuntime.status)} wrap />
                <Field label="CYCLE ID" value={autoRuntime.cycleId} title={displayAmsValue(autoRuntime.cycleId)} />
                <Field label="LAST CYCLE STATUS" value={autoRuntime.lastCycleStatus} className={statusClass(autoRuntime.lastCycleStatus)} wrap />
                <Field label="LAST CYCLE ID" value={autoRuntime.lastCycleId} title={displayAmsValue(autoRuntime.lastCycleId)} />
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
                    <h3>CAPITAL DETAILS</h3>
                    <Field label="REMAINING EXPOSURE" value={capital.remainingExposure} />
                    <Field label="POSITION CAPACITY" value={capital.remainingPositionCapacity} />
                    <Field label="MM REGIME" value={capital.mmRegime} wrap />
                </div>

                <div className="ams-section">
                    <h3>SYMBOL SWITCH</h3>
                    <Field label="STATE" value={switching.state} className={statusClass(switching.state)} wrap />
                    <Field label="PREVIOUS" value={switching.previousSymbol} wrap />
                    <Field label="PROPOSED" value={switching.proposedSymbol} wrap />
                    <Field label="COMMITTED" value={switching.committedSymbol} wrap />
                    <Field label="TRANSACTION" value={switching.transactionId} title={displayAmsValue(switching.transactionId)} />
                    <Field label="NEW ENTRIES PAUSED" value={switching.entryPaused} className={switching.entryPaused ? "status-danger" : ""} />
                </div>
            </div>

            <div className="ams-footer">
                <div className="ams-freshness" aria-label="AMS freshness">
                    {Object.entries(model.freshness).map(([key, value]) => (
                        <span key={key} className={statusClass(value)}>{key.toUpperCase()}: {displayAmsValue(value)}</span>
                    ))}
                </div>
                <div className="ams-reasons" aria-label="Last cycle reasons" data-testid="auto-market-selection-last-cycle-reasons">
                    <span>LAST CYCLE REASONS</span>
                    <strong>{lastCycleReasons.length ? lastCycleReasons.join(" · ") : "—"}</strong>
                </div>
            </div>
            </div>}
        </section>
    );
}
