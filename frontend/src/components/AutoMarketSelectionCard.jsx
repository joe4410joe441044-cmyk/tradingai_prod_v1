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

// G6: bilingual fixed UI labels. ENGLISH / 日本語 — dynamic values and machine
// identifiers are never translated.
const bi = (english, japanese) => `${english} / ${japanese}`;

const FRESHNESS_LABELS = Object.freeze({
    universe: bi("UNIVERSE", "対象市場"),
    scanner: bi("SCANNER", "スキャナー"),
    ranking: bi("RANKING", "ランキング"),
    mm: "MM",
});

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
    const reselectJapanese = reselectBusy ? "再選定中…" : "スキップ / 再選定";
    const reselectTitle = reselectBlocked ? (reselect.reason || "RESELECT_UNAVAILABLE") : "SKIP / RESELECT";

    return (
        <section className={`panel-card ams-card${collapsible ? " ams-card--collapsible" : ""}`} aria-labelledby="ams-card-title" data-testid="auto-market-selection-card">
            <div className="ams-card-header">
                <span className="ams-card-heading">
                    <span id="ams-card-title" className="governance-card-title">{bi("AUTO MARKET SELECTION", "自動市場選定")}</span>
                    <span className="ams-card-subtitle">Market Scanner / Ranking / Selection</span>
                    <span className="ams-card-subtitle">市場スキャン / ランキング / 選定</span>
                </span>
                <span className="ams-card-header-status">
                    <span className={`ams-read-status ${statusClass(model.availability)}`}>{model.availability}</span>
                </span>
            </div>

            {/* ESSENTIAL OPERATOR VIEW — always visible */}
            <div className="ams-essential" data-testid="auto-market-selection-essential">
                <div className="ams-essential-grid">
                    <Field label={bi("ACTIVE SYMBOL", "現在銘柄")} value={model.activeSymbol} className="ams-active-symbol" wrap />
                    <Field label={bi("TOP CANDIDATE", "最有力候補") + " · PREVIEW"} value={top.symbol} wrap />
                    <Field label={bi("STATUS", "状態")} value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} wrap />
                    <Field label={bi("LAST EVALUATED", "最終評価")} value={autoRuntime.evaluatedAt} wrap />
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
                            <span className="ams-reselect-label">{reselectLabel}</span>
                            <span className="ams-reselect-label-ja">{reselectJapanese}</span>
                        </button>
                    </div>
                </div>

                <div className="ams-capital-summary" data-testid="auto-market-selection-capital-summary">
                    <span className="ams-capital-title">{bi("CAPITAL", "資金")}</span>
                    <div className="ams-capital-grid">
                        <Field label={bi("STATUS", "状態")} value={capital.status} className={statusClass(capital.status)} wrap />
                        <Field label={bi("AVAILABLE CAPITAL", "利用可能資金")} value={capital.availableCapital} wrap />
                        <Field label={bi("RISK BUDGET", "リスク予算")} value={capital.riskBudget} wrap />
                    </div>
                </div>

                <div className="ams-reasons ams-reasons--current" aria-label="Current reasons" data-testid="auto-market-selection-current-reasons">
                    <span>{bi("CURRENT REASONS", "現在の理由")}</span>
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
                {bi("DETAILS / DIAGNOSTICS", "詳細・診断")}
            </button>

            {expanded && <div id="ams-card-details" className="ams-details" data-testid="auto-market-selection-details">

            <div className="ams-symbol-grid">
                <Field label={bi("SELECTION MODE", "選定モード")} value={selectionModeDisplayLabel(model.selectionMode)} wrap />
                <Field label={bi("NEXT REQUESTED SYMBOL", "次回要求銘柄")} value={model.requestedSymbol} wrap />
                <Field label={bi("AUTO RUNTIME MODE", "自動実行モード")} value={autoRuntime.mode} wrap />
                <Field label={bi("RUNTIME STATE", "実行状態")} value={autoRuntime.runtimeState} className={statusClass(autoRuntime.runtimeState)} wrap />
                <Field label={bi("CYCLE STATUS", "サイクル状態")} value={autoRuntime.status} className={statusClass(autoRuntime.status)} wrap />
                <Field label={bi("CYCLE ID", "サイクルID")} value={autoRuntime.cycleId} title={displayAmsValue(autoRuntime.cycleId)} />
                <Field label={bi("LAST CYCLE STATUS", "前回サイクル状態")} value={autoRuntime.lastCycleStatus} className={statusClass(autoRuntime.lastCycleStatus)} wrap />
                <Field label={bi("LAST CYCLE ID", "前回サイクルID")} value={autoRuntime.lastCycleId} title={displayAmsValue(autoRuntime.lastCycleId)} />
            </div>

            <div className="ams-section-grid">
                <div className="ams-section">
                    <h3>{bi("SCANNER", "スキャナー")}</h3>
                    <Field label={bi("STATUS", "状態")} value={model.scanner.status} className={statusClass(model.scanner.status)} />
                    <Field label={bi("UNIVERSE", "対象市場数")} value={model.scanner.universeCount} />
                    <Field label={bi("EVALUATED", "評価済み")} value={model.scanner.evaluatedCount} />
                    <Field label={bi("ELIGIBLE", "適格")} value={model.scanner.eligibleCount} />
                    <Field label={bi("REJECTED", "除外")} value={model.scanner.rejectedCount} />
                    <Field label={bi("EVALUATED AT", "評価時刻")} value={model.scanner.evaluatedAt} />
                </div>

                <div className="ams-section">
                    <h3>{bi("RANKING", "ランキング")}</h3>
                    <Field label={bi("STATUS", "状態")} value={model.ranking.status} className={statusClass(model.ranking.status)} />
                    <Field label={bi("RANKED", "ランク対象")} value={model.ranking.rankedCount} />
                    <Field label={bi("TOP SCORE", "最高スコア")} value={top.score} />
                    <Field label={bi("SPREAD SCORE", "スプレッド評価")} value={top.spreadScore} />
                    <Field label={bi("LIQUIDITY SCORE", "流動性評価")} value={top.liquidityScore} />
                    <Field label={bi("ACTIVITY SCORE", "活動度評価")} value={top.activityScore} />
                </div>

                <div className="ams-section">
                    <h3>{bi("CAPITAL DETAILS", "資金詳細")}</h3>
                    <Field label={bi("REMAINING EXPOSURE", "残り許容エクスポージャー")} value={capital.remainingExposure} />
                    <Field label={bi("POSITION CAPACITY", "建玉余力")} value={capital.remainingPositionCapacity} />
                    <Field label={bi("MM REGIME", "MM運用状態")} value={capital.mmRegime} wrap />
                </div>

                <div className="ams-section">
                    <h3>{bi("SYMBOL SWITCH", "銘柄切替")}</h3>
                    <Field label={bi("STATE", "状態")} value={switching.state} className={statusClass(switching.state)} wrap />
                    <Field label={bi("PREVIOUS", "前回")} value={switching.previousSymbol} wrap />
                    <Field label={bi("PROPOSED", "候補")} value={switching.proposedSymbol} wrap />
                    <Field label={bi("COMMITTED", "確定")} value={switching.committedSymbol} wrap />
                    <Field label={bi("TRANSACTION", "トランザクション")} value={switching.transactionId} title={displayAmsValue(switching.transactionId)} />
                    <Field label={bi("NEW ENTRIES PAUSED", "新規エントリー停止")} value={switching.entryPaused} className={switching.entryPaused ? "status-danger" : ""} />
                </div>
            </div>

            <div className="ams-footer">
                <div className="ams-freshness" aria-label="AMS freshness">
                    {Object.entries(model.freshness).map(([key, value]) => (
                        <span key={key} className={statusClass(value)}>{FRESHNESS_LABELS[key] ?? key.toUpperCase()}: {displayAmsValue(value)}</span>
                    ))}
                </div>
                <div className="ams-reasons" aria-label="Last cycle reasons" data-testid="auto-market-selection-last-cycle-reasons">
                    <span>{bi("LAST CYCLE REASONS", "前回サイクルの理由")}</span>
                    <strong>{lastCycleReasons.length ? lastCycleReasons.join(" · ") : "—"}</strong>
                </div>
            </div>
            </div>}
        </section>
    );
}
