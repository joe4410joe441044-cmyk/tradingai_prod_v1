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
                    <h1>Account Status</h1>
                </div>
                <span className="as-page-badge">READ ONLY</span>
            </header>

            {/* =================================================
               LEVEL 1: REAL / LIVE ACCOUNT (PRIMARY)
            ================================================= */}
            <article className="semantic-card as-primary-card clear" data-testid="real-account-section">
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">Production Account</span>
                        <h2>Real / Live Account</h2>
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
                        PAPER MODE — LIVE ACCOUNT INACTIVE
                    </p>
                )}

                <div className="as-primary-metrics" data-testid="real-account-metrics">
                    <StatusMetric
                        label="Balance"
                        value={realBalanceValue}
                        testId="real-balance"
                        tone="real"
                    />
                    <StatusMetric
                        label="Equity"
                        value={realEquityValue}
                        testId="real-equity"
                        tone="real"
                    />
                    <StatusMetric
                        label="Available"
                        value={realAvailableValue}
                        testId="real-available"
                        tone="real"
                    />
                    <StatusMetric
                        label="Position"
                        value={realPositionValue}
                        testId="real-position"
                        tone="real"
                    />
                </div>

                <div className="as-primary-details" data-testid="real-account-details">
                    <StatusMetric
                        label="Exchange"
                        value={displayValue(realExchange)}
                        testId="real-exchange"
                        tone="connection"
                    />
                    <StatusMetric
                        label="Connection"
                        value={displayValue(resolvedExchangeConnection)}
                        testId="real-connection"
                        tone={realConnected ? "safe" : "connection"}
                    />
                    <StatusMetric
                        label="Authentication"
                        value={displayValue(resolvedExchangeAuth)}
                        testId="real-auth"
                        tone={authVerified ? "safe" : "connection"}
                    />
                    <StatusMetric
                        label="API Key"
                        value={displayValue(resolvedApiKeyStatus)}
                        testId="real-api-key"
                        tone={authVerified ? "safe" : "connection"}
                    />
                    <StatusMetric
                        label="Permission"
                        value={displayValue(resolvedPermission)}
                        testId="real-permission"
                        tone={realConnected ? "safe" : "connection"}
                    />
                    <StatusMetric
                        label="Account Type"
                        value={displayValue(resolvedAccountType)}
                        testId="real-account-type"
                        tone="connection"
                    />
                    <StatusMetric
                        label="Sync Status"
                        value={realSyncStatus}
                        testId="real-sync-status"
                        tone={realConnected ? "safe" : "warning"}
                    />
                    <StatusMetric
                        label="Last Sync"
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
                            <span className="semantic-card-kicker">Runtime state</span>
                            <h2>Account Runtime</h2>
                        </div>
                        <span className="semantic-badge">RUNTIME</span>
                    </header>

                    <div className="semantic-metric-grid three-columns" data-testid="runtime-state-grid">
                        <StatusMetric
                            label="Runtime Mode"
                            value={runtimeState.runtimeMode}
                            testId="runtime-mode"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Bot State"
                            value={runtimeState.botState}
                            testId="runtime-bot-state"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Position State"
                            value={runtimeState.positionState}
                            testId="runtime-position-state"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Pending Order"
                            value={runtimeState.pendingOrder}
                            testId="runtime-pending-order"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Real Orders"
                            value={runtimeState.realOrders}
                            testId="runtime-real-orders"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Mode"
                            value={runtimeState.executionMode}
                            testId="runtime-execution-mode"
                            tone="execution"
                        />
                    </div>

                    <div className="as-authority-grid" data-testid="execution-authority-grid">
                        <StatusMetric
                            label="Real Order Allowed"
                            value={runtimeState.realOrderAllowed}
                            testId="authority-real-order-allowed"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Entry"
                            value={runtimeState.executionEntryAllowed}
                            testId="authority-execution-entry"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Live Order Entry"
                            value={runtimeState.liveOrderEntryAllowed}
                            testId="authority-live-order-entry"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Enabled"
                            value={runtimeState.executionEnabled}
                            testId="authority-execution-enabled"
                            tone="execution"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Execution authority is read-only. This page does not operate the trading system.
                    </p>
                </article>

                <article className="semantic-card as-card clear" data-testid="live-context-section">
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">Current relationship</span>
                            <h2>Live Context</h2>
                        </div>
                        <span className="semantic-badge">CONTEXT</span>
                    </header>

                    <div className="semantic-metric-grid three-columns" data-testid="live-context-grid">
                        <StatusMetric
                            label="Current Mode"
                            value={liveContext.currentMode}
                            testId="live-context-mode"
                            tone="connection"
                        />
                        <StatusMetric
                            label="Account Access"
                            value={displayValue(accountAccess)}
                            testId="live-context-access"
                            tone="connection"
                        />
                        <StatusMetric
                            label="LIVE Execution"
                            value={liveContext.liveExecution}
                            testId="live-context-execution"
                            tone="connection"
                        />
                        <StatusMetric
                            label="Data Freshness"
                            value={liveContext.dataFreshness}
                            testId="live-context-freshness"
                            tone="connection"
                        />
                        <StatusMetric
                            label="Current Context"
                            value={liveContext.currentContext}
                            testId="live-context-message"
                            tone="connection"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Freshness sourced from the Real Account canonical state (stale / sync / connection).
                    </p>
                </article>
            </div>

            {/* =================================================
               LEVEL 4: PAPER / SIMULATION (SECONDARY)
            ================================================= */}
            <article className="semantic-card as-paper-card" data-testid="paper-account-section">
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">Simulation Account</span>
                        <h2>Paper / Simulation</h2>
                    </div>
                    <span className="semantic-badge">PAPER_SIMULATION</span>
                </header>

                <div className="as-paper-metrics" data-testid="paper-account-metrics">
                    <StatusMetric
                        label="Balance"
                        value={displayRuntimeValue(paperBalance, {
                            formatter: formatAmount,
                        })}
                        testId="paper-balance"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Equity"
                        value={displayRuntimeValue(paperEquity, {
                            formatter: formatAmount,
                        })}
                        testId="paper-equity"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Available"
                        value={displayRuntimeValue(paperAvailableBalance, {
                            formatter: formatAmount,
                        })}
                        testId="paper-available"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Position"
                        value={formatPositionValue(
                            paperPosition,
                            derived.paperAvailable ? "NO_OPEN_POSITION" : undefined,
                        )}
                        testId="paper-position"
                        tone="paper"
                    />
                    <StatusMetric
                        label="PnL"
                        value={displayRuntimeValue(paperPnl, {
                            formatter: formatPnl,
                        })}
                        testId="paper-pnl"
                        tone="paper"
                    />
                    <StatusMetric
                        label="Source"
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
