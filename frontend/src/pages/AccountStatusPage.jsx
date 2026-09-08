import { useState } from "react";
import usePolling from "../hooks/usePolling";
import PaperCapitalControl from "../components/runtime/PaperCapitalControl";
import StatusMetric from "../components/runtime/StatusMetric";
import {
    buildAccountRuntimeProps,
    deriveAccountRuntime,
    deriveFinancialMetrics,
    deriveLiveContext,
    displayRuntimeValue,
    displayValue,
    fetchBotStatus,
    formatAmount,
    formatLastUpdate,
    formatPnl,
    formatPositionValue,
    isAvailable,
} from "../components/runtime/accountRuntimeModel";

/* =================================================
   ACCOUNT STATUS (independent page)

   Live-first asymmetric account hierarchy:
     REAL / LIVE ACCOUNT   -> primary, full width
     ACCOUNT RUNTIME       -> runtime card
     LIVE CONTEXT          -> context card
     PAPER / SIMULATION    -> compact secondary

   Read-only. No operation controls. Canonical source
   is GET /api/bot/status.
================================================= */

const displaySyncState = (value) => {
    if (value === true) return "PENDING";
    if (value === false) return "NONE";
    return displayValue(value);
};

const displayBoolean = (value) => {
    if (value === true) return "YES";
    if (value === false) return "NO";
    return "--";
};

const CURRENT_CONTEXT_LABELS = {
    "PAPER MODE — LIVE ACCOUNT INACTIVE": "PAPER MODE（ペーパーモード）— LIVE ACCOUNT INACTIVE（実口座取引停止中）",
    "LIVE MODE — REAL ACCOUNT ACTIVE": "LIVE MODE（LIVE状態）— REAL ACCOUNT ACTIVE（実口座が有効です）",
    "LIVE MODE — REAL EXECUTION NOT ALLOWED": "LIVE MODE（LIVE状態）— REAL EXECUTION NOT ALLOWED（実口座での取引実行は許可されていません）",
    "RUNTIME MODE UNKNOWN": "RUNTIME MODE UNKNOWN（実行モード不明）",
};

const displayCurrentContext = (value) => (
    CURRENT_CONTEXT_LABELS[value] ?? String(value ?? "")
);

/* =================================================
   Financial metric icons — small inline SVGs, no
   external asset, no emoji, no new dependency. The
   visual language mirrors the dashboard cyan icon
   containers. PnL icons inherit the status color.
================================================= */
const FINANCIAL_GLYPHS = {
    equity: (
        <>
            <ellipse cx="12" cy="7" rx="6" ry="3" />
            <path d="M6 7v5c0 1.66 2.69 3 6 3s6-1.34 6-3V7" />
            <path d="M6 12v5c0 1.66 2.69 3 6 3s6-1.34 6-3v-5" />
        </>
    ),
    availableBalance: (
        <>
            <rect x="3" y="6" width="18" height="13" rx="2" />
            <path d="M3 10h18" />
            <circle cx="16" cy="14" r="1" />
        </>
    ),
    walletBalance: (
        <>
            <path d="M4 7h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7z" />
            <path d="M4 7a3 3 0 0 1 3-3h9" />
            <circle cx="17" cy="13" r="1" />
        </>
    ),
    unrealizedPnl: (
        <>
            <polyline points="3 17 9 11 13 14 21 6" />
            <polyline points="15 6 21 6 21 12" />
        </>
    ),
    realizedPnlToday: (
        <>
            <line x1="5" y1="21" x2="5" y2="13" />
            <line x1="12" y1="21" x2="12" y2="8" />
            <line x1="19" y1="21" x2="19" y2="11" />
        </>
    ),
    totalPnlToday: (
        <>
            <polyline points="3 19 9 13 13 15 21 7" />
            <path d="M3 19h18" />
        </>
    ),
    marginUsed: (
        <>
            <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
            <line x1="12" y1="9" x2="12" y2="13" />
        </>
    ),
    marginAvailable: (
        <>
            <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
            <polyline points="9 12 11 14 15 10" />
        </>
    ),
    marginRatio: (
        <>
            <circle cx="12" cy="12" r="9" />
            <line x1="8.5" y1="15.5" x2="15.5" y2="8.5" />
            <circle cx="9" cy="9" r="1" />
            <circle cx="15" cy="15" r="1" />
        </>
    ),
};

function FinancialIcon({ icon = "equity", tone = "neutral" }) {
    return (
        <span
            className={`as-fin-icon as-fin-icon--${tone}`}
            data-testid={`financial-icon-${icon}`}
        >
            <svg
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
            >
                {FINANCIAL_GLYPHS[icon]}
            </svg>
        </span>
    );
}

function FinancialMetricCard({ metric }) {
    const stateClass = metric.state
        ? `as-fin-card-state--${metric.state.toLowerCase()}`
        : "";
    return (
        <div
            className={`as-fin-card as-fin-card--${metric.tone}`}
            data-testid={`financial-${metric.key}`}
        >
            <div className="as-fin-card-head as-fin-card-identity">
                <FinancialIcon icon={metric.icon} tone={metric.tone} />
                <div className="as-fin-card-title">
                    <span className="as-fin-card-label">{metric.label}</span>
                    <span className="as-fin-card-jp">{metric.jpLabel}</span>
                </div>
            </div>
            <div className="as-fin-card-value-cluster">
                <div className="as-fin-card-value">
                    <span
                        className="as-fin-card-number"
                        data-testid={`financial-${metric.key}-value`}
                    >
                        {metric.value ?? "—"}
                    </span>
                    {metric.unit && (
                        <span className="as-fin-card-unit" data-testid={`financial-${metric.key}-unit`}>
                            {metric.unit}
                        </span>
                    )}
                </div>
                {metric.state && (
                    <span
                        className={`as-fin-card-state ${stateClass}`}
                        data-testid={`financial-${metric.key}-state`}
                    >
                        {metric.state}
                    </span>
                )}
            </div>
        </div>
    );
}

export function AccountStatusView({
    botStatus = {},
    onPaperCapitalApplied,
    detailsExpanded = false,
    onDetailsToggle = () => {},
}) {
    const props = buildAccountRuntimeProps(botStatus);
    const derived = deriveAccountRuntime(props);
    const liveContext = deriveLiveContext(props, derived);
    const financialMetrics = deriveFinancialMetrics(derived);

    const {
        realPositionValue,
        realConnected,
        realLoading,
        realStale,
        realSyncStatus,
        resolvedExchangeAuth,
        resolvedExchangeConnection,
        resolvedApiKeyStatus,
        resolvedPermission,
        resolvedAccountType,
        authVerified,
        accountLastSync,
        paperMode,
        normalizedSelectedMode,
        paperBalance,
        paperEquity,
        paperAvailableBalance,
        paperPosition,
        paperPnl,
        paperAccount,
        realAvailableRaw,
        realPositionSummary,
        selectedExchange,
    } = derived;

    const runtimeState = {
        runtimeMode: normalizedSelectedMode,
        botState: displayValue(botStatus?.botState),
        positionState: displayRuntimeValue(
            realPositionSummary,
            {
                formatter: (value) => String(value),
                loading: realLoading,
                stale: realStale,
                emptyLabel: "NOT FETCHED",
            },
        ),
        pendingOrder: displaySyncState(
            botStatus?.pendingOrderState?.state
                ?? botStatus?.pendingOrder,
        ),
        realOrders: botStatus?.realOrderAllowed === true ? "ENABLED" : "DISABLED",
        realOrderAllowed: displayBoolean(botStatus?.realOrderAllowed),
        executionEntryAllowed: displayBoolean(botStatus?.executionEntryAllowed),
        liveOrderEntryAllowed: displayBoolean(botStatus?.liveOrderEntryAllowed),
        executionEnabled: displayBoolean(botStatus?.executionEnabled),
        executionMode: displayValue(botStatus?.executionMode),
    };

    const accountAccess = liveContext.accountAccess
        && isAvailable(liveContext.accountAccess)
        ? liveContext.accountAccess
        : resolvedExchangeConnection;
    const realExchange = derived.realAccount?.exchange ?? selectedExchange;

    return (
        <section
            className="account-status-page account-runtime-overview"
            data-testid="account-status-page"
        >
            <header className="as-page-header">
                <div>
                    <span className="as-page-kicker">Live-first account hierarchy</span>
                    <h1>Account Status（アカウント状況）</h1>
                </div>
                <span className="as-page-badge">READ ONLY</span>
            </header>

            {/* =================================================
               LEVEL 1: REAL / LIVE ACCOUNT (PRIMARY)
            ================================================= */}
            <article className="semantic-card as-primary-card clear" data-testid="real-account-section">
                <header
                    className="as-account-summary"
                    data-testid="real-account-canonical"
                >
                    <div className="as-account-summary-identity">
                        <span className="semantic-card-kicker">Production Account（本番口座）</span>
                        <h2>Real / Live Account（実口座）</h2>
                    </div>
                    <p
                        className="as-account-summary-context"
                        data-testid="real-account-paper-context"
                    >
                        {displayCurrentContext(liveContext.currentContext)}
                    </p>
                    <div className="as-account-summary-position">
                        <span>POSITION（ポジション）</span>
                        <strong data-testid="real-position">{realPositionValue}</strong>
                    </div>
                    <span className="as-account-summary-authority" data-testid="real-read-only-authority">
                        {displayValue(resolvedPermission)}
                    </span>
                </header>

                {/*
                   ACCOUNT FINANCIAL STATUS — 5px SILVER raised metallic frame.
                   Authoritative backend/exchange fields only. Missing or
                   ambiguous metrics surface as UNAVAILABLE (never a fake zero).
                */}
                <section
                    className="as-financial-frame"
                    data-testid="account-financial-status"
                >
                    <header className="as-financial-frame-header">
                        <div className="as-financial-frame-title">
                            <span className="as-financial-kicker">Account Financial Status</span>
                        </div>
                        <button
                            type="button"
                            className="as-details-toggle"
                            data-testid="account-details-toggle"
                            aria-expanded={detailsExpanded}
                            aria-controls="account-financial-details"
                            onClick={onDetailsToggle}
                        >
                            DETAILS {detailsExpanded ? "▲" : "▼"}
                        </button>
                    </header>

                    <div className="as-financial-grid" data-testid="financial-metric-grid">
                        {financialMetrics.map((metric) => (
                            <FinancialMetricCard key={metric.key} metric={metric} />
                        ))}
                    </div>

                    <div
                        id="account-financial-details"
                        className={`as-financial-details${
                            detailsExpanded ? " as-financial-details--open" : ""
                        }`}
                        data-testid="account-financial-details"
                    >
                        <div className="as-primary-details" data-testid="real-account-details">
                            <StatusMetric
                                label="Exchange（取引所）"
                                value={displayValue(realExchange)}
                                testId="real-exchange"
                                tone="connection"
                            />
                            <StatusMetric
                                label="Connection（接続）"
                                value={displayValue(resolvedExchangeConnection)}
                                testId="real-connection"
                                tone={realConnected ? "safe" : "connection"}
                            />
                            <StatusMetric
                                label="Authentication（取引所認証）"
                                value={displayValue(resolvedExchangeAuth)}
                                testId="real-auth"
                                tone={authVerified ? "safe" : "connection"}
                            />
                            <StatusMetric
                                label="API Key（APIキー）"
                                value={displayValue(resolvedApiKeyStatus)}
                                testId="real-api-key"
                                tone={authVerified ? "safe" : "connection"}
                            />
                            <StatusMetric
                                label="Permission（権限）"
                                value={displayValue(resolvedPermission)}
                                testId="real-permission"
                                tone={realConnected ? "safe" : "connection"}
                            />
                            <StatusMetric
                                label="Account Type（口座種別）"
                                value={displayValue(resolvedAccountType)}
                                testId="real-account-type"
                                tone="connection"
                            />
                            <StatusMetric
                                label="Sync Status（同期状態）"
                                value={realSyncStatus}
                                testId="real-sync-status"
                                tone={realConnected ? "safe" : "warning"}
                            />
                            <StatusMetric
                                label="Last Sync（最終同期）"
                                value={realConnected
                                    ? displayValue(accountLastSync, formatLastUpdate)
                                    : "--"
                                }
                                testId="real-last-sync"
                                tone="connection"
                            />
                        </div>
                    </div>
                </section>
            </article>

            {/* =================================================
               LEVEL 3: ACCOUNT RUNTIME + LIVE CONTEXT
            ================================================= */}
            <div className="as-secondary-grid">
                <article className="semantic-card as-card clear" data-testid="account-runtime-section">
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">Runtime state（実行状態）</span>
                            <h2>Account Runtime（アカウント実行状態）</h2>
                        </div>
                        <span className="semantic-badge">RUNTIME</span>
                    </header>

                    <div className="semantic-metric-grid three-columns" data-testid="runtime-state-grid">
                        <StatusMetric
                            label="Runtime Mode（実行モード）"
                            value={runtimeState.runtimeMode}
                            testId="runtime-mode"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Bot State（ボット状態）"
                            value={runtimeState.botState}
                            testId="runtime-bot-state"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Position State（ポジション状態）"
                            value={runtimeState.positionState}
                            testId="runtime-position-state"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Pending Order（保留注文）"
                            value={runtimeState.pendingOrder}
                            testId="runtime-pending-order"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Real Orders（実注文）"
                            value={runtimeState.realOrders}
                            testId="runtime-real-orders"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Mode（実行方式）"
                            value={runtimeState.executionMode}
                            testId="runtime-execution-mode"
                            tone="execution"
                        />
                    </div>

                    <div className="as-authority-grid" data-testid="execution-authority-grid">
                        <StatusMetric
                            label="Real Order Allowed（実注文許可）"
                            value={runtimeState.realOrderAllowed}
                            testId="authority-real-order-allowed"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Entry（注文実行許可）"
                            value={runtimeState.executionEntryAllowed}
                            testId="authority-execution-entry"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Live Order Entry（LIVE注文許可）"
                            value={runtimeState.liveOrderEntryAllowed}
                            testId="authority-live-order-entry"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Enabled（実行有効状態）"
                            value={runtimeState.executionEnabled}
                            testId="authority-execution-enabled"
                            tone="execution"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Execution authority is read-only. This page does not operate the trading system.
                        {" "}（実行権限は参照専用です。この画面から取引システムを操作することはありません。）
                    </p>
                </article>

                <article className="semantic-card as-card clear" data-testid="live-context-section">
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">Current relationship（現在の関係）</span>
                            <h2>Live Context（LIVE状態）</h2>
                        </div>
                        <span className="semantic-badge">CONTEXT</span>
                    </header>

                    <div className="semantic-metric-grid three-columns" data-testid="live-context-grid">
                        <StatusMetric
                            label="Current Mode（現在モード）"
                            value={liveContext.currentMode}
                            testId="live-context-mode"
                            tone="connection"
                        />
                        <StatusMetric
                            label="Account Access（口座アクセス）"
                            value={displayValue(accountAccess)}
                            testId="live-context-access"
                            tone="connection"
                        />
                        <StatusMetric
                            label="LIVE Execution（LIVE実行）"
                            value={liveContext.liveExecution}
                            testId="live-context-execution"
                            tone="connection"
                        />
                        <StatusMetric
                            label="Data Freshness（データ鮮度）"
                            value={liveContext.dataFreshness}
                            testId="live-context-freshness"
                            tone="connection"
                        />
                        <StatusMetric
                            label="Current Context（現在状況）"
                            value={displayCurrentContext(liveContext.currentContext)}
                            testId="live-context-message"
                            tone="connection"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Freshness sourced from the Real Account canonical state (stale / sync / connection).
                        {" "}（データ鮮度は実口座のCanonical状態［stale / sync / connection］を参照しています。）
                    </p>
                </article>
            </div>

            {/* =================================================
               LEVEL 4: PAPER / SIMULATION (SECONDARY)
            ================================================= */}
            <article className="semantic-card as-paper-card" data-testid="paper-account-section">
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">Simulation Account（シミュレーション口座）</span>
                        <h2>Paper / Simulation（ペーパー・シミュレーション）</h2>
                    </div>
                    <span className="semantic-badge">PAPER_SIMULATION</span>
                </header>

                <div className="as-paper-metrics" data-testid="paper-account-metrics">
                    <StatusMetric
                        label="Balance（模擬残高）"
                        value={displayRuntimeValue(paperBalance, {
                            formatter: formatAmount,
                        })}
                        testId="paper-balance"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Equity（模擬純資産）"
                        value={displayRuntimeValue(paperEquity, {
                            formatter: formatAmount,
                        })}
                        testId="paper-equity"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Available（模擬利用可能額）"
                        value={displayRuntimeValue(paperAvailableBalance, {
                            formatter: formatAmount,
                        })}
                        testId="paper-available"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Position（模擬ポジション）"
                        value={formatPositionValue(
                            paperPosition,
                            derived.paperAvailable ? "NO_OPEN_POSITION" : undefined,
                        )}
                        testId="paper-position"
                        tone="paper"
                    />
                    <StatusMetric
                        label="PnL（模擬損益）"
                        value={displayRuntimeValue(paperPnl, {
                            formatter: formatPnl,
                        })}
                        testId="paper-pnl"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Source（データソース）"
                        value={paperAccount.source || "PAPER_SIMULATION"}
                        testId="paper-source"
                        tone="paper"
                    />
                </div>

                <PaperCapitalControl
                    paperBalance={paperBalance}
                    realAvailableRaw={realAvailableRaw}
                    realConnected={realConnected}
                    realLoading={realLoading}
                    realStale={realStale}
                    onPaperCapitalApplied={onPaperCapitalApplied}
                />

                <p className="semantic-card-note">
                    Simulation-only account. No real funds are used.
                    {" "}（シミュレーション専用口座です。実資金は使用されません。）
                </p>
            </article>
        </section>
    );
}

export default function AccountStatusPage() {
    const { data } = usePolling(fetchBotStatus, 5000);
    const botStatus = data?.data;
    const [detailsExpanded, setDetailsExpanded] = useState(false);

    const refreshBotStatus = async () => {
        const snapshot = await fetchBotStatus();
        return snapshot.data;
    };

    return (
        <AccountStatusView
            botStatus={botStatus}
            onPaperCapitalApplied={refreshBotStatus}
            detailsExpanded={detailsExpanded}
            onDetailsToggle={() => setDetailsExpanded((expanded) => !expanded)}
        />
    );
}
