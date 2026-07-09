const EMPTY_VALUES = new Set([
    "UNKNOWN",
    "NO DATA",
    "NONE",
    "UNDEFINED",
    "NAN",
]);

const isAvailable = (value) => {
    if (value === null || value === undefined || value === "") {
        return false;
    }

    if (typeof value === "number" && !Number.isFinite(value)) {
        return false;
    }

    return !EMPTY_VALUES.has(String(value).trim().toUpperCase());
};

const displayValue = (value, formatter) => {
    if (!isAvailable(value)) {
        return "--";
    }

    return formatter ? formatter(value) : String(value);
};

const formatAmount = (value) => {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return "--";
    }

    return numericValue.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
};

const formatPnl = (value) => {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return "--";
    }

    return `${numericValue > 0 ? "+" : ""}${numericValue.toFixed(2)}`;
};

const formatLastUpdate = (value) => {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "--";
    }

    return date.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
    });
};

function StatusMetric({
    label,
    value,
    testId,
    tone = "neutral",
}) {
    return (
        <div className="semantic-metric">
            <span className="semantic-metric-label">{label}</span>
            <span
                className={`semantic-metric-value tone-${tone}`}
                data-testid={testId}
            >
                {value}
            </span>
        </div>
    );
}

export default function AccountRuntimeOverview({
    exchange,
    selectedMode,
    executionMode,
    realOrderAllowed,
    dryRun,
    safetyReason,
    allowLive,
    tradeMode,
    accountSource,
    balanceSource,
    positionSource,
    exchangeAuth,
    realAccountConnected,
    realBalance,
    realPosition,
    balance,
    equity,
    availableBalance,
    position,
    pnl,
    lastUpdate,
}) {
    const paperBalance = balanceSource === "PAPER_SIMULATION"
        ? balance
        : undefined;
    const paperEquity = balanceSource === "PAPER_SIMULATION"
        ? equity
        : undefined;
    const paperAvailableBalance = balanceSource === "PAPER_SIMULATION"
        ? availableBalance
        : undefined;
    const paperPosition = positionSource === "PAPER_SIMULATION"
        ? position
        : undefined;
    const paperPnl = accountSource === "PAPER_SIMULATION"
        ? pnl
        : undefined;
    const normalizedSelectedMode = String(selectedMode ?? "PAPER").toUpperCase();
    const normalizedAuth = String(exchangeAuth ?? "NOT_VERIFIED").toUpperCase();
    const authVerified = normalizedAuth === "VERIFIED";
    const displayedReason = normalizedSelectedMode === "LIVE" && !realOrderAllowed
        && !String(safetyReason ?? "").includes("LIVE_NOT_ENABLED")
        ? "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE"
        : displayValue(safetyReason);
    const realUnavailable = realAccountConnected ? "--" : "NOT CONNECTED";

    return (
        <section
            className="account-runtime-overview"
            data-testid="account-runtime-overview"
        >
            <div className="account-separation-grid">
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
                            value={displayValue(paperBalance, formatAmount)}
                            testId="paper-balance"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper Equity:（模擬純資産）"
                            value={displayValue(paperEquity, formatAmount)}
                            testId="paper-equity"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper Available:（模擬利用可能額）"
                            value={displayValue(paperAvailableBalance, formatAmount)}
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper Position:（模擬ポジション）"
                            value={displayValue(paperPosition)}
                            testId="paper-position"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Paper PnL:（模擬損益）"
                            value={displayValue(paperPnl, formatPnl)}
                            testId="paper-pnl"
                            tone="paper"
                        />
                        <StatusMetric
                            label="Source:（データソース）"
                            value={displayValue(accountSource)}
                            testId="account-source"
                            tone="paper"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Simulation-only account. No real funds are used.
                    </p>
                </article>

                <article className="semantic-card semantic-card-real">
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">Authenticated account only</span>
                            <h2>Real / Live Account</h2>
                        </div>
                        <span className="semantic-badge">
                            {realAccountConnected ? "CONNECTED" : "NOT_CONNECTED"}
                        </span>
                    </header>

                    <div className="semantic-metric-grid three-columns">
                        <StatusMetric
                            label="Real Balance:（実残高）"
                            value={realAccountConnected
                                ? displayValue(realBalance, formatAmount)
                                : realUnavailable
                            }
                            testId="real-balance"
                            tone="real"
                        />
                        <StatusMetric
                            label="Real Equity:（実純資産）"
                            value={realUnavailable}
                            tone="real"
                        />
                        <StatusMetric
                            label="Available Balance:（実利用可能額）"
                            value={realUnavailable}
                            tone="real"
                        />
                        <StatusMetric
                            label="Real Position:（実ポジション）"
                            value={realAccountConnected
                                ? displayValue(realPosition)
                                : realUnavailable
                            }
                            testId="real-position"
                            tone="real"
                        />
                        <StatusMetric
                            label="Exchange Auth:（取引所認証）"
                            value={displayValue(exchangeAuth)}
                            testId="exchange-auth"
                            tone={authVerified ? "safe" : "real"}
                        />
                        <StatusMetric
                            label="Last Sync:（最終同期）"
                            value={realAccountConnected
                                ? displayValue(lastUpdate, formatLastUpdate)
                                : "--"
                            }
                            tone="real"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Real account data is unavailable until exchange authentication is verified.
                    </p>
                </article>
            </div>

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
                            value={realAccountConnected ? "CONNECTED" : "NOT CONNECTED"}
                            tone={realAccountConnected ? "safe" : "connection"}
                        />
                        <StatusMetric
                            label="API Key:（APIキー状態）"
                            value={authVerified ? "VERIFIED" : "NOT VERIFIED"}
                            tone={authVerified ? "safe" : "connection"}
                        />
                        <StatusMetric
                            label="Permission:（権限）"
                            value={authVerified ? "VERIFIED" : "--"}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Account Type:（口座種別）"
                            value={authVerified ? "VERIFIED" : "NOT VERIFIED"}
                            tone="connection"
                        />
                        <StatusMetric
                            label="Last Sync:（口座同期）"
                            value={realAccountConnected
                                ? displayValue(lastUpdate, formatLastUpdate)
                                : "--"
                            }
                            tone="connection"
                        />
                    </div>

                    <p className="semantic-card-note">
                        Connection status never implies real-order permission.
                    </p>
                </article>
            </div>

            <div className="semantic-legend" aria-label="Status color legend">
                <span><i className="legend-paper" />Paper / Simulation</span>
                <span><i className="legend-real" />Real / Live</span>
                <span><i className="legend-execution" />Execution / Runtime</span>
                <span><i className="legend-connection" />Connection / Auth</span>
            </div>
        </section>
    );
}
