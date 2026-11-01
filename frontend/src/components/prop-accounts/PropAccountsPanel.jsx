import { useEffect, useMemo, useRef, useState } from "react";

import {
    displayAmount,
    displayQuantity,
    displayTimestamp,
    normalizePropAccountsView,
    selectedAccount,
} from "../../features/prop-accounts/propAccountsViewModel.js";
import {
    PROP_ACCOUNT_ID,
    PROP_FIXTURE_SCENARIOS,
    createPropAccountsFixture,
} from "../../features/prop-accounts/propAccountsFixtures.js";

import "./prop-accounts.css";

const LABELS = {
    NORMAL: "通常取引",
    PROP: "PROP取引",
    PAPER: "内部模擬",
    EXTERNAL_SIMULATION: "外部Demo（PROPルール適用あり得る）",
    LIVE: "実資金環境（サンプル表示のみ）",
};

const shown = (value, fallback = "未確認") => (
    value === null || value === undefined || value === "" ? fallback : String(value)
);

function StateBadge({ label, value, tone = "neutral", testId }) {
    return (
        <div className={`cc-prop-accounts__state cc-prop-accounts__state--${tone}`} data-testid={testId}>
            <span>{label}</span>
            <strong>{shown(value)}</strong>
        </div>
    );
}

function Metric({ label, value, testId }) {
    return (
        <div className="cc-prop-accounts__metric" data-testid={testId}>
            <span>{label}</span>
            <strong>{value}</strong>
        </div>
    );
}

function CollectionNotice({ quality, emptyLabel, failedLabel }) {
    if (quality !== "COMPLETE") {
        const qualifier = quality === "PARTIAL"
            ? "（部分取得）"
            : quality === "STALE"
                ? "（データが古いため空一覧と判定しません）"
                : "";
        return <p className="cc-prop-accounts__empty cc-prop-accounts__empty--error">{failedLabel}{qualifier}</p>;
    }
    return <p className="cc-prop-accounts__empty">{emptyLabel}</p>;
}

function PositionTable({ collection }) {
    if (collection.items.length === 0) {
        return (
            <CollectionNotice
                quality={collection.quality}
                emptyLabel="オープンポジションなし（正常な空一覧）"
                failedLabel="ポジションを取得できませんでした"
            />
        );
    }
    return (
        <div className="cc-prop-accounts__table-wrap">
            <table>
                <thead><tr><th>Symbol</th><th>Side</th><th>Quantity</th><th>Entry</th><th>Mark</th><th>Unrealized PnL</th><th>Status</th></tr></thead>
                <tbody>
                    {collection.items.map((position) => (
                        <tr key={`${position.symbol}:${position.side}`}>
                            <td>{position.symbol}</td>
                            <td>{position.side}</td>
                            <td>{displayQuantity(position.quantity, position.quantityUnit)}</td>
                            <td>{displayAmount(position.entryPrice)}</td>
                            <td>{displayAmount(position.markPrice)}</td>
                            <td>{displayAmount(position.unrealizedPnl)}</td>
                            <td>{position.status}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function OrderTable({ collection }) {
    if (collection.items.length === 0) {
        return (
            <CollectionNotice
                quality={collection.quality}
                emptyLabel="オープン注文なし（正常な空一覧）"
                failedLabel="オープン注文を取得できませんでした"
            />
        );
    }
    return (
        <div className="cc-prop-accounts__table-wrap">
            <table>
                <thead><tr><th>Symbol</th><th>Side</th><th>Quantity</th><th>Price</th><th>Status</th></tr></thead>
                <tbody>
                    {collection.items.map((order) => (
                        <tr key={`${order.symbol}:${order.side}`}>
                            <td>{order.symbol}</td>
                            <td>{order.side}</td>
                            <td>{displayQuantity(order.quantity, order.quantityUnit)}</td>
                            <td>{displayAmount(order.price)}</td>
                            <td>{order.status}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function RulesCard({ account }) {
    const rules = account.propRules;
    return (
        <section className="cc-prop-accounts__card" data-testid="prop-rules-card">
            <header className="cc-prop-accounts__card-header">
                <div><span>PROP RULES</span><h2>PROPルール</h2></div>
                <b className={`cc-prop-accounts__badge cc-prop-accounts__badge--${rules.readiness === "READY" ? "ok" : "warning"}`}>
                    {rules.readiness}
                </b>
            </header>
            {account.accountSummary.accountType === "NORMAL" ? (
                <p className="cc-prop-accounts__notice">通常取引口座にはPROPルールを適用しません。</p>
            ) : (
                <>
                    {rules.sampleCalculated && (
                        <p className="cc-prop-accounts__sample-rule">架空ルールのサンプル — HyroTrader現行公式ルールではありません</p>
                    )}
                    <dl className="cc-prop-accounts__definition-grid">
                        <div><dt>Rule set</dt><dd>{shown(rules.ruleSetId)}</dd></div>
                        <div><dt>Revision</dt><dd>{shown(rules.revision)}</dd></div>
                        <div><dt>Phase</dt><dd>{rules.phase}</dd></div>
                    </dl>
                    <p className="cc-prop-accounts__notice">{rules.explanation}</p>
                    <div className="cc-prop-accounts__rule-grid">
                        {rules.limits.map((limit) => (
                            <article key={limit.code} data-testid={`rule-${limit.code.toLowerCase()}`}>
                                <span>{limit.code}</span>
                                <strong>{limit.state}</strong>
                                <dl>
                                    <div><dt>閾値</dt><dd>{displayAmount(limit.threshold)}</dd></div>
                                    <div><dt>使用額</dt><dd>{displayAmount(limit.actual)}</dd></div>
                                    <div><dt>残余</dt><dd>{displayAmount(limit.headroom)}</dd></div>
                                </dl>
                            </article>
                        ))}
                    </div>
                    {rules.unknownFields.length > 0 && (
                        <p className="cc-prop-accounts__missing">未確認: {rules.unknownFields.join(" / ")}</p>
                    )}
                </>
            )}
        </section>
    );
}

function DetailsPanel({ account, onClose }) {
    const panelRef = useRef(null);

    useEffect(() => {
        if (typeof document === "undefined") return undefined;
        const returnFocus = document.activeElement;
        const panel = panelRef.current;
        panel?.focus();

        const handleKeyDown = (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                onClose();
                return;
            }
            if (event.key !== "Tab" || !panel) return;
            const focusable = [...panel.querySelectorAll("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")];
            if (focusable.length === 0) {
                event.preventDefault();
                panel.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };

        document.addEventListener("keydown", handleKeyDown);
        return () => {
            document.removeEventListener("keydown", handleKeyDown);
            if (returnFocus instanceof HTMLElement) returnFocus.focus();
        };
    }, [onClose]);

    return (
        <aside
            aria-label="状態詳細"
            aria-modal="true"
            className="cc-prop-accounts__details"
            data-testid="prop-details"
            ref={panelRef}
            role="dialog"
            tabIndex="-1"
        >
            <header>
                <div><span>DIAGNOSTIC DETAILS</span><h2>状態詳細・不足情報</h2></div>
                <button aria-label="状態詳細を閉じる" onClick={onClose} type="button">×</button>
            </header>
            <dl>
                <div><dt>Account ID</dt><dd>{account.accountSummary.accountId}</dd></div>
                <div><dt>Safe reason</dt><dd>{account.connection.safeReasonCode}</dd></div>
                <div><dt>Observation source</dt><dd>{account.observation.source}</dd></div>
                <div><dt>Oldest source</dt><dd>{displayTimestamp(account.observation.oldestSourceAt)}</dd></div>
                <div><dt>Newest source</dt><dd>{displayTimestamp(account.observation.newestSourceAt)}</dd></div>
                <div><dt>Missing fields</dt><dd>{account.observation.missingFields.join(" / ") || "なし"}</dd></div>
                <div><dt>Position quality</dt><dd>{account.positions.quality}</dd></div>
                <div><dt>Open-order quality</dt><dd>{account.openOrders.quality}</dd></div>
            </dl>
        </aside>
    );
}

export function PropAccountsView({
    viewModel,
    scenarioId,
    scenarios = PROP_FIXTURE_SCENARIOS,
    detailsOpen = false,
    onAccountChange = () => {},
    onScenarioChange = () => {},
    onDetailsOpen = () => {},
    onDetailsClose = () => {},
}) {
    if (viewModel?.status !== "READY") {
        return (
            <main className="cc-prop-accounts" data-testid="prop-accounts-invalid">
                <div className="cc-prop-accounts__fixture-banner">サンプル表示 / 実口座未接続</div>
                <section className="cc-prop-accounts__invalid" role="alert">
                    <h1>表示データを安全に読み込めませんでした</h1>
                    <p>{shown(viewModel?.errorCode, "INVALID_VIEW_MODEL")}</p>
                    <p>別口座へのfallbackやREADY補完は行っていません。</p>
                </section>
            </main>
        );
    }
    const account = selectedAccount(viewModel);
    if (!account) return null;
    const { accountSummary, connection, observation } = account;
    const degraded = observation.quality !== "COMPLETE";

    return (
        <main className="cc-prop-accounts" data-testid="prop-accounts-panel">
            <div className="cc-prop-accounts__fixture-banner" data-testid="fixture-banner">
                <strong>サンプル表示 / 実口座未接続</strong>
                <span>この画面は架空データです。実API・Registry・runtime・注文経路には接続していません。</span>
            </div>

            <header className="cc-prop-accounts__hero">
                <div><span>FIXTURE-ONLY PREVIEW</span><h1>PROP Account Status</h1></div>
                <div className="cc-prop-accounts__execution" data-testid="execution-authority">
                    <span>EXECUTION AUTHORITY</span><strong>DISABLED</strong>
                </div>
            </header>

            <section className="cc-prop-accounts__scenario" aria-label="開発用fixture scenario">
                <label htmlFor="cc-prop-scenario">開発preview用scenario（実運用設定ではありません）</label>
                <select
                    id="cc-prop-scenario"
                    onChange={(event) => onScenarioChange(event.target.value)}
                    value={scenarioId}
                >
                    {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.label}</option>)}
                </select>
            </section>

            <section className="cc-prop-accounts__selector" aria-label="閲覧対象口座" data-testid="account-selector">
                <div className="cc-prop-accounts__section-title">
                    <div><span>ACCOUNT VIEW</span><h2>閲覧対象口座</h2></div>
                    <p>表示だけを切り替えます。runtime・実行対象・注文設定は変更しません。</p>
                </div>
                <div className="cc-prop-accounts__account-options">
                    {viewModel.accounts.map(({ accountSummary: option }) => (
                        <button
                            aria-pressed={viewModel.viewedAccountId === option.accountId}
                            className={viewModel.viewedAccountId === option.accountId ? "is-selected" : ""}
                            data-testid={`account-option-${option.accountType.toLowerCase()}`}
                            key={option.accountId}
                            onClick={() => onAccountChange(option.accountId)}
                            type="button"
                        >
                            <span>{LABELS[option.accountType]}</span>
                            <strong>{option.label}</strong>
                            <small>{option.platform} · {LABELS[option.environment]}</small>
                            <small>Phase: {option.phase}</small>
                        </button>
                    ))}
                </div>
            </section>

            <section className="cc-prop-accounts__identity" data-testid="selected-account-identity">
                <div><span>{LABELS[accountSummary.accountType]}</span><h2>{accountSummary.label}</h2></div>
                <dl>
                    <div><dt>Platform</dt><dd>{accountSummary.platform}</dd></div>
                    <div><dt>Phase</dt><dd>{accountSummary.phase}</dd></div>
                    <div><dt>Environment</dt><dd>{LABELS[accountSummary.environment]}</dd></div>
                </dl>
            </section>

            <section className="cc-prop-accounts__axis-grid" aria-label="独立状態軸">
                <StateBadge label="Observer接続" value={connection.state} tone={connection.state === "CONNECTED_READ_ONLY" ? "ok" : "warning"} testId="connection-state" />
                <StateBadge label="Data quality" value={observation.quality} tone={degraded ? "warning" : "ok"} testId="data-quality-state" />
                <StateBadge label="PROP rules" value={account.propRules.readiness} tone={account.propRules.readiness === "READY" ? "ok" : "warning"} testId="rules-readiness-state" />
                <StateBadge label="Execution" value="DISABLED" tone="danger" testId="execution-state" />
            </section>

            <section className="cc-prop-accounts__card" data-testid="account-summary-card">
                <header className="cc-prop-accounts__card-header">
                    <div><span>ACCOUNT SUMMARY</span><h2>口座サマリー</h2></div>
                    <b className={`cc-prop-accounts__badge cc-prop-accounts__badge--${degraded ? "warning" : "ok"}`}>{observation.freshness} / {observation.quality}</b>
                </header>
                <div className="cc-prop-accounts__metrics">
                    <Metric label="Balance" value={displayAmount(observation.balance)} testId="metric-balance" />
                    <Metric label="Equity" value={displayAmount(observation.equity)} testId="metric-equity" />
                    <Metric label="Realized PnL" value={displayAmount(observation.realizedPnl)} testId="metric-realized-pnl" />
                    <Metric label="Unrealized PnL" value={displayAmount(observation.unrealizedPnl)} testId="metric-unrealized-pnl" />
                    <Metric label="Observed at" value={displayTimestamp(observation.observedAt, viewModel.displayTimezone)} testId="metric-observed-at" />
                    <Metric label="Source" value={observation.source} testId="metric-source" />
                </div>
                {observation.missingFields.length > 0 && <p className="cc-prop-accounts__missing">欠損: {observation.missingFields.join(" / ")}</p>}
            </section>

            <div className="cc-prop-accounts__collections">
                <section className="cc-prop-accounts__card" data-testid="positions-card">
                    <header className="cc-prop-accounts__card-header"><div><span>POSITIONS</span><h2>オープンポジション</h2></div><b>{account.positions.quality}</b></header>
                    <PositionTable collection={account.positions} />
                    {account.positions.quality === "PARTIAL" && <p className="cc-prop-accounts__missing">部分取得: {account.positions.missingFields.join(" / ")}</p>}
                </section>
                <section className="cc-prop-accounts__card" data-testid="open-orders-card">
                    <header className="cc-prop-accounts__card-header"><div><span>OPEN ORDERS</span><h2>オープン注文</h2></div><b>{account.openOrders.quality}</b></header>
                    <OrderTable collection={account.openOrders} />
                    {account.openOrders.quality === "PARTIAL" && <p className="cc-prop-accounts__missing">部分取得: {account.openOrders.missingFields.join(" / ")}</p>}
                </section>
            </div>

            <RulesCard account={account} />

            <section className="cc-prop-accounts__authority" data-testid="readiness-authority-card">
                <div><span>Observer connection</span><strong>{connection.state}</strong><small>サンプル上の接続状態</small></div>
                <div><span>Key eligibility</span><strong>{connection.keyEligibility}</strong><small>外部確認が必要</small></div>
                <div><span>PROP rules</span><strong>{account.propRules.readiness}</strong><small>UNKNOWNは取引可能にしません</small></div>
                <div><span>Execution authority</span><strong className="is-disabled">DISABLED</strong><small>{account.executionCapability.reasons.join(" / ")}</small></div>
            </section>

            <section className="cc-prop-accounts__ai" data-testid="ai-context-card">
                <div><span>AI CONTEXT</span><h2>AI context未接続</h2></div>
                <dl>
                    <div><dt>対象口座</dt><dd>{accountSummary.label}</dd></div>
                    <div><dt>Context</dt><dd>{account.aiContext.status}</dd></div>
                    <div><dt>Authority</dt><dd>付与しない</dd></div>
                </dl>
                <p>fixture助言や実際のAI出力は表示していません。</p>
            </section>

            <button className="cc-prop-accounts__details-button" onClick={onDetailsOpen} type="button">状態詳細・不足情報を開く</button>
            {detailsOpen && <DetailsPanel account={account} onClose={onDetailsClose} />}
        </main>
    );
}

export default function PropAccountsPanel({ fixtureOverride = null }) {
    const [scenarioId, setScenarioId] = useState("not_configured");
    const [viewedAccountId, setViewedAccountId] = useState(PROP_ACCOUNT_ID);
    const [detailsOpen, setDetailsOpen] = useState(false);
    const viewModel = useMemo(() => normalizePropAccountsView(
        fixtureOverride ?? createPropAccountsFixture({ scenarioId, viewedAccountId }),
    ), [fixtureOverride, scenarioId, viewedAccountId]);

    return (
        <PropAccountsView
            detailsOpen={detailsOpen}
            onAccountChange={(accountId) => {
                setViewedAccountId(accountId);
                setDetailsOpen(false);
            }}
            onDetailsClose={() => setDetailsOpen(false)}
            onDetailsOpen={() => setDetailsOpen(true)}
            onScenarioChange={(nextScenario) => {
                setScenarioId(nextScenario);
                setDetailsOpen(false);
            }}
            scenarioId={scenarioId}
            viewModel={viewModel}
        />
    );
}
