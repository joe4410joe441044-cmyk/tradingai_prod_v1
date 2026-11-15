import { useState } from "react";

import { useHyroTrialOperator } from "../../state/hyro-trial/HyroTrialOperatorContext.jsx";
import { HYRO_TRIAL_OPERATOR_ISOLATED_PREVIEW } from "../../features/prop-accounts/hyroTrialOperatorFeature.js";
import { HYRO_DASHBOARD_URL } from "../../features/prop-accounts/hyroTrialReadModel.js";
import "./prop-accounts.css";

const shown = (value) => value || "未確認";

const connectionLabel = (state) => ({
    NOT_CHECKED: "未確認",
    CHECKING: "確認中…",
    CONNECTED_SAMPLE: "隔離カタログ確認済み（実更新なし）",
    FAILED: "確認失敗",
}[state] || "未確認");

const listLabel = (state) => ({
    IDLE: "未取得",
    LOADING: "取得中…",
    READY: "選択してください",
    EMPTY: "対象なし（完全なサンプル一覧）",
    INCOMPLETE: "取得不完全 — 対象なしとは判定しません",
    FAILED: "取得失敗 — 対象なしとは判定しません",
}[state] || "未確認");

function AccountSwitch() {
    const operator = useHyroTrialOperator();
    return (
        <section className="hyro-trial-switch" data-testid="trading-account-switch">
            <div>
                <span>取引口座 / TRADING ACCOUNT</span>
                <small>画面の表示対象だけを切り替えます。稼働先・注文権限は変更しません。</small>
            </div>
            <div aria-label="取引口座" className="hyro-trial-switch__buttons" role="group">
                <button
                    aria-pressed={operator.accountMode === "KUCOIN"}
                    className={operator.accountMode === "KUCOIN" ? "is-selected" : ""}
                    onClick={() => operator.selectAccountMode("KUCOIN")}
                    type="button"
                >通常口座 — KuCoin</button>
                <button
                    aria-pressed={operator.accountMode === "HYRO"}
                    className={operator.accountMode === "HYRO" ? "is-selected" : ""}
                    onClick={() => operator.selectAccountMode("HYRO")}
                    type="button"
                >PROP口座 — HyroTrader</button>
            </div>
            {operator.simulation.state !== "STOPPED" && (
                <p className="hyro-trial-running-banner" data-testid="cross-account-running-banner">
                    稼働中サンプル: {shown(operator.simulation.accountName)} / {operator.simulation.state} — 画面切替では停止しません
                </p>
            )}
        </section>
    );
}

function ChallengeSelection({ operator }) {
    const listBusy = operator.challengeList.state === "LOADING";
    return (
        <section className="hyro-trial-section" data-testid="hyro-connection-challenge-section">
            <header><span>1</span><h3>接続確認 / チャレンジ選択</h3></header>
            <p className="hyro-trial-warning">発行済みTrialはCC-6Qの前回MCP証跡、サンプルはメモリ内fixtureです。この操作自体は外部通信しません。</p>
            <div className="hyro-trial-actions">
                <button
                    disabled={operator.connection.state === "CHECKING"}
                    onClick={operator.checkConnection}
                    type="button"
                >{operator.connection.state === "CHECKING" ? "接続確認中…" : "接続を確認"}</button>
                <button disabled={listBusy} onClick={operator.loadChallenges} type="button">
                    {listBusy ? "一覧取得中…" : "チャレンジ選択（一覧取得）"}
                </button>
            </div>
            <dl className="hyro-trial-definition-grid">
                <div><dt>Connection</dt><dd data-testid="hyro-connection-state">{connectionLabel(operator.connection.state)}</dd></div>
                <div><dt>Challenge list</dt><dd data-testid="hyro-challenge-list-state">{listLabel(operator.challengeList.state)}</dd></div>
                <div><dt>Source</dt><dd>CC-6Q REDACTED EVIDENCE / IN-MEMORY SAMPLE</dd></div>
                <div><dt>Trading</dt><dd>OFF / 注文不可</dd></div>
            </dl>
            {operator.connection.error && <p className="hyro-trial-error" role="alert">{operator.connection.error}</p>}
            {operator.challengeList.error && <p className="hyro-trial-error" role="alert">{operator.challengeList.error}</p>}
            {operator.challengeList.state === "READY" && (
                <label className="hyro-trial-field">
                    <span>発行済みTrial（読み取り専用）/ サンプル</span>
                    <select
                        data-testid="hyro-challenge-select"
                        onChange={(event) => operator.selectChallenge(event.target.value)}
                        value={operator.selectedChallengeId}
                    >
                        <option value="">選択してください</option>
                        {operator.challengeList.items.map((challenge) => (
                            <option key={challenge.id} value={challenge.id}>{challenge.accountName}</option>
                        ))}
                    </select>
                </label>
            )}
            {operator.selectedChallenge && (
                <dl className="hyro-trial-definition-grid" data-testid="hyro-selected-challenge">
                    <div><dt>口座名</dt><dd>{operator.selectedChallenge.accountName}</dd></div>
                    <div><dt>プラン</dt><dd>{operator.selectedChallenge.plan}</dd></div>
                    <div><dt>段階</dt><dd>{operator.selectedChallenge.stage}</dd></div>
                    <div><dt>期間</dt><dd>{operator.selectedChallenge.period}</dd></div>
                    <div><dt>最終更新</dt><dd>{operator.selectedChallenge.updatedAt}</dd></div>
                    <div><dt>取得元</dt><dd>{shown(operator.selectedChallenge.source)}</dd></div>
                    <div><dt>取得品質</dt><dd>{shown(operator.selectedChallenge.dataQuality)}</dd></div>
                    <div><dt>チャレンジ状態</dt><dd>{shown(operator.selectedChallenge.status)}</dd></div>
                    <div><dt>表示区分</dt><dd>{operator.selectedChallenge.readKind === "ISSUED_READ_ONLY" ? "ISSUED TRIAL / READ ONLY / 注文不可" : "SAMPLE / SIMULATION"}</dd></div>
                </dl>
            )}
            {operator.selectedChallenge?.readKind === "ISSUED_READ_ONLY" && (
                <div className="hyro-trial-terminal-link" data-testid="hyro-terminal-link">
                    <a href={HYRO_DASHBOARD_URL} target="_blank" rel="noreferrer noopener">Hyro Terminalを開く</a>
                    <small>HyroTraderのマイチャレンジを開き、25,000 USDT / swing の無料Trialを選択してください。個別URLは未確認です。</small>
                </div>
            )}
        </section>
    );
}

const referenceText = (result) => {
    if (!result || result.state === "UNKNOWN") return `判定不能 — ${result?.reason || "必要データ未取得"}`;
    if (Object.hasOwn(result, "used")) return `${result.state} — ${result.used.toLocaleString()} / ${result.limit.toLocaleString()} USDT`;
    if (Object.hasOwn(result, "actual")) return `${result.state} — ${result.actual} / ${result.required}日`;
    if (Object.hasOwn(result, "countedProfit")) return `${result.state} — ${result.countedProfit.toLocaleString()} / ${result.target.toLocaleString()} USDT`;
    return result.state;
};

function CoreReferencePanel({ operator }) {
    const reference = operator.coreReference;
    if (!reference) return null;
    return (
        <section className="hyro-trial-section hyro-core-reference" data-testid="hyro-core-reference">
            <header><span>R</span><h3>Hyro Core 25K 参考評価</h3></header>
            <p className="hyro-trial-warning">無料Trialの公式判定とは別の参考計算です。Trialのdrawdown値をCoreの日次損失へ流用しません。</p>
            <dl className="hyro-trial-definition-grid">
                <div><dt>総合</dt><dd data-testid="hyro-core-overall">{reference.overall}</dd></div>
                <div><dt>評価期間</dt><dd>{reference.period}</dd></div>
                <div><dt>利益目標</dt><dd>2,500 USDT</dd></div>
                <div><dt>日次損失</dt><dd>{referenceText(reference.dailyLoss)}</dd></div>
                <div><dt>最大損失</dt><dd>{referenceText(reference.maximumLoss)}</dd></div>
                <div><dt>適格取引日</dt><dd>{referenceText(reference.tradingDays)}</dd></div>
                <div><dt>日次利益算入</dt><dd>{referenceText(reference.profitProgress)}</dd></div>
                <div><dt>基準日</dt><dd>UTC</dd></div>
            </dl>
            <p>利益日は1日1,000 USDTまで算入し、損失日は全額算入します。必要なequity・決済履歴が欠ける項目は判定不能です。</p>
            <a href={reference.rules.sourceUrl} target="_blank" rel="noreferrer noopener">Core基準の公式出典</a>
        </section>
    );
}

function Settings({ operator }) {
    const dirty = Boolean(operator.selectedChallenge) && JSON.stringify(operator.selectedDraft) !== JSON.stringify(operator.selectedSavedSettings);
    return (
        <section className="hyro-trial-section" data-testid="hyro-strategy-risk-section">
            <header><span>2</span><h3>戦略・リスク設定</h3></header>
            <div className="hyro-trial-form-grid">
                <label className="hyro-trial-field"><span>戦略</span><select disabled={!operator.selectedChallenge} onChange={(event) => operator.updateDraft("strategy", event.target.value)} value={operator.selectedDraft.strategy}><option value="">選択してください</option><option value="TREND_FOLLOW_SAMPLE">Trend Follow（サンプル）</option><option value="MEAN_REVERSION_SAMPLE">Mean Reversion（サンプル）</option></select></label>
                <label className="hyro-trial-field"><span>1取引リスク (%)</span><input disabled={!operator.selectedChallenge} inputMode="decimal" onChange={(event) => operator.updateDraft("riskPerTradePercent", event.target.value)} value={operator.selectedDraft.riskPerTradePercent} /></label>
                <label className="hyro-trial-field"><span>日次損失上限 (%)</span><input disabled={!operator.selectedChallenge} inputMode="decimal" onChange={(event) => operator.updateDraft("dailyLossLimitPercent", event.target.value)} value={operator.selectedDraft.dailyLossLimitPercent} /></label>
                <label className="hyro-trial-field"><span>最大損失上限 (%)</span><input disabled={!operator.selectedChallenge} inputMode="decimal" onChange={(event) => operator.updateDraft("maximumLossPercent", event.target.value)} value={operator.selectedDraft.maximumLossPercent} /></label>
            </div>
            <div className="hyro-trial-actions">
                <button disabled={!operator.selectedChallenge} onClick={operator.saveSelectedSettings} type="button">設定を保存</button>
                <strong data-testid="hyro-settings-state">{operator.selectedSavedSettings ? dirty ? "UNSAVED CHANGES" : "SAVED FOR THIS ACCOUNT" : "NOT SAVED"}</strong>
            </div>
            <small>設定は選択中の表示口座だけに保存され、KuCoinや別チャレンジへ自動適用しません。発行済みTrialは読み取り専用でSTARTできません。</small>
        </section>
    );
}

function FinalPreparation({ operator }) {
    const [confirmation, setConfirmation] = useState(null);
    const running = operator.simulation.state === "RUNNING";
    const pending = ["STARTING", "STOPPING"].includes(operator.simulation.state);
    const confirm = async () => {
        const action = confirmation;
        setConfirmation(null);
        if (action === "START") await operator.startSimulation();
        if (action === "STOP") await operator.stopSimulation();
    };
    return (
        <section className="hyro-trial-section hyro-trial-final" data-testid="hyro-final-preparation">
            <header><span>3</span><h3>FINAL PREPARATION / START / READINESS</h3></header>
            <dl className="hyro-trial-definition-grid">
                <div><dt>対象口座</dt><dd>{shown(operator.selectedChallenge?.accountName)}</dd></div>
                <div><dt>適用戦略</dt><dd>{shown(operator.selectedSavedSettings?.strategy)}</dd></div>
                <div><dt>1取引リスク</dt><dd>{operator.selectedSavedSettings ? `${operator.selectedSavedSettings.riskPerTradePercent}%` : "未確認"}</dd></div>
                <div><dt>実行方式</dt><dd>注文を送らないシミュレーション</dd></div>
                <div><dt>READINESS</dt><dd data-testid="hyro-readiness">{operator.readiness.state}</dd></div>
                <div><dt>実Hyro START</dt><dd>DISABLED — 権限・停止契約未確認</dd></div>
            </dl>
            {operator.readiness.reasons.length > 0 && <ul className="hyro-trial-block-reasons" data-testid="hyro-readiness-reasons">{operator.readiness.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
            <div className="hyro-trial-runtime" data-testid="hyro-simulation-runtime">
                <strong>SIMULATION {operator.simulation.state}</strong>
                <span>稼働対象: {shown(operator.simulation.accountName)}</span>
                <span>注文・取消・決済: 0</span>
            </div>
            <div className="hyro-trial-actions">
                {!running && <button disabled={pending || operator.readiness.state !== "READY"} onClick={() => setConfirmation("START")} type="button">{operator.simulation.state === "STARTING" ? "STARTING…" : "シミュレーション START"}</button>}
                {running && <button disabled={pending} onClick={() => setConfirmation("STOP")} type="button">シミュレーション STOP</button>}
                <button disabled type="button">実Hyro START（未確認のため無効）</button>
            </div>
            {operator.actionError && <p className="hyro-trial-error" role="alert">{operator.actionError}</p>}
            {confirmation && (
                <div className="hyro-trial-confirm" role="dialog" aria-modal="true" aria-label={`${confirmation} simulation confirmation`}>
                    <div>
                        <h4>{confirmation === "START" ? "シミュレーションを開始しますか" : "シミュレーションを停止しますか"}</h4>
                        <p>対象: {confirmation === "STOP" ? operator.simulation.accountName : operator.selectedChallenge?.accountName}</p>
                        <p>{confirmation === "START" ? "注文を送らず、共有状態だけをRUNNINGへ変更します。" : "シミュレーション状態だけを停止します。注文取消・建玉決済は実行しません。"}</p>
                        <button onClick={confirm} type="button">確認して{confirmation}</button>
                        <button onClick={() => setConfirmation(null)} type="button">キャンセル</button>
                    </div>
                </div>
            )}
        </section>
    );
}

function HyroTrialPanel() {
    const operator = useHyroTrialOperator();
    return (
        <div className="terminal-panel operation-console hyro-trial-console" data-testid="hyro-trial-operator-panel">
            <header className="hyro-trial-hero"><span>FEATURE-GATED · READ ONLY / SAMPLE SIMULATION</span><h2>HyroTrader Trial オペレーター</h2><p>発行済みTrialの前回MCP確認結果と、明示されたサンプルを分離表示します。PROP選択中は読み取り専用・注文不可です。</p></header>
            <div className="hyro-trial-grid">
                <ChallengeSelection operator={operator} />
                <CoreReferencePanel operator={operator} />
                <Settings operator={operator} />
                <FinalPreparation operator={operator} />
            </div>
        </div>
    );
}

export default function HyroTrialOperationSurface({ children }) {
    const operator = useHyroTrialOperator();
    if (!operator.enabled) return children;
    const kucoinControls = HYRO_TRIAL_OPERATOR_ISOLATED_PREVIEW ? (
        <fieldset
            className="operation-auth-gate operation-auth-gate--preview-disabled"
            data-testid="preview-disabled-kucoin-controls"
            disabled
        >
            <legend>KuCoin既存PAPER / LIVE操作（隔離プレビューでは操作無効）</legend>
            {children}
        </fieldset>
    ) : children;
    return <>
        <AccountSwitch />
        {operator.accountMode === "HYRO" ? <HyroTrialPanel /> : kucoinControls}
    </>;
}
