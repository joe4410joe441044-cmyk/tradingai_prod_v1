import {
    deriveAccountRuntime,
    displayRuntimeValue,
    displayValue,
    formatAmount,
    formatLastUpdate,
    formatPnl,
    formatPositionValue,
} from "./accountRuntimeModel";
import StatusMetric from "./StatusMetric";
import PaperCapitalControl from "./PaperCapitalControl";

export default function AccountRuntimeOverview(props) {
    const {
        variant = "summary",
        exchange,
        executionMode,
        realOrderAllowed,
        allowLive,
        tradeMode,
        dryRun,
        accountSource,
        balanceSource,
        positionSource,
        accountSourceReason,
        balanceSourceReason,
        positionSourceReason,
        lastUpdate,
        onPaperCapitalApplied,
    } = props;

    const isSummary = variant !== "diagnostics";
    const isDiagnostics = variant === "diagnostics";

    const derived = deriveAccountRuntime(props);
    const {
        paperAccount,
        paperAvailable,
        paperBalance,
        paperEquity,
        paperAvailableBalance,
        paperPosition,
        paperPnl,
        realConnected,
        realLoading,
        realStale,
        realSyncStatus,
        resolvedExchangeAuth,
        resolvedExchangeConnection,
        resolvedApiKeyStatus,
        resolvedPermission,
        resolvedAccountType,
        resolvedAuthReason,
        resolvedConnectionReason,
        resolvedAccountReason,
        resolvedBalanceReason,
        resolvedPositionReason,
        realAvailableRaw,
        normalizedSelectedMode,
        paperMode,
        authVerified,
        accountLastSync,
        realBalanceValue,
        realEquityValue,
        realAvailableValue,
        realPositionValue,
        displayedReason,
    } = derived;

    return (
        <section
            className="account-runtime-overview"
            data-testid="account-runtime-overview"
        >
            {isSummary && (
            <div className="account-separation-grid">
                <article className="semantic-card semantic-card-real">
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">Authenticated account only</span>
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
                        >
                            {paperMode ? "READ ONLY" : realSyncStatus}
                        </span>
                    </header>

                    {paperMode && (
                        <p className="semantic-card-context" data-testid="real-account-paper-context">
                            PAPER MODE — LIVE ACCOUNT INACTIVE · Sync: {realSyncStatus}
                        </p>
                    )}

                    <div className="semantic-metric-grid three-columns">
                        <StatusMetric
                            label="Real Balance:（実残高）"
                            value={realBalanceValue}
                            testId="real-balance"
                            tone="real"
                        />
                        <StatusMetric
                            label="Real Equity:（実純資産）"
                            value={realEquityValue}
                            tone="real"
                        />
                        <StatusMetric
                            label="Available Balance:（実利用可能額）"
                            value={realAvailableValue}
                            tone="real"
                        />
                        <StatusMetric
                            label="Real Position:（実ポジション）"
                            value={realPositionValue}
                            testId="real-position"
                            tone="real"
                        />
                        <StatusMetric
                            label="Auth:（取引所認証）"
                            value={displayValue(resolvedExchangeAuth)}
                            testId="exchange-auth"
                            tone={authVerified ? "safe" : "real"}
                        />
                        <StatusMetric
                            label="Permission:（権限）"
                            value={displayValue(resolvedPermission)}
                            tone="real"
                        />
                        <StatusMetric
                            label="Last Sync:（最終同期）"
                            value={realConnected
                                ? displayValue(accountLastSync, formatLastUpdate)
                                : "--"
                            }
                            tone="real"
                        />
                    </div>

                    <p className="semantic-card-note">
                        {displayValue(accountSourceReason || resolvedAccountReason)}
                    </p>
                </article>

                <article className="semantic-card semantic-card-paper">
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">Virtual account only</span>
                            <h2>Paper / Simulation Account</h2>
                        </div>
                        <span className="semantic-badge">PAPER_SIMULATION</span>
                    </header>

                    <div className="semantic-metric-grid three-columns">
                        <StatusMetric
                            label="Paper Balance:（模擬残高）"
                            value={displayRuntimeValue(paperBalance, {
                                formatter: formatAmount,
                            })}
                            testId="paper-balance"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper Equity:（模擬純資産）"
                            value={displayRuntimeValue(paperEquity, {
                                formatter: formatAmount,
                            })}
                            testId="paper-equity"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper Available:（模擬利用可能額）"
                            value={displayRuntimeValue(paperAvailableBalance, {
                                formatter: formatAmount,
                            })}
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper Position:（模擬ポジション）"
                            value={formatPositionValue(
                                paperPosition,
                                paperAvailable ? "NO_OPEN_POSITION" : undefined,
                            )}
                            testId="paper-position"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper PnL:（模擬損益）"
                            value={displayRuntimeValue(paperPnl, {
                                formatter: formatPnl,
                            })}
                            testId="paper-pnl"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Source:（データソース）"
                            value={paperAccount.source || "PAPER_SIMULATION"}
                            testId="account-source"
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
            </div>
            )}

            {isDiagnostics && (
            <div className="operational-separation-grid">
                <article className="semantic-card semantic-card-execution">
                    <header className="semantic-card-header compact">
                        <div>
                            <span className="semantic-card-kicker">Order capability</span>
                            <h2>Trading Mode &amp; Execution</h2>
                        </div>
                        <span className="semantic-badge">RUNTIME</span>
                    </header>

                    <div className="semantic-metric-grid three-columns">
                        <StatusMetric
                            label="Selected Mode:（選択モード）"
                            value={normalizedSelectedMode}
                            testId="selected-mode"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Execution Mode:（実行モード）"
                            value={displayValue(executionMode)}
                            testId="execution-mode"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Allow Live:（本番許可）"
                            value={String(allowLive === true)}
                            testId="allow-live"
                            tone={allowLive ? "safe" : "danger"}
                        />
                        <StatusMetric
                            label="Trade Mode:（取引モード）"
                            value={displayValue(tradeMode)}
                            testId="trade-mode"
                            tone="execution"
                        />
                        <StatusMetric
                            label="Dry Run:（ドライラン）"
                            value={String(dryRun !== false)}
                            testId="dry-run"
                            tone={dryRun !== false ? "warning" : "danger"}
                        />
                        <StatusMetric
                            label="Real Orders:（実注文）"
                            value={realOrderAllowed ? "ENABLED" : "DISABLED"}
                            testId="real-orders"
                            tone={realOrderAllowed ? "safe" : "danger"}
                        />
                        <StatusMetric
                            label="Real Order Allowed:（実注文許可）"
                            value={String(realOrderAllowed === true)}
                            testId="real-order-allowed"
                            tone={realOrderAllowed ? "safe" : "danger"}
                        />
                        <StatusMetric
                            label="Reason:（理由）"
                            value={displayedReason}
                            testId="safety-reason"
                            tone="warning"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Runtime status updated {displayValue(lastUpdate, formatLastUpdate)}.
                        {realOrderAllowed
                            ? " Real-order capability is enabled."
                            : " Real orders are disabled."
                        }
                    </p>
                </article>

                <article className="semantic-card semantic-card-connection">
                    <header className="semantic-card-header compact">
                        <div>
                            <span className="semantic-card-kicker">Account access only</span>
                            <h2>Connection &amp; Auth</h2>
                        </div>
                        <span className="semantic-badge">AUTH</span>
                    </header>

                    <div className="semantic-metric-grid three-columns">
                        <StatusMetric
                            label="Exchange:（取引所）"
                            value={displayValue(exchange).toUpperCase()}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Exchange Connection:（口座接続）"
                            value={displayValue(
                                resolvedExchangeConnection
                                || (realConnected ? "CONNECTED" : "NOT_CONNECTED"),
                            )}
                            tone={realConnected ? "safe" : "connection"}
                        />
                        <StatusMetric
                            label="API Key:（APIキー状態）"
                            value={displayValue(resolvedApiKeyStatus)}
                            tone={authVerified ? "safe" : "connection"}
                        />
                        <StatusMetric
                            label="Permission:（権限）"
                            value={displayValue(resolvedPermission)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Account Type:（口座種別）"
                            value={displayValue(resolvedAccountType)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Exchange Auth:（取引所認証）"
                            value={displayValue(resolvedExchangeAuth)}
                            testId="exchange-auth"
                            tone={authVerified ? "safe" : "connection"}
                        />
                        <StatusMetric
                            label="accountSource"
                            value={displayValue(accountSource)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="balanceSource"
                            value={displayValue(balanceSource)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="positionSource"
                            value={displayValue(positionSource)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Last Sync:（口座同期）"
                            value={realConnected
                                ? displayValue(accountLastSync, formatLastUpdate)
                                : "--"
                            }
                            tone="connection"
                        />
                        <StatusMetric
                            label="Auth Reason"
                            value={displayValue(resolvedAuthReason)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Balance Reason"
                            value={displayValue(balanceSourceReason || resolvedBalanceReason)}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Position Reason"
                            value={displayValue(positionSourceReason || resolvedPositionReason)}
                            tone="connection"
                        />
                    </div>

                    <p className="semantic-card-note">
                        {displayValue(resolvedConnectionReason)}
                    </p>
                </article>
            </div>
            )}

            {isSummary && (
            <div className="semantic-legend" aria-label="Status color legend">
                <span><i className="legend-paper" />Paper / Simulation</span>
                <span><i className="legend-real" />Real / Live</span>
                <span><i className="legend-execution" />Execution / Runtime</span>
                <span><i className="legend-connection" />Connection / Auth</span>
            </div>
            )}
        </section>
    );
}
