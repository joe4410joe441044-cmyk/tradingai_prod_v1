const STAGES = [
    ["market", "MARKET（市場）"],
    ["pythonStrategy", "PYTHON STRATEGY（Python戦略）"],
    ["moneyManagement", "MONEY MANAGEMENT（資金管理）"],
    ["governance", "GOVERNANCE（安全判定）"],
    ["execution", "EXECUTION（注文実行）"],
    ["position", "POSITION（ポジション）"],
];

const label = (english, japanese) => `${english}（${japanese}）`;

const display = (value, fallback = "--") => (
    value === null || value === undefined || value === "" ? fallback : String(value)
);

const yesNo = (value) => (value === true ? "YES" : value === false ? "NO" : "--");
const publishedYesNo = (value) => (
    value === true ? "YES" : value === false ? "NO" : label("NOT PUBLISHED", "未公開")
);
const operationalStatus = (value, trueLabel = "RUNNING", falseLabel = "STOPPED") => {
    if (value === true) return trueLabel;
    if (value === false) return falseLabel;
    return display(value, "NOT AVAILABLE");
};
const percentage = (value) => (
    value === null || value === undefined || value === ""
        ? "--"
        : `${(Number(value) * 100).toFixed(1)} %`
);
const timestampLabel = (value) => {
    if (!value) return "NOT AVAILABLE";
    const date = new Date(typeof value === "number" ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? "NOT AVAILABLE" : date.toLocaleString();
};
const durationLabel = (value) => {
    if (!value) return "NOT AVAILABLE";
    const started = typeof value === "number" ? value * 1000 : Date.parse(value);
    if (!Number.isFinite(started)) return "NOT AVAILABLE";
    const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
};

const numberLabel = (value, code) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "--";
    if (code === "LIQUIDITY_VOLUME") return numeric.toLocaleString();
    return numeric.toFixed(code === "SPREAD" ? 5 : 4);
};

const conditionByCode = (readiness, code) => (
    readiness?.conditions?.find((condition) => condition.code === code)
);

const conditionValue = (condition) => {
    if (!condition) return "NOT AVAILABLE";
    if (condition.expected !== null && condition.expected !== undefined) {
        return `${display(condition.currentValue)} / expected ${display(condition.expected)}`;
    }
    return `${numberLabel(condition.currentValue, condition.code)} / ${display(condition.operator)}${numberLabel(condition.threshold, condition.code)}`;
};

const ReadinessCondition = ({ condition, labelText }) => (
    <div className="entry-readiness-condition">
        <div><span>{labelText}</span><strong className={`decision-tone decision-tone--${toneFor(condition?.status)}`}>{display(condition?.status, "NOT AVAILABLE")}</strong></div>
        <small>{conditionValue(condition)}</small>
    </div>
);

const EntryReadiness = ({ readiness }) => {
    if (readiness?.available !== true) return (
        <section className="entry-readiness entry-readiness--unavailable">
            <h3>{label("ENTRY READINESS", "エントリー準備")}</h3>
            <p>{label("Detailed entry conditions are not exposed by the current runtime.", "現在のランタイムでは詳細なエントリー条件を取得できません。")}</p>
        </section>
    );
    const safety = conditionByCode(readiness, "LIQUIDITY_SAFETY");
    const rows = [
        ["SPREAD", "Spread"], ["SPREAD_VOLATILITY", "Spread Stability"],
        ["LIQUIDITY_QUALITY", "Liquidity"], ["MOMENTUM", "Momentum"],
        ["PRESSURE_ALIGNMENT", "Pressure Alignment"], ["EDGE", "Edge"],
        ["CONFIDENCE", "Confidence"],
    ];
    return (
        <section className="entry-readiness" aria-labelledby="entry-readiness-title">
            <div className="entry-readiness-heading">
                <h3 id="entry-readiness-title">{label("ENTRY READINESS", "エントリー準備")}</h3>
                <span>Candidate <strong>{display(readiness.candidateDirection)}</strong></span>
                <span>Python Decision <strong>{display(readiness.strategyDecision)}</strong></span>
                <span>Primary Blocker <strong>{display(readiness.blockingCondition, "NONE")}</strong></span>
            </div>
            <div className="entry-readiness-grid">
                {rows.map(([code, title]) => <ReadinessCondition key={code} condition={conditionByCode(readiness, code)} labelText={title} />)}
                <div className="entry-readiness-condition"><div><span>Liquidity Safety</span><strong className={`decision-tone decision-tone--${toneFor(safety?.status)}`}>{display(safety?.status, "NOT AVAILABLE")}</strong></div><small>Absorption / Stagnant / Fake Pressure</small></div>
            </div>
        </section>
    );
};

const toneFor = (value) => {
    const status = String(value || "").toUpperCase();
    if (["PASS", "BUY", "SELL", "POSITION OPEN"].includes(status)) return "pass";
    if (["FAIL", "HOLD", "BLOCK", "ENTRY BLOCKED"].includes(status)) return "blocked";
    if (["NO ORDER", "NOT REACHED", "NOT TRIGGERED", "WAITING FOR SIGNAL"].includes(status)) return "idle";
    if (["WAITING FOR FILL", "CALLED", "READY FOR ORDER"].includes(status)) return "active";
    return "unknown";
};

const stageMatchesBlock = (key, blockingStage) => {
    const normalized = String(blockingStage || "").toUpperCase();
    return {
        market: "MARKET",
        pythonStrategy: "PYTHON STRATEGY",
        moneyManagement: "MONEY MANAGEMENT",
        governance: "GOVERNANCE",
        execution: "EXECUTION",
        position: "POSITION",
    }[key] === normalized;
};

const confidenceTone = (value) => {
    const confidence = Number(value);
    if (!Number.isFinite(confidence)) return "unknown";
    if (confidence < 0.2) return "low";
    if (confidence < 0.5) return "medium";
    return "high";
};

const ConfidenceValue = ({ value }) => {
    const numericValue = Number(value);
    const published = value !== null && value !== undefined && value !== "" && Number.isFinite(numericValue);
    const width = published ? `${Math.max(0, Math.min(100, numericValue * 100))}%` : "0%";

    return (
        <div className={`trading-decision-confidence confidence-tone--${confidenceTone(value)}`}>
            <strong>{percentage(value)}</strong>
            <span className="trading-decision-confidence-track" role="progressbar" aria-label={label("CONFIDENCE", "信頼度")} aria-valuemin="0" aria-valuemax="100" aria-valuenow={published ? numericValue * 100 : undefined}>
                <i style={{ width }} />
            </span>
        </div>
    );
};

const blockContext = (snapshot) => {
    const stageName = String(snapshot.blockingStage || "").toUpperCase();
    const stage = snapshot.stages || {};

    if (stageName === "PYTHON STRATEGY" && snapshot.entryReadiness?.available) {
        const readiness = snapshot.entryReadiness;
        const blocker = conditionByCode(readiness, readiness.blockingCondition);
        return {
            title: label("PYTHON STRATEGY", "Python戦略"),
            items: [
                [label("CANDIDATE", "候補"), display(readiness.candidateDirection)],
                [label("PRIMARY BLOCKER", "主停止条件"), display(readiness.blockingCondition)],
                [label("CURRENT", "現在値"), numberLabel(blocker?.currentValue, blocker?.code)],
                [label("REQUIRED", "必要値"), blocker ? `${blocker.operator}${numberLabel(blocker.threshold, blocker.code)}` : "--"],
                ...(blocker?.delta == null ? [] : [[`${display(readiness.blockingCondition)} GAP`, numberLabel(blocker.delta, blocker.code)]]),
            ],
        };
    }
    if (stageName === "PYTHON STRATEGY") return {
        title: label("PYTHON STRATEGY", "Python戦略"),
        items: [
            [label("CONFIDENCE", "信頼度"), stage.pythonStrategy?.confidence, "confidence"],
            [label("EXECUTION ALLOWED", "実行許可"), publishedYesNo(stage.pythonStrategy?.executionAllowed)],
            [label("STRATEGY RESULT", "戦略結果"), display(stage.pythonStrategy?.decision)],
            [label("SUPPRESSION REASON", "抑制理由"), display(stage.pythonStrategy?.suppressionReason)],
        ],
    };
    if (stageName === "MONEY MANAGEMENT") return {
        title: label("MONEY MANAGEMENT", "資金管理"),
        items: [
            [label("RISK", "リスク"), display(stage.moneyManagement?.riskAmount)],
            [label("EXPOSURE", "エクスポージャー"), display(stage.moneyManagement?.exposure)],
            [label("REASON", "理由"), display(stage.moneyManagement?.reason)],
        ],
    };
    if (stageName === "GOVERNANCE") return {
        title: label("GOVERNANCE", "安全判定"),
        items: [
            [label("RULE", "ルール"), display(stage.governance?.executionAuthority)],
            [label("BLOCK REASON", "停止理由"), display(stage.governance?.reason)],
            [label("DECISION", "判断"), display(stage.governance?.decision)],
        ],
    };
    if (stageName === "EXECUTION") return {
        title: label("EXECUTION", "注文実行"),
        items: [
            [label("ORDER STATE", "注文状態"), display(stage.execution?.orderState)],
            [label("PENDING", "保留"), display(stage.execution?.orderState)],
            [label("WAITING FILL", "約定待ち"), display(stage.execution?.state)],
        ],
    };
    if (stageName === "POSITION" || String(snapshot.currentState || "").toUpperCase() === "POSITION OPEN") return {
        title: label("POSITION", "ポジション"),
        items: [
            [label("POSITION", "方向"), display(stage.execution?.positionState)],
            [label("ENTRY PRICE", "建値"), display(stage.position?.entryPrice)],
            [label("CURRENT PNL", "現在損益"), display(stage.position?.currentPnl)],
        ],
    };
    return {
        title: display(snapshot.blockingStage, label("NO ACTIVE BLOCK", "停止なし")),
        items: [[label("BLOCK REASON", "停止理由"), display(snapshot.blockingReason)]],
    };
};

const CurrentBlockContext = ({ snapshot }) => {
    const context = blockContext(snapshot);
    return (
        <section className="trading-decision-context" aria-labelledby="current-block-context-title">
            <div className="trading-decision-context-heading">
                <h3 id="current-block-context-title">{label("CURRENT BLOCK CONTEXT", "現在停止工程")}</h3>
                <strong>{context.title}</strong>
            </div>
            <div className="trading-decision-context-grid">
                {context.items.map(([itemLabel, value, kind]) => (
                    <div className={kind === "confidence" ? "is-confidence" : undefined} key={itemLabel}>
                        <span>{itemLabel}</span>
                        {kind === "confidence" ? <ConfidenceValue value={value} /> : <strong>{value}</strong>}
                    </div>
                ))}
            </div>
        </section>
    );
};

const StageValue = ({ stage }) => {
    const status = display(stage?.status, "NOT AVAILABLE");
    const details = [];
    if (stage?.decision && stage.decision !== stage.status) details.push(stage.decision);
    if (stage?.confidence !== null && stage?.confidence !== undefined) {
        details.push(`${(Number(stage.confidence) * 100).toFixed(1)}%`);
    }

    return (
        <div className="trading-decision-stage-value">
            <strong className={`decision-tone decision-tone--${toneFor(status)}`}>{status}</strong>
            {details.length > 0 && <span>{details.join(" / ")}</span>}
            {stage?.reason && <span className="trading-decision-stage-reason">{stage.reason}</span>}
        </div>
    );
};

export default function TradingDecisionCard({ decision }) {
    const snapshot = decision && typeof decision === "object" ? decision : {};
    const finalDecision = display(snapshot.finalDecision, "NOT AVAILABLE");
    const stages = {
        ...snapshot.stages,
        position: { status: snapshot.stages?.execution?.positionState },
    };

    // Collect all known stages and any additional unknown stages from backend
    const allStageKeys = new Set([...STAGES.map(([key]) => key), ...Object.keys(snapshot.stages || {}).filter(key => !STAGES.some(([knownKey]) => knownKey === key))]);
    const displayStages = [...STAGES, ...Array.from(allStageKeys).filter(key => !STAGES.some(([knownKey]) => knownKey === key)).map(key => [key, key.toUpperCase()])];

    return (
        <section className="trading-decision-card" aria-labelledby="trading-decision-title">
            <header className="trading-decision-header">
                <div>
                    <h2 id="trading-decision-title">{label("TRADING DECISION", "売買判断")}</h2>
                </div>
            </header>

            {snapshot.stale === true && <div className="trading-decision-alert" role="status">{label("STALE DECISION DATA", "判断データが古くなっています")}</div>}

            {/* PRIMARY DECISION - Most visible */}
            <div className="trading-decision-primary">
                <div className="trading-decision-final">
                    <span>{label("FINAL DECISION", "最終判断")}</span>
                    <strong className={`decision-tone decision-tone--${toneFor(finalDecision)}`}>{finalDecision}</strong>
                </div>
                
                {/* Entry Readiness and Current State */}
                <div className="trading-decision-status-row">
                    <div>
                        <span>{label("ENTRY READINESS", "エントリー準備")}</span>
                        <strong>{display(snapshot.entryReadiness)}</strong>
                    </div>
                    <div>
                        <span>{label("CURRENT STATE", "現在状態")}</span>
                        <strong>{display(snapshot.currentState)}</strong>
                    </div>
                </div>

                {/* Blocking Information */}
                {snapshot.blockingStage || snapshot.blockingReason ? (
                    <div className="trading-decision-block-info">
                        <div>
                            <span>{label("BLOCKING STAGE", "停止工程")}</span>
                            <strong>{display(snapshot.blockingStage, "NONE")}</strong>
                        </div>
                        <div>
                            <span>{label("BLOCKING REASON", "停止理由")}</span>
                            <strong>{display(snapshot.blockingReason, "NONE")}</strong>
                        </div>
                    </div>
                ) : null}
            </div>

            {/* Decision Pipeline */}
            <section className="trading-decision-pipeline" aria-labelledby="decision-pipeline-title">
                <h3 id="decision-pipeline-title">{label("DECISION PIPELINE", "判断フロー")}</h3>
                <ol className="trading-decision-stages">
                    {displayStages.map(([key, stageLabel], index) => {
                        const currentBlock = stageMatchesBlock(key, snapshot.blockingStage);
                        return (
                            <li className={`trading-decision-stage${currentBlock ? " is-current-block" : ""}`} key={key} aria-current={currentBlock ? "step" : undefined}>
                                <div className="trading-decision-stage-heading"><span>{index + 1}</span><strong>{stageLabel}</strong>{currentBlock && <em>{label("STOPPED HERE", "現在停止")}</em>}</div>
                                <StageValue stage={stages[key]} />
                                {index < displayStages.length - 1 && <span className={`trading-decision-connector${currentBlock ? " is-stopped" : ""}`} aria-hidden="true">━━▶</span>}
                            </li>
                        );
                    })}
                </ol>
            </section>

            {/* Runtime Meta - Compact grid */}
            <section className="trading-decision-runtime-meta" aria-labelledby="runtime-meta-title">
                <h3 id="runtime-meta-title">{label("RUNTIME META", "ランタイム情報")}</h3>
                <div className="runtime-meta-grid">
                    <div><span>{label("MODE", "モード")}</span><strong>{display(snapshot.mode)}</strong></div>
                    <div><span>{label("EXCHANGE", "取引所")}</span><strong>{display(snapshot.exchange)}</strong></div>
                    <div><span>{label("REAL ORDER ALLOWED", "実注文許可")}</span><strong>{yesNo(snapshot.realOrderAllowed)}</strong></div>
                    <div><span>{label("BOT", "ボット")}</span><strong>{operationalStatus(snapshot.bot ?? snapshot.botRunning)}</strong></div>
                    <div><span>{label("LOOP", "ループ")}</span><strong>{operationalStatus(snapshot.loop ?? snapshot.loopState ?? snapshot.loopRunning)}</strong></div>
                    <div><span>{label("AUTO TRADE", "自動売買")}</span><strong>{operationalStatus(snapshot.autoTrade ?? snapshot.autoTradeEnabled, "ENABLED", "DISABLED")}</strong></div>
                    <div><span>{label("TRADING AI", "売買AI")}</span><strong>{display(snapshot.tradingAiMode, "OFF")}</strong></div>
                    <div><span>{label("AI IMPLEMENTATION", "AI実装")}</span><strong>{display(snapshot.tradingAiStatus, "NOT_INSTALLED")}</strong></div>
                    <div><span>{label("MARKET STALE", "市場データ遅延")}</span><strong>{yesNo(snapshot.stale)}</strong></div>
                    <div><span>{label("LAST CYCLE", "最終サイクル")}</span><strong>{timestampLabel(snapshot.timestamp)}</strong></div>
                    <div><span>{label("CYCLE ID", "サイクルID")}</span><strong>{display(snapshot.cycleId, "NOT AVAILABLE")}</strong></div>
                    <div><span>{label("STATE SINCE", "状態継続時間")}</span><strong>{durationLabel(snapshot.stateSince)}</strong></div>
                    <div><span>{label("PENDING ORDER", "保留注文")}</span><strong>{snapshot.stages?.execution?.orderState == null ? "NOT AVAILABLE" : snapshot.stages.execution.orderState === "NONE" ? "NO" : "YES"}</strong></div>
                </div>
            </section>

            {/* Decision Details - Collapsible */}
            <details className="trading-decision-disclosure">
                <summary>{label("Decision Details", "判断詳細")}</summary>
                <div className="trading-decision-details">
                <section>
                    <h3>{label("ENTRY READINESS", "エントリー準備")}</h3>
                    <p>{snapshot.entryReadiness?.available ? `AVAILABLE / Candidate ${display(snapshot.entryReadiness.candidateDirection)} / Python Decision ${display(snapshot.entryReadiness.strategyDecision)}` : label("Detailed entry conditions are not exposed by the current runtime.", "現在のランタイムでは詳細なエントリー条件を取得できません。")}</p>
                    {snapshot.entryReadiness?.conditions?.map((condition) => <p key={condition.code}>{condition.code}: {condition.status} · {conditionValue(condition)} · source {condition.sourceStatus}{condition.delta == null ? "" : ` · gap ${numberLabel(condition.delta, condition.code)}`}</p>)}
                </section>
                <section>
                    <h3>{label("PYTHON STRATEGY", "戦略")}</h3>
                    <p>{label("Decision", "判断")}: {display(snapshot.stages?.pythonStrategy?.decision, "NOT EVALUATED")}</p>
                    <p>{label("Confidence", "信頼度")}: {snapshot.stages?.pythonStrategy?.confidence == null ? "--" : `${(Number(snapshot.stages.pythonStrategy.confidence) * 100).toFixed(1)}%`}</p>
                    <p>{label("Reason", "理由")}: {display(snapshot.stages?.pythonStrategy?.reason, "--")}</p>
                    <p>{label("Suppression Reason", "抑制理由")}: {display(snapshot.stages?.pythonStrategy?.suppressionReason, "--")}</p>
                    <p>{label("Evaluated At", "判定時刻")}: {timestampLabel(snapshot.stages?.pythonStrategy?.evaluatedAt)}</p>
                </section>
                <section>
                    <h3>{label("TRADING AI (OPTIONAL)", "売買AI（任意）")}</h3>
                    <p>{label("Mode", "モード")}: {display(snapshot.tradingAiMode, "OFF")}</p>
                    <p>{label("Implementation", "実装")}: {display(snapshot.tradingAiStatus, "NOT_INSTALLED")}</p>
                    <p>{label("Required", "必須")}: NO</p>
                    <p>{label("Fallback", "代替処理")}: NONE</p>
                </section>
                <section>
                    <h3>{label("MONEY MANAGEMENT", "資金管理")}</h3>
                    <p>{label("Result", "結果")}: {display(snapshot.stages?.moneyManagement?.status, "NOT AVAILABLE")}</p>
                    <p>{label("Reason", "理由")}: {display(snapshot.stages?.moneyManagement?.reason, "--")}</p>
                    {snapshot.stages?.moneyManagement?.approvedQuantity != null && <p>{label("Approved Quantity", "承認数量")}: {snapshot.stages.moneyManagement.approvedQuantity}</p>}
                    {snapshot.stages?.moneyManagement?.riskAmount != null && <p>{label("Risk Amount", "リスク額")}: {snapshot.stages.moneyManagement.riskAmount}</p>}
                </section>
                <section>
                    <h3>{label("GOVERNANCE", "安全判定")}</h3>
                    <p>{label("Result", "結果")}: {display(snapshot.stages?.governance?.status, "NOT AVAILABLE")}</p>
                    <p>{label("Execution Authority", "実行権限")}: {display(snapshot.stages?.governance?.executionAuthority, "NOT AVAILABLE")}</p>
                    <p>{label("Emergency State", "緊急状態")}: {display(snapshot.stages?.governance?.emergencyState, "NOT AVAILABLE")}</p>
                </section>
                <section>
                    <h3>{label("EXECUTION", "注文実行")}</h3>
                    <p>{label("State", "状態")}: {display(snapshot.stages?.execution?.state, "NOT AVAILABLE")}</p>
                    <p>{label("Order", "注文")}: {display(snapshot.stages?.execution?.orderState, "NONE")}</p>
                    <p>{label("Side", "売買")}: {display(snapshot.stages?.execution?.orderSide, "--")}</p>
                    <p>{label("Type", "注文種別")}: {display(snapshot.stages?.execution?.orderType, "--")}</p>
                    <p>{label("Position", "ポジション")}: {display(snapshot.stages?.execution?.positionState, "UNKNOWN")}</p>
                    <p>{label("Reason", "理由")}: {display(snapshot.stages?.execution?.reason, "--")}</p>
                </section>
                <section>
                    <h3>{label("MODE SAFETY", "モード安全性")}</h3>
                    <p>{label("Destination", "注文先")}: {display(snapshot.orderDestination, "NOT AVAILABLE")}</p>
                    <p>{label("Real Order Allowed", "実注文許可")}: {snapshot.realOrderAllowed === true ? "true" : "false"}</p>
                    <p>{snapshot.mode === "LIVE" ? (snapshot.realOrderAllowed ? "LIVE ORDER AUTHORIZED" : "REAL ORDER BLOCKED") : "PAPER SIMULATION"}</p>
                </section>
                </div>
            </details>

        </section>
    );
}