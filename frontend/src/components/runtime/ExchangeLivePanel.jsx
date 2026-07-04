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

export default function ExchangeLivePanel({
    exchange,
    connection,
    selectedMode,
    executionMode,
    realOrderAllowed,
    dryRun,
    safetyReason,
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
    const displayedReason = normalizedSelectedMode === "LIVE" && !realOrderAllowed
        && !String(safetyReason ?? "").includes("LIVE_NOT_ENABLED")
        ? "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE"
        : displayValue(safetyReason);

    const items = [
        { label: "EXCHANGE（取引所）", value: displayValue(exchange) },
        { label: "MARKET DATA CONNECTION（市場データ接続）", value: displayValue(connection) },
        {
            label: "Selected Mode:（選択モード）",
            value: normalizedSelectedMode,
            testId: "selected-mode",
        },
        {
            label: "Execution Mode:（実行モード）",
            value: displayValue(executionMode),
            testId: "execution-mode",
        },
        {
            label: "Real Orders:（実注文）",
            value: realOrderAllowed ? "ENABLED" : "DISABLED",
            testId: "real-orders",
        },
        {
            label: "Reason:（安全理由）",
            value: displayedReason,
            testId: "safety-reason",
        },
        {
            label: "Paper Balance:（模擬残高）",
            value: displayValue(paperBalance, formatAmount),
            testId: "paper-balance",
        },
        {
            label: "Paper Equity:（模擬純資産）",
            value: displayValue(paperEquity, formatAmount),
            testId: "paper-equity",
        },
        {
            label: "Paper Available Balance:（模擬利用可能残高）",
            value: displayValue(paperAvailableBalance, formatAmount),
        },
        {
            label: "Paper Position:（模擬ポジション）",
            value: displayValue(paperPosition),
            testId: "paper-position",
        },
        {
            label: "Paper PnL:（模擬損益）",
            value: displayValue(paperPnl, formatPnl),
            testId: "paper-pnl",
        },
        {
            label: "Source:（データソース）",
            value: displayValue(accountSource),
            testId: "account-source",
        },
        {
            label: "Real Balance:（実残高）",
            value: realAccountConnected
                ? displayValue(realBalance, formatAmount)
                : "NOT CONNECTED",
            testId: "real-balance",
        },
        {
            label: "Real Position:（実ポジション）",
            value: realAccountConnected
                ? displayValue(realPosition)
                : "NOT CONNECTED",
            testId: "real-position",
        },
        {
            label: "Exchange Auth:（取引所認証）",
            value: displayValue(exchangeAuth),
            testId: "exchange-auth",
        },
        {
            label: "realOrderAllowed",
            value: String(realOrderAllowed === true),
            testId: "real-order-allowed",
        },
        {
            label: "dryRun",
            value: String(dryRun !== false),
            testId: "dry-run",
        },
        {
            label: "LAST UPDATE（最終更新）",
            value: displayValue(lastUpdate, formatLastUpdate),
        },
    ];

    return (
        <section className="terminal-monitor-section exchange-live-panel">
            <div className="terminal-section-header">
                1 | ACCOUNT DATA SOURCES
            </div>

            <div className="exchange-live-grid">
                {items.map((item) => (
                    <div className="runtime-metric" key={item.label}>
                        <span className="runtime-metric-label">
                            {item.label}
                        </span>
                        <span
                            className="runtime-metric-value"
                            data-testid={item.testId}
                        >
                            {item.value}
                        </span>
                    </div>
                ))}
            </div>
        </section>
    );
}
