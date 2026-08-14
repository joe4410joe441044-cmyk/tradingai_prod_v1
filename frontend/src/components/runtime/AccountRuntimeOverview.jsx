import { useEffect, useState } from "react";
import { API } from "../../api";

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

const displayRuntimeValue = (
    value,
    {
        formatter,
        loading = false,
        stale = false,
        emptyLabel = "NOT FETCHED",
    } = {},
) => {
    if (loading) {
        return "REFRESHING";
    }

    if (stale) {
        return "STALE";
    }

    if (Array.isArray(value) && value.length === 0) {
        return "NO OPEN POSITION";
    }

    if (!isAvailable(value)) {
        return emptyLabel;
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
    const numericValue = Number(value);
    const date = new Date(
        Number.isFinite(numericValue) && numericValue < 1000000000000
            ? numericValue * 1000
            : value,
    );

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

const formatPositionValue = (
    value,
    state,
    {
        loading = false,
        stale = false,
        emptyLabel = "NOT FETCHED",
    } = {},
) => {
    if (loading) {
        return "REFRESHING";
    }

    if (stale) {
        return "STALE";
    }

    if (Array.isArray(value)) {
        if (value.length === 0) {
            return "FLAT";
        }

        return formatPositionValue(value[0], state);
    }

    if (value && typeof value === "object") {
        const symbol = value.symbol ?? value.pair ?? "--";
        const side = value.side ?? value.position_side ?? value.state ?? "--";
        const qty = value.qty ?? value.size ?? value.coin_qty;

        return qty !== null && qty !== undefined && qty !== ""
            ? `${symbol} ${side} ${qty}`
            : `${symbol} ${side}`;
    }

    if (isAvailable(value)) {
        return String(value);
    }

    if (state === "NO_OPEN_POSITION" || state === "FLAT") {
        return "FLAT";
    }

    return displayRuntimeValue(state, { emptyLabel });
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
    variant = "summary",
    accountRuntime,
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
    exchangeConnection,
    apiKeyStatus,
    permission,
    accountType,
    exchangeAuthReason,
    exchangeConnectionReason,
    accountReason,
    balanceReason,
    positionReason,
    accountSourceReason,
    balanceSourceReason,
    positionSourceReason,
    realAccountConnected,
    realBalance,
    realEquity,
    realAvailableBalance,
    realPosition,
    realPositionState,
    realAccountLastSync,
    realLastSync,
    balance,
    equity,
    availableBalance,
    position,
    pnl,
    lastUpdate,
    onPaperCapitalApplied,
}) {
    const isSummary = variant !== "diagnostics";
    const isDiagnostics = variant === "diagnostics";
    const runtime = accountRuntime && typeof accountRuntime === "object"
        ? accountRuntime
        : {};
    const paperAccount = runtime.paperAccount || {};
    const realAccount = runtime.realAccount || {};
    const connection = runtime.connection || {};
    const hasAccountRuntime = Boolean(runtime.paperAccount || runtime.realAccount);
    const paperAvailable = hasAccountRuntime
        ? paperAccount.available !== false
        : true;
    const paperBalance = paperAvailable
        ? paperAccount.balance ?? balance
        : null;
    const paperEquity = paperAvailable
        ? paperAccount.equity ?? equity
        : null;
    const paperAvailableBalance = paperAvailable
        ? paperAccount.availableBalance ?? availableBalance
        : null;
    const paperPosition = paperAvailable
        ? paperAccount.positions ?? paperAccount.position ?? position
        : null;
    const paperPnl = paperAvailable
        ? paperAccount.totalPnl ?? pnl
        : null;
    const [capitalExpanded, setCapitalExpanded] = useState(false);
    const [capitalInput, setCapitalInput] = useState("");
    const [capitalSource, setCapitalSource] = useState("DASHBOARD_MANUAL");
    const [capitalConfirming, setCapitalConfirming] = useState(false);
    const [capitalSubmitting, setCapitalSubmitting] = useState(false);
    const [capitalMessage, setCapitalMessage] = useState(null);
    const [capitalDirty, setCapitalDirty] = useState(false);
    useEffect(() => {
        if (!capitalDirty && isAvailable(paperBalance)) {
            setCapitalInput(String(paperBalance));
        }
    }, [capitalDirty, paperBalance]);

    const capitalNumber = Number(capitalInput);
    const capitalError = !capitalInput.trim()
        ? "Simulation capital is required."
        : !/^\d+(?:\.\d{1,2})?$/.test(capitalInput.trim())
            ? "Enter a valid amount with up to 2 decimal places."
            : !Number.isFinite(capitalNumber) || capitalNumber < 0.01
                ? "Simulation capital must be at least 0.01 USDT."
                : capitalNumber > 1_000_000_000
                    ? "Simulation capital must not exceed 1,000,000,000.00 USDT."
                    : null;

    const chooseCapital = (value, source = "DASHBOARD_MANUAL") => {
        setCapitalInput(String(value));
        setCapitalSource(source);
        setCapitalDirty(true);
        setCapitalConfirming(false);
        setCapitalMessage(null);
    };

    const submitPaperCapital = async () => {
        if (capitalSubmitting || capitalError) return;
        setCapitalSubmitting(true);
        setCapitalMessage(null);
        try {
            const response = await fetch(API.paperAccountCapital(), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    capital: capitalInput.trim(),
                    source: capitalSource,
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload.detail || "Unable to reset paper capital.");
            }
            if (onPaperCapitalApplied) await onPaperCapitalApplied();
            setCapitalDirty(false);
            setCapitalConfirming(false);
            setCapitalMessage({
                type: "success",
                text: `Paper simulation capital reset to ${formatAmount(payload.paperBalance)} USDT.`,
            });
        } catch (error) {
            setCapitalMessage({
                type: "error",
                text: `Unable to reset paper capital. Reason: ${error.message}`,
            });
        } finally {
            setCapitalSubmitting(false);
        }
    };
    const selectedExchange = String(exchange ?? "").trim().toUpperCase();
    const realExchange = String(realAccount.exchange ?? "").trim().toUpperCase();
    const realExchangeMatches = !realExchange || realExchange === selectedExchange;
    const realLoading = realExchangeMatches && realAccount.loading === true;
    const realStale = realExchangeMatches && realAccount.stale === true;
    const realAuthenticated = realExchangeMatches
        && (
            realAccount.authenticated === true
            || Boolean(realAccount.balanceSource)
            || Boolean(realAccount.positionSource)
        );
    const resolvedExchangeAuth = realAuthenticated
        ? "VERIFIED"
        : exchangeAuth;
    const resolvedExchangeConnection = realExchangeMatches
        ? connection.apiKeyStatus
            ? realAccount.connected === true
                ? "CONNECTED"
                : "NOT_CONNECTED"
            : exchangeConnection
        : "NOT_CONNECTED";
    const resolvedApiKeyStatus = connection.apiKeyStatus || apiKeyStatus;
    const resolvedPermission = realAccount.permission || permission;
    const resolvedAccountType = realAccount.accountType || accountType;
    const resolvedAuthReason = realAccount.authReason || exchangeAuthReason;
    const resolvedConnectionReason = realExchangeMatches
        ? realAccount.connectionReason || exchangeConnectionReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const resolvedAccountReason = realExchangeMatches
        ? realAccount.accountReason || accountReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const resolvedBalanceReason = realExchangeMatches
        ? realAccount.balanceReason || balanceReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const resolvedPositionReason = realExchangeMatches
        ? realAccount.positionReason || positionReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const realPositions = realExchangeMatches
        ? realAccount.positions ?? realPosition
        : null;
    const realBalanceRaw = realExchangeMatches
        ? realAccount.balance ?? realBalance
        : null;
    const realEquityRaw = realExchangeMatches
        ? realAccount.equity ?? realEquity
        : null;
    const realAvailableRaw = realExchangeMatches
        ? realAccount.availableBalance ?? realAvailableBalance
        : null;
    const realPositionSummary = realExchangeMatches
        ? realAccount.positionSummary ?? realPositionState
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const realConnected = realExchangeMatches
        && (
            realAccountConnected
            || realAuthenticated
            || realAccount.connected === true
        );
    const realAvailablePresetEnabled = realConnected
        && !realLoading
        && !realStale
        && Number.isFinite(Number(realAvailableRaw));
    const normalizedSelectedMode = String(selectedMode ?? "PAPER").toUpperCase();
    const paperMode = normalizedSelectedMode === "PAPER";
    const realSyncStatus = realLoading
        ? "REFRESHING"
        : realStale
            ? "STALE"
            : realConnected
                ? "CONNECTED"
                : "NOT_CONNECTED";
    const normalizedAuth = String(resolvedExchangeAuth ?? "NOT_VERIFIED").toUpperCase();
    const authVerified = normalizedAuth === "VERIFIED";
    const displayedReason = normalizedSelectedMode === "LIVE" && !realOrderAllowed
        && !String(safetyReason ?? "").includes("LIVE_NOT_ENABLED")
        ? "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE"
        : displayValue(safetyReason);
    const accountLastSync = realAccount.lastSync
        ?? realLastSync
        ?? realAccountLastSync
        ?? lastUpdate;
    const realUnavailable = displayValue(
        resolvedAccountReason
        || resolvedBalanceReason
        || "NOT_CONNECTED",
    );
    const realBalanceValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realBalanceRaw, {
            formatter: formatAmount,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
    const realEquityValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realEquityRaw, {
            formatter: formatAmount,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
    const realAvailableValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realAvailableRaw, {
            formatter: formatAmount,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
    const realPositionValue = realConnected || realLoading || realStale
        ? formatPositionValue(realPositions, realPositionSummary, {
            loading: realLoading,
            stale: realStale,
        })
        : displayValue(resolvedPositionReason || resolvedAccountReason || "NOT_CONNECTED");

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

                    <div className="paper-capital-control">
                        <button
                            type="button"
                            className="paper-capital-toggle"
                            aria-expanded={capitalExpanded}
                            onClick={() => setCapitalExpanded((value) => !value)}
                        >
                            {capitalExpanded ? "▼" : "▶"} Set Paper Capital
                        </button>
                        {capitalExpanded && (
                            <div className="paper-capital-panel">
                                <label htmlFor="simulation-capital-input">Simulation Capital (USDT)</label>
                                <input
                                    id="simulation-capital-input"
                                    inputMode="decimal"
                                    value={capitalInput}
                                    aria-invalid={Boolean(capitalError)}
                                    onChange={(event) => chooseCapital(event.target.value)}
                                />
                                <div className="paper-capital-presets">
                                    <button
                                        type="button"
                                        disabled={!realAvailablePresetEnabled}
                                        title={realAvailablePresetEnabled ? "Copy current real available balance" : "REAL_ACCOUNT_NOT_SYNCED"}
                                        onClick={() => chooseCapital(realAvailableRaw, "REAL_AVAILABLE_PRESET")}
                                    >
                                        Real Available
                                    </button>
                                    {["100", "1000", "10000"].map((preset) => (
                                        <button type="button" key={preset} onClick={() => chooseCapital(preset)}>
                                            {formatAmount(preset)}
                                        </button>
                                    ))}
                                </div>
                                {capitalError && capitalDirty && (
                                    <p className="paper-capital-feedback error">{capitalError}</p>
                                )}
                                {!capitalConfirming ? (
                                    <button
                                        type="button"
                                        className="paper-capital-apply"
                                        disabled={Boolean(capitalError) || capitalSubmitting}
                                        onClick={() => setCapitalConfirming(true)}
                                    >
                                        Apply Paper Capital
                                    </button>
                                ) : (
                                    <div className="paper-capital-confirm" role="alertdialog" aria-labelledby="paper-capital-confirm-title">
                                        <strong id="paper-capital-confirm-title">Reset Paper Account?</strong>
                                        <span>New Simulation Capital: {formatAmount(capitalNumber)} USDT</span>
                                        <span>Balance, equity, PnL and paper positions will reset. Real funds are not affected.</span>
                                        <div>
                                            <button type="button" disabled={capitalSubmitting} onClick={() => setCapitalConfirming(false)}>Cancel</button>
                                            <button type="button" disabled={capitalSubmitting} onClick={submitPaperCapital}>
                                                {capitalSubmitting ? "Applying…" : "Reset Paper Account"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                                <div className="paper-capital-live" aria-live="polite">
                                    {capitalMessage && (
                                        <p className={`paper-capital-feedback ${capitalMessage.type}`}>{capitalMessage.text}</p>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>

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
