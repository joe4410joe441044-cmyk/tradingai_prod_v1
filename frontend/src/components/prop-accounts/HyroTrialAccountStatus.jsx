import { useHyroTrialOperator } from "../../state/hyro-trial/HyroTrialOperatorContext.jsx";
import "./prop-accounts.css";

const shown = (value) => value || "未確認";

export default function HyroTrialAccountStatus() {
    const operator = useHyroTrialOperator();
    const status = operator.accountStatus;
    const challenge = operator.selectedChallenge;
    const runningThisAccount = operator.simulation.accountId === challenge?.id;
    return (
        <section className="account-status-page hyro-trial-account-status" data-testid="hyro-trial-account-status">
            <header className="as-page-header">
                <div><span className="as-page-kicker">SAMPLE / SIMULATION / READ ONLY</span><h1>Account Status（HyroTraderサンプル）</h1></div>
                <span className="as-page-badge">NO ORDERS</span>
            </header>
            <p className="hyro-trial-warning">仮データによる発行前プレビューです。公式の無料トライアル、有料One-Step、実口座の判定ではありません。</p>
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
                    <div><span>建玉</span><strong>{status.positions}</strong></div>
                    <div><span>通常注文</span><strong>{status.openOrders}</strong></div>
                    <div><span>条件注文</span><strong>{status.conditionalOrders}</strong></div>
                    <div><span>最終更新</span><strong>{shown(challenge?.updatedAt)}</strong></div>
                </div>
                <section className="hyro-trial-rules">
                    <h3>サンプル用ルール</h3>
                    <p>{status.rules}</p>
                    <strong>NOT OFFICIAL — 未確認値を0として表示しません</strong>
                </section>
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
