import { useHyroTrialOperator } from "../../state/hyro-trial/HyroTrialOperatorContext.jsx";
import { HYRO_DASHBOARD_URL } from "../../features/prop-accounts/hyroTrialReadModel.js";
import "./prop-accounts.css";

const shown = (value) => value || "未確認";

export default function HyroTrialAccountStatus() {
    const operator = useHyroTrialOperator();
    const status = operator.accountStatus;
    const challenge = operator.selectedChallenge;
    const issued = challenge?.readKind === "ISSUED_READ_ONLY";
    const coreReference = operator.coreReference;
    const runningThisAccount = operator.simulation.accountId === challenge?.id;
    return (
        <section className="account-status-page hyro-trial-account-status" data-testid="hyro-trial-account-status">
            <header className="as-page-header">
                <div><span className="as-page-kicker">{issued ? "ISSUED TRIAL / READ ONLY" : "SAMPLE / SIMULATION / READ ONLY"}</span><h1>Account Status（HyroTrader）</h1></div>
                <span className="as-page-badge">NO ORDERS</span>
            </header>
            <p className="hyro-trial-warning">{issued ? "発行済み無料Trialの前回MCP確認結果です。欠落・古い情報をゼロ補完せず、実Hyro STARTは無効です。" : "明示された仮データです。無料TrialやHyro Coreの公式判定ではありません。"}</p>
            <article className="semantic-card as-primary-card clear">
                <header className="as-account-summary">
                    <div className="as-account-summary-identity"><span className="semantic-card-kicker">SELECTED CHALLENGE</span><h2>{shown(challenge?.accountName)}</h2></div>
                    <p className="as-account-summary-context">{shown(challenge?.plan)} / {shown(challenge?.stage)}</p>
                    <div className="as-account-summary-position"><span>SIMULATION</span><strong>{runningThisAccount ? operator.simulation.state : "STOPPED"}</strong></div>
                    <span className="as-account-summary-authority">EXECUTION DISABLED</span>
                </header>
                <div className="hyro-trial-status-grid">
                    <div><span>取得状態</span><strong>{operator.challengeList.quality}</strong></div>
                    <div><span>損益</span><strong>{status.pnl}</strong></div>
                    <div><span>日次損失までの余裕</span><strong>{status.dailyLossHeadroom}</strong></div>
                    <div><span>最大損失までの余裕</span><strong>{status.maximumLossHeadroom}</strong></div>
                    <div><span>残高</span><strong>{status.balance}</strong></div>
                    <div><span>Equity</span><strong>{status.equity}</strong></div>
                    <div><span>MCP currentDrawdown</span><strong>{status.currentDrawdown}</strong></div>
                    <div><span>MCP currentLoss</span><strong>{status.currentLoss}</strong></div>
                    <div><span>適格取引日</span><strong>{status.qualifyingTradingDays}</strong></div>
                    <div><span>建玉</span><strong>{status.positions}</strong></div>
                    <div><span>通常注文</span><strong>{status.openOrders}</strong></div>
                    <div><span>条件注文</span><strong>{status.conditionalOrders}</strong></div>
                    <div><span>最終更新</span><strong>{shown(challenge?.updatedAt)}</strong></div>
                </div>
                <section className="hyro-trial-rules">
                    <h3>{issued ? "Trialルール取得状況" : "サンプル用ルール"}</h3>
                    <p>{status.rules}</p>
                    <strong>{issued ? "MCP RULE VALUES NOT ADOPTED — 型・単位契約未確定" : "NOT OFFICIAL"} — 未確認値を0として表示しません</strong>
                </section>
                {issued && (
                    <section className="hyro-trial-runtime-summary" data-testid="hyro-issued-read-summary">
                        <h3>発行済みTrial 読み取り</h3>
                        <dl className="hyro-trial-definition-grid">
                            <div><dt>状態</dt><dd>{shown(challenge.status)}</dd></div>
                            <div><dt>ステージ</dt><dd>{shown(challenge.stage)}</dd></div>
                            <div><dt>取得元</dt><dd>{shown(challenge.source)}</dd></div>
                            <div><dt>品質</dt><dd>{shown(challenge.dataQuality)}</dd></div>
                            <div><dt>最終取得</dt><dd>{shown(challenge.updatedAt)}</dd></div>
                            <div><dt>Core参考評価</dt><dd>{shown(coreReference?.overall)}</dd></div>
                        </dl>
                        <a href={HYRO_DASHBOARD_URL} target="_blank" rel="noreferrer noopener">Hyro Terminalを開く</a>
                        <small>マイチャレンジから「25,000 USDT / Trial / swing」を選択してください。</small>
                    </section>
                )}
                <section className="hyro-trial-runtime-summary">
                    <h3>シミュレーション結果</h3>
                    <dl className="hyro-trial-definition-grid">
                        <div><dt>状態</dt><dd>{operator.simulation.state}</dd></div>
                        <div><dt>稼働対象</dt><dd>{shown(operator.simulation.accountName)}</dd></div>
                        <div><dt>開始時刻</dt><dd>{shown(operator.simulation.startedAt)}</dd></div>
                        <div><dt>停止時刻</dt><dd>{shown(operator.simulation.stoppedAt)}</dd></div>
                        <div><dt>外部通信</dt><dd>{operator.counts.externalNetworkCalls}</dd></div>
                        <div><dt>注文操作</dt><dd>{operator.counts.orderCalls}</dd></div>
                    </dl>
                </section>
            </article>
        </section>
    );
}
