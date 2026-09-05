import usePolling from "../hooks/usePolling";
import PaperCapitalControl from "../components/runtime/PaperCapitalControl";
import StatusMetric from "../components/runtime/StatusMetric";
import {
    buildAccountRuntimeProps,
    deriveAccountRuntime,
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

export function AccountStatusView({
    botStatus = {},
    onPaperCapitalApplied,
}) {
    const props = buildAccountRuntimeProps(botStatus);
    const derived = deriveAccountRuntime(props);
    const liveContext = deriveLiveContext(props, derived);

    const {
        realBalanceValue,
        realEquityValue,
        realAvailableValue,
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
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">Production Account（本番口座）</span>
                        <h2>Real / Live Account（実口座）</h2>
                    </div>
                    <span
                        className={`semantic-badge semantic-badge-${
                            realLoading
                                ? "refreshing"
                                : realStale
                                    ? "stale"
                                    : realConnected
                                        ? "connected"
                                        : "not-connected"
                        }`}
                        data-testid="real-account-badge"
                    >
                        {paperMode ? "READ ONLY" : realSyncStatus}
                    </span>
                </header>

                {paperMode && (
                    <p className="semantic-card-context" data-testid="real-account-paper-context">
                        {displayCurrentContext(liveContext.currentContext)}
                    </p>
                )}

                <div className="as-primary-metrics" data-testid="real-account-metrics">
                    <StatusMetric
                        label="Balance（残高）"
                        value={realBalanceValue}
                        testId="real-balance"
                        tone="real"
                    />
                    <StatusMetric
                        label="Equity（純資産）"
                        value={realEquityValue}
                        testId="real-equity"
                        tone="real"
                    />
                    <StatusMetric
                        label="Available（利用可能額）"
                        value={realAvailableValue}
                        testId="real-available"
                        tone="real"
                    />
                    <StatusMetric
                        label="Position（ポジション）"
                        value={realPositionValue}
                        testId="real-position"
                        tone="real"
                    />
                </div>

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

    const refreshBotStatus = async () => {
        const snapshot = await fetchBotStatus();
        return snapshot.data;
    };

    return (
        <AccountStatusView
            botStatus={botStatus}
            onPaperCapitalApplied={refreshBotStatus}
        />
    );
}
