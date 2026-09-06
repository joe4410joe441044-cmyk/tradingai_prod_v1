import { createTradingCycleModel, STAGES, STATUS, display, yesNo } from './tradingCycleModel';

const label = (english, japanese) => `${english}（${japanese}）`;

const timestampLabel = (value) => {
    if (!value) return 'NOT AVAILABLE';
    const date = new Date(typeof value === 'number' ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? 'NOT AVAILABLE' : date.toLocaleString();
};

const durationLabel = (value) => {
    if (!value) return 'NOT AVAILABLE';
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
    if (normalized === STATUS.CURRENT) return 'active';
    if (normalized === STATUS.BLOCKED) return 'blocked';
    if (normalized === STATUS.WAITING || normalized === STATUS.NOT_REACHED) return 'idle';
    return 'unknown';
};

const TradingCycleFlow = ({ stages }) => {
    // 布局分为三行：顶部行(0-4), 中间行(5-9), 底部行(10-14)
    const topRow = stages.slice(0, 5);
    const middleRow = stages.slice(5, 10); // 保持正确的顺序
    const bottomRow = stages.slice(10, 15);

    return (
        <section className="trading-cycle-flow" aria-label="Trading Cycle Flow">
            <div className="trading-cycle-row">
                {topRow.map((stage, index) => (
                    <div key={stage.key} className="trading-cycle-stage-wrapper">
                        <div className={`trading-cycle-stage trading-cycle-stage--${toneFor(stage.status)}`} data-status={stage.status}>
                            <div className="trading-cycle-stage-index">{stage.index}</div>
                            <div className="trading-cycle-stage-label">{stage.label}</div>
                            <div className="trading-cycle-stage-status">{stage.status}</div>
                        </div>
                        {index < topRow.length - 1 && (
                            <div className="trading-cycle-connector" aria-hidden="true">→</div>
                        )}
                    </div>
                ))}
            </div>

            <div className="trading-cycle-vertical-connector" aria-hidden="true">↓</div>

            <div className="trading-cycle-row">
                {middleRow.map((stage, index) => (
                    <div key={stage.key} className="trading-cycle-stage-wrapper">
                        <div className={`trading-cycle-stage trading-cycle-stage--${toneFor(stage.status)}`} data-status={stage.status}>
                            <div className="trading-cycle-stage-index">{stage.index}</div>
                            <div className="trading-cycle-stage-label">{stage.label}</div>
                            <div className="trading-cycle-stage-status">{stage.status}</div>
                        </div>
                        {index < middleRow.length - 1 && (
                            <div className="trading-cycle-connector" aria-hidden="true">→</div>
                        )}
                    </div>
                ))}
            </div>

            <div className="trading-cycle-vertical-connector" aria-hidden="true">↓</div>

            <div className="trading-cycle-row">
                {bottomRow.map((stage, index) => (
                    <div key={stage.key} className="trading-cycle-stage-wrapper">
                        <div className={`trading-cycle-stage trading-cycle-stage--${toneFor(stage.status)}`} data-status={stage.status}>
                            <div className="trading-cycle-stage-index">{stage.index}</div>
                            <div className="trading-cycle-stage-label">{stage.label}</div>
                            <div className="trading-cycle-stage-status">{stage.status}</div>
                        </div>
                        {index < bottomRow.length - 1 && (
                            <div className="trading-cycle-connector" aria-hidden="true">→</div>
                        )}
                    </div>
                ))}
            </div>
        </section>
    );
};

const CurrentActivityPanel = ({ model }) => {
    return (
        <section className="current-activity-panel" aria-labelledby="current-activity-title">
            <h3 id="current-activity-title">{label("CURRENT ACTIVITY", "現在処理")}</h3>
            <div className="current-activity-grid">
                <div>
                    <span>{label("CURRENT STAGE", "現在の工程")}</span>
                    <strong>{model.currentStage?.label || ''}</strong>
                </div>
                <div>
                    <span>{label("CURRENT ACTION", "現在のアクション")}</span>
                    <strong>{model.currentActivity}</strong>
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
        </section>
    );
};

const LowerStatusPanel = ({ decision }) => {
    const snapshot = decision || {};
    const stages = snapshot.stages || {};

    return (
        <section className="lower-status-panel" aria-labelledby="lower-status-title">
            <h3 id="lower-status-title">{label("DECISION DETAILS", "判断詳細")}</h3>
            <div className="lower-status-grid">
                <div>
                    <span>{label("FINAL DECISION", "最終判断")}</span>
                    <strong>{display(snapshot.finalDecision, 'NOT AVAILABLE')}</strong>
                </div>
                <div>
                    <span>{label("CURRENT STATE", "現在状態")}</span>
                    <strong>{display(snapshot.currentState)}</strong>
                </div>
                <div>
                    <span>{label("BLOCKED AT", "停止工程")}</span>
                    <strong>{display(snapshot.blockingStage, 'NONE')}</strong>
                </div>
                <div>
                    <span>{label("REASON", "理由")}</span>
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
        </section>
    );
};

export default function TradingDecisionCard({ decision, lastOrderActivity = null, lastOrderValue = null }) {
    const model = createTradingCycleModel(decision);

    return (
        <section className="trading-decision-card" aria-labelledby="trading-decision-title">
            <header className="trading-decision-header">
                <div>
                    <h2 id="trading-decision-title">{label("TRADING CYCLE", "トレーディングサイクル")}</h2>
                </div>
            </header>

            {/* Main Trading Cycle Flow */}
            <TradingCycleFlow stages={model.stages} />

            {/* Current Activity Panel */}
            <CurrentActivityPanel model={model} />

            {/* Lower Status Panel */}
            <LowerStatusPanel decision={decision} />

            {/* Runtime Meta - Compact */}
            <section className="runtime-meta-compact">
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
            </section>

            {/* LAST ORDER — compact footer status (secondary to the cycle stages). */}
            <section className="trading-decision-last-order" data-testid="last-execution-activity">
                <span>{lastOrderActivity?.label ?? "LAST ORDER"}</span>
                <strong>{lastOrderValue ?? "NONE THIS SESSION"}</strong>
            </section>
        </section>
    );
}
