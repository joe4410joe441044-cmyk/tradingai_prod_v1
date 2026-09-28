import { useEffect, useRef, useState } from 'react';

import { createTradingCycleModel, STAGES, STATUS, display, yesNo } from './tradingCycleModel';

const label = (english, japanese) => `${english}（${japanese}）`;

const timestampLabel = (value) => {
    if (value === null || value === undefined) return 'NOT AVAILABLE';
    const date = new Date(typeof value === 'number' ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? 'NOT AVAILABLE' : date.toLocaleString();
};

const durationLabel = (value) => {
    if (value === null || value === undefined) return 'NOT AVAILABLE';
    const started = typeof value === 'number' ? value * 1000 : Date.parse(value);
    if (!Number.isFinite(started)) return 'NOT AVAILABLE';
    const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
};

const toneFor = (status) => {
    const normalized = String(status || '').toUpperCase();
    if (normalized === STATUS.COMPLETED) return 'pass';
    if (normalized === STATUS.CURRENT || normalized === STATUS.ACTIVE) return 'active';
    if (normalized === STATUS.BLOCKED) return 'blocked';
    if (normalized === STATUS.BYPASSED) return 'bypassed';
    if (normalized === STATUS.WAITING || normalized === STATUS.NOT_REACHED) return 'idle';
    return 'unknown';
};

const EMPTY_VALUE = 'NOT AVAILABLE';

const formatDiagnosticValue = (value) => {
    if (value === null || value === undefined) return EMPTY_VALUE;
    if (value === '') return '""';
    if (typeof value === 'boolean') return String(value);
    if (typeof value === 'number') return Number.isFinite(value) ? String(value) : EMPTY_VALUE;
    if (Array.isArray(value)) {
        return value.length ? value.map(formatDiagnosticValue).join(', ') : EMPTY_VALUE;
    }
    if (typeof value === 'object') {
        const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined);
        if (!entries.length) return EMPTY_VALUE;
        return entries
            .map(([key, item]) => `${key}: ${formatDiagnosticValue(item)}`)
            .join(' / ');
    }
    return String(value);
};

const formatFreshness = (freshness) => {
    if (!freshness || typeof freshness !== 'object') return EMPTY_VALUE;
    const state = freshness.state || 'UNKNOWN';
    const age = freshness.ageSeconds;
    return Number.isFinite(age) ? `${state} (${age}s)` : String(state);
};

const StepDiagnosticsPanel = ({ stage, rootBlocker, rootBlockerStep }) => {
    const diagnostic = stage.diagnostic;

    if (!diagnostic) {
        return (
            <div
                className="step-diagnostics step-diagnostics--empty"
                data-testid={`trading-cycle-step-${stage.index}-content`}
                id={`trading-cycle-step-${stage.index}-content`}
            >
                <p className="step-diagnostics__empty">{EMPTY_VALUE}</p>
            </div>
        );
    }

    const isRootBlocker = Number.isInteger(rootBlockerStep) && rootBlockerStep === stage.index;
    const blockerName = rootBlocker && Number.isInteger(rootBlockerStep)
        ? (STAGES.find((item) => item.index === rootBlockerStep)?.label || `STEP ${rootBlockerStep}`)
        : null;
    const relatedParameters = Array.isArray(diagnostic.relatedParameters)
        ? diagnostic.relatedParameters
        : [];

    return (
        <div
            className="step-diagnostics"
            data-testid={`trading-cycle-step-${stage.index}-content`}
            id={`trading-cycle-step-${stage.index}-content`}
        >
            {diagnostic.provenance && (
                <p className="step-diagnostics__meta">
                    EVALUATION: {diagnostic.provenance} · EVALUATION CYCLE: {display(diagnostic.evaluationCycleId)}
                    {' · '}EVALUATED AT: {timestampLabel(diagnostic.evaluatedAt)}
                </p>
            )}
            <dl className="step-diagnostics__list">
                <div className="step-diagnostics__row">
                    <dt>WHY</dt>
                    <dd>
                        <span className="step-diagnostics__reason">
                            {diagnostic.reasonText || diagnostic.reasonCode || EMPTY_VALUE}
                        </span>
                        {diagnostic.reasonCode && (
                            <code className="step-diagnostics__code">{diagnostic.reasonCode}</code>
                        )}
                    </dd>
                </div>

                <div className="step-diagnostics__row">
                    <dt>CURRENT</dt>
                    <dd><strong className="step-diagnostics__value">{formatDiagnosticValue(diagnostic.current)}</strong></dd>
                </div>
                <div className="step-diagnostics__row">
                    <dt>REQUIRED</dt>
                    <dd><strong className="step-diagnostics__value">{formatDiagnosticValue(diagnostic.required)}</strong></dd>
                </div>
                <div className="step-diagnostics__row">
                    <dt>COMPARISON</dt>
                    <dd><strong className="step-diagnostics__value">{diagnostic.comparison || EMPTY_VALUE}</strong></dd>
                </div>

                <div className="step-diagnostics__row">
                    <dt>ROOT BLOCKER</dt>
                    <dd>
                        {isRootBlocker ? (
                            <strong className="step-diagnostics__root">THIS STEP (ROOT BLOCKER)</strong>
                        ) : Number.isInteger(rootBlockerStep) ? (
                            <strong className="step-diagnostics__waiting">
                                WAITING FOR STEP {rootBlockerStep}
                                {blockerName ? ` — ${blockerName}` : ''}
                            </strong>
                        ) : (
                            <strong className="step-diagnostics__value">NONE</strong>
                        )}
                    </dd>
                </div>

                <div className="step-diagnostics__row">
                    <dt>BLOCKER TYPE</dt>
                    <dd><strong className="step-diagnostics__value">{diagnostic.blockerType || 'UNKNOWN'}</strong></dd>
                </div>

                <div className="step-diagnostics__row">
                    <dt>OPERATOR ACTION</dt>
                    <dd>
                        <strong className="step-diagnostics__value">{diagnostic.actionable || 'UNKNOWN'}</strong>
                        {diagnostic.actionable === 'YES' && (
                            <span className="step-diagnostics__hint">Operator-changeable</span>
                        )}
                    </dd>
                </div>

                <div className="step-diagnostics__row">
                    <dt>RELATED PARAMETER</dt>
                    <dd>
                        {relatedParameters.length ? (
                            <ul className="step-diagnostics__parameters">
                                {relatedParameters.map((parameter) => (
                                    <li key={`${stage.index}-${parameter.key}-${parameter.scope || 'NA'}`}>
                                        <code>{parameter.key}</code>
                                        <span>{formatDiagnosticValue(parameter.currentSetting)}</span>
                                        <span className="step-diagnostics__scope">{parameter.scope || 'N/A'}</span>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <strong className="step-diagnostics__value">NONE</strong>
                        )}
                    </dd>
                </div>

                <div className="step-diagnostics__row">
                    <dt>NEXT CONDITION</dt>
                    <dd><strong className="step-diagnostics__value">{formatDiagnosticValue(diagnostic.nextCondition)}</strong></dd>
                </div>
                <div className="step-diagnostics__row">
                    <dt>NEXT STEP</dt>
                    <dd><strong className="step-diagnostics__value">{formatDiagnosticValue(diagnostic.nextStep)}</strong></dd>
                </div>
            </dl>

            {diagnostic.retainedEvaluation && (
                <div data-testid="retained-evaluation">
                    <p className="step-diagnostics__meta">
                        RETAINED EVALUATION · {diagnostic.retainedEvaluation.provenance}
                        {' · '}{formatFreshness(diagnostic.retainedEvaluation.freshness)}
                    </p>
                    <dl className="step-diagnostics__list">
                        {[
                            ['RETAINED REASON', diagnostic.retainedEvaluation.reasonText],
                            ['RECORDED VALUE', diagnostic.retainedEvaluation.current],
                            ['REQUIRED', diagnostic.retainedEvaluation.required],
                            ['COMPARISON', diagnostic.retainedEvaluation.comparison],
                        ].map(([name, value]) => (
                            <div className="step-diagnostics__row" key={name}>
                                <dt>{name}</dt>
                                <dd><strong className="step-diagnostics__value">{formatDiagnosticValue(value)}</strong></dd>
                            </div>
                        ))}
                    </dl>
                </div>
            )}
            <p className="step-diagnostics__meta">
                SOURCE: {diagnostic.source || EMPTY_VALUE} · FRESHNESS: {formatFreshness(diagnostic.freshness)}
            </p>
        </div>
    );
};

const TradingCycleStage = ({ stage, open, onToggle }) => (
    <div className="trading-cycle-stage-wrapper" data-step-index={stage.index}>
        <div className={`trading-cycle-stage trading-cycle-stage--${toneFor(stage.status)}`} data-status={stage.status}>
            <div className="trading-cycle-stage-index">{stage.index}</div>
            <div className="trading-cycle-stage-label">{stage.label}</div>
            <div className="trading-cycle-stage-status">{stage.status}</div>
        </div>
        <div className="trading-cycle-stage-details">
            <button
                aria-controls={`trading-cycle-step-${stage.index}-content`}
                aria-expanded={open}
                aria-haspopup="dialog"
                className="trading-cycle-step-toggle"
                data-testid={`trading-cycle-step-${stage.index}-toggle`}
                onClick={onToggle}
                type="button"
            >
                <span className="trading-cycle-step-toggle__label">DETAILS</span>
                <span aria-hidden="true" className="trading-cycle-step-toggle__indicator">
                    {open ? '▲' : '▼'}
                </span>
            </button>
        </div>
    </div>
);

const TradingCycleFlow = ({ stages, selectedStepIndex, onSelectStep }) => {
    // Left-aligned four-column grid: rows are 0-3 / 4-7 / 8-11 / 12-14.
    // STEP order stays canonical (0..14); only the visual placement changes.
    // The layout is viewport-driven and never reacts to the drawer, so the
    // STEP card coordinates are identical whether the drawer is open or not.
    const COLUMNS = 4;
    const rows = [];
    for (let index = 0; index < stages.length; index += COLUMNS) {
        rows.push(stages.slice(index, index + COLUMNS));
    }

    return (
        <section className="trading-cycle-flow" aria-label="Trading Cycle Flow">
            {rows.map((row, rowIndex) => (
                <div className="trading-cycle-row" data-row={rowIndex} key={`row-${rowIndex}`}>
                    {row.map((stage) => (
                        <TradingCycleStage
                            key={stage.key}
                            stage={stage}
                            open={selectedStepIndex === stage.index}
                            onToggle={() => onSelectStep(stage.index)}
                        />
                    ))}
                </div>
            ))}
        </section>
    );
};

// Non-modal right-side overlay.  The drawer is position:fixed so opening it
// never reflows the Trading Cycle flow or the surrounding dashboard; the
// operator can keep the cycle in view while reading diagnostics.
const TradingCycleDiagnosticsDrawer = ({ stage, onClose, overlayRef, rootBlocker, rootBlockerStep }) => {
    if (!stage) return null;

    const isRootBlocker = Number.isInteger(rootBlockerStep) && rootBlockerStep === stage.index;

    const handleKeyDown = (event) => {
        if (event.key === 'Escape') {
            if (typeof event.stopPropagation === 'function') event.stopPropagation();
            onClose();
        }
    };

    return (
        <div className="trading-cycle-drawer-overlay" data-testid="trading-cycle-drawer-overlay" ref={overlayRef}>
            <aside
                aria-labelledby="trading-cycle-drawer-title"
                aria-modal="false"
                className="trading-cycle-drawer"
                data-testid="trading-cycle-diagnostics-drawer"
                onKeyDown={handleKeyDown}
                role="dialog"
            >
                <header className="trading-cycle-drawer__header">
                    <div className="trading-cycle-drawer__heading">
                        <span className="trading-cycle-drawer__kicker">TRADING CYCLE DIAGNOSTICS</span>
                        <h3 className="trading-cycle-drawer__title" id="trading-cycle-drawer-title">
                            STEP {stage.index}
                            <span className="trading-cycle-drawer__name">{stage.label}</span>
                        </h3>
                        <span className={`trading-cycle-drawer__status trading-cycle-drawer__status--${toneFor(stage.status)}`}>
                            STATUS: {stage.status}
                            {isRootBlocker ? ' · ROOT BLOCKER' : ''}
                        </span>
                    </div>
                    <button
                        aria-label="Close trading cycle diagnostics"
                        autoFocus
                        className="trading-cycle-drawer__close"
                        data-testid="trading-cycle-drawer-close"
                        onClick={onClose}
                        type="button"
                    >
                        × CLOSE
                    </button>
                </header>
                <div className="trading-cycle-drawer__body">
                    <StepDiagnosticsPanel
                        stage={stage}
                        rootBlocker={rootBlocker}
                        rootBlockerStep={rootBlockerStep}
                    />
                </div>
            </aside>
        </div>
    );
};

const DetailDisclosure = ({ className = "", children, id, open, onToggle, title }) => (
    <section className={className}>
        <button
            aria-controls={`${id}-content`}
            aria-expanded={open}
            className="trading-cycle-disclosure__toggle"
            data-testid={`${id}-toggle`}
            onClick={onToggle}
            type="button"
        >
            <span className="trading-cycle-disclosure__title">{title}</span>
            <span
                aria-hidden="true"
                className="trading-cycle-disclosure__indicator"
            >
                {open ? '▲' : '▼'}
            </span>
        </button>
        {open && (
            <div className="trading-cycle-disclosure__body" id={`${id}-content`}>
                {children}
            </div>
        )}
    </section>
);

const CurrentActivityPanel = ({ model, open, onToggle }) => (
    <DetailDisclosure
        className="current-activity-panel"
        id="current-activity-title"
        open={open}
        onToggle={onToggle}
        title={label("CURRENT ACTIVITY", "現在処理")}
    >
        <div className="current-activity-grid">
            <div>
                <span>{label("CURRENT STAGE", "現在の工程")}</span>
                <strong>{model.currentStage?.label || ''}</strong>
            </div>
            <div>
                <span>{label("CURRENT ACTION", "現在のアクション")}</span>
                <strong>{model.currentStageIndex === 4 && model.diagnostics.stepFor(4)?.retainedEvaluation
                    ? model.diagnostics.stepFor(4).reasonCode : model.currentActivity}</strong>
            </div>
            <div>
                <span>{label("SELECTED SYMBOL", "選定された通貨ペア")}</span>
                <strong>{model.selectedSymbol}</strong>
            </div>
            <div>
                <span>{label("NEXT STAGE", "次の工程")}</span>
                <strong>{model.nextStage?.label || ''}</strong>
            </div>
        </div>
    </DetailDisclosure>
);

const LowerStatusPanel = ({ decision, diagnostic, open, onToggle }) => {
    const snapshot = decision || {};
    const stages = snapshot.stages || {};
    const retained = snapshot.currentStageIndex === 4 && diagnostic?.retainedEvaluation;

    return (
        <DetailDisclosure
            className="lower-status-panel"
            id="lower-status-title"
            open={open}
            onToggle={onToggle}
            title={label("DECISION DETAILS", "判断詳細")}
        >
            {retained && <p className="step-diagnostics__meta">STRATEGY EVALUATION: {diagnostic.provenance} · EVALUATION CYCLE: {display(diagnostic.evaluationCycleId)}</p>}
            <div className="lower-status-grid">
                <div>
                    <span>{label("FINAL DECISION", "最終判断")}</span>
                    <strong>{display(snapshot.finalDecision, 'NOT AVAILABLE')}</strong>
                </div>
                <div>
                    <span>{label(retained ? "RECORDED STATE" : "CURRENT STATE", retained ? "記録された状態" : "現在状態")}</span>
                    <strong>{display(snapshot.currentState)}</strong>
                </div>
                <div>
                    <span>{label(retained ? "RECORDED BLOCK" : "BLOCKED AT", "停止工程")}</span>
                    <strong>{display(snapshot.blockingStage, 'NONE')}</strong>
                </div>
                <div>
                    <span>{label(retained ? "RETAINED REASON" : "REASON", "理由")}</span>
                    <strong>{display(snapshot.blockingReason, 'NONE')}</strong>
                </div>
                <div>
                    <span>{label("CYCLE ID", "サイクルID")}</span>
                    <strong>{display(snapshot.cycleId, "NOT AVAILABLE")}</strong>
                </div>
                <div>
                    <span>{label("PENDING ORDER", "保留注文")}</span>
                    <strong>{stages?.execution?.orderState == null ? "NOT AVAILABLE" : stages.execution.orderState === "NONE" ? "NO" : "YES"}</strong>
                </div>
                <div>
                    <span>{label("LAST UPDATE", "最終更新")}</span>
                    <strong>{timestampLabel(snapshot.timestamp)}</strong>
                </div>
                <div>
                    <span>{label("STATE DURATION", "状態継続時間")}</span>
                    <strong>{durationLabel(snapshot.stateSince)}</strong>
                </div>
            </div>
        </DetailDisclosure>
    );
};

export default function TradingDecisionCard({ decision, diagnostics = null, lastOrderActivity = null, lastOrderValue = null }) {
    const model = createTradingCycleModel(decision, diagnostics);
    const [currentActivityOpen, setCurrentActivityOpen] = useState(false);
    const [decisionDetailsOpen, setDecisionDetailsOpen] = useState(false);
    const [thirdSectionOpen, setThirdSectionOpen] = useState(false);
    const [selectedStepIndex, setSelectedStepIndex] = useState(null);
    const drawerOverlayRef = useRef(null);

    const selectStep = (index) => {
        setSelectedStepIndex((current) => (current === index ? null : index));
    };

    useEffect(() => {
        if (selectedStepIndex === null) return undefined;
        const handleEscape = (event) => {
            if (event.key === 'Escape') setSelectedStepIndex(null);
        };
        window.addEventListener('keydown', handleEscape);
        return () => window.removeEventListener('keydown', handleEscape);
    }, [selectedStepIndex]);

    // Keep the fixed drawer clear of the app top chrome (AppNavigation +
    // status header). Their heights are not fixed, so measure the stable
    // document offset instead of hardcoding a top value.
    useEffect(() => {
        if (selectedStepIndex === null) return undefined;
        const overlay = drawerOverlayRef.current;
        if (!overlay) return undefined;

        const layoutBottom = (element) => {
            let offset = 0;
            let node = element;
            while (node) {
                offset += node.offsetTop || 0;
                node = node.offsetParent;
            }
            return offset + element.offsetHeight;
        };

        const measure = () => {
            let bottom = 0;
            ['.mi-app-navigation', '.app-header'].forEach((selector) => {
                const element = document.querySelector(selector);
                if (element) bottom = Math.max(bottom, layoutBottom(element));
            });
            if (bottom > 0) overlay.style.top = `${Math.ceil(bottom)}px`;
        };

        measure();
        window.addEventListener('resize', measure);
        return () => window.removeEventListener('resize', measure);
    }, [selectedStepIndex]);

    const rootBlocker = model.diagnostics?.rootBlocker || diagnostics?.rootBlocker || null;
    const rootBlockerStep = model.diagnostics?.rootBlockerStep ?? null;
    const selectedStage = selectedStepIndex === null
        ? null
        : model.stages.find((stage) => stage.index === selectedStepIndex) || null;

    return (
        <section className="trading-decision-card" aria-labelledby="trading-decision-title">
            <header className="trading-decision-header">
                <div>
                    <h2 id="trading-decision-title">{label("TRADING CYCLE", "トレーディングサイクル")}</h2>
                </div>
            </header>

            {/* Main Trading Cycle Flow */}
            <TradingCycleFlow
                stages={model.stages}
                selectedStepIndex={selectedStepIndex}
                onSelectStep={selectStep}
            />

            {/* Right-side overlay diagnostics drawer (single instance) */}
            <TradingCycleDiagnosticsDrawer
                stage={selectedStage}
                onClose={() => setSelectedStepIndex(null)}
                overlayRef={drawerOverlayRef}
                rootBlocker={rootBlocker}
                rootBlockerStep={rootBlockerStep}
            />

            {/* Current Activity Panel */}
            <CurrentActivityPanel
                model={model}
                open={currentActivityOpen}
                onToggle={() => setCurrentActivityOpen((value) => !value)}
            />

            {/* Lower Status Panel */}
            <LowerStatusPanel
                decision={decision}
                diagnostic={model.diagnostics.stepFor(4)}
                open={decisionDetailsOpen}
                onToggle={() => setDecisionDetailsOpen((value) => !value)}
            />

            {/* Runtime Meta - Compact (third existing detail section) */}
            <DetailDisclosure
                className="runtime-meta-compact"
                id="runtime-meta-title"
                open={thirdSectionOpen}
                onToggle={() => setThirdSectionOpen((value) => !value)}
                title={label("RUNTIME STATUS", "ランタイム状態")}
            >
                <div className="runtime-meta-grid">
                    <div>
                        <span>{label("MODE", "モード")}</span>
                        <strong>{display(decision?.mode)}</strong>
                    </div>
                    <div>
                        <span>{label("EXCHANGE", "取引所")}</span>
                        <strong>{display(decision?.exchange)}</strong>
                    </div>
                    <div>
                        <span>{label("REAL ORDER", "実注文")}</span>
                        <strong>{yesNo(decision?.realOrderAllowed)}</strong>
                    </div>
                    <div>
                        <span>{label("BOT", "ボット")}</span>
                        <strong>{display(decision?.bot ?? decision?.botRunning)}</strong>
                    </div>
                    <div>
                        <span>{label("LOOP", "ループ")}</span>
                        <strong>{display(decision?.loop ?? decision?.loopState ?? decision?.loopRunning)}</strong>
                    </div>
                    <div>
                        <span>{label("AUTO TRADE", "自動売買")}</span>
                        <strong>{display(decision?.autoTrade ?? decision?.autoTradeEnabled)}</strong>
                    </div>
                </div>
            </DetailDisclosure>

            {/* LAST ORDER — compact footer status (secondary to the cycle stages). */}
            <section className="trading-decision-last-order" data-testid="last-execution-activity">
                <span>{lastOrderActivity?.label ?? "LAST ORDER"}</span>
                <strong>{lastOrderValue ?? "NONE THIS SESSION"}</strong>
            </section>
        </section>
    );
}
