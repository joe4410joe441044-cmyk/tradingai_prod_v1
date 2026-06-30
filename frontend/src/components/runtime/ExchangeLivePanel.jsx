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
    mode,
    balance,
    equity,
    availableBalance,
    position,
    pnl,
    lastUpdate,
}) {
    const items = [
        { label: "EXCHANGE（取引所）", value: displayValue(exchange) },
        { label: "CONNECTION（接続）", value: displayValue(connection) },
        { label: "MODE（モード）", value: displayValue(mode) },
        { label: "BALANCE（残高）", value: displayValue(balance, formatAmount) },
        { label: "EQUITY（純資産）", value: displayValue(equity, formatAmount) },
        {
            label: "AVAILABLE BALANCE（利用可能残高）",
            value: displayValue(availableBalance, formatAmount),
        },
        { label: "POSITION（ポジション）", value: displayValue(position) },
        { label: "PNL（損益）", value: displayValue(pnl, formatPnl) },
        {
            label: "LAST UPDATE（最終更新）",
            value: displayValue(lastUpdate, formatLastUpdate),
        },
    ];

    return (
        <section className="terminal-monitor-section exchange-live-panel">
            <div className="terminal-section-header">
                1 | EXCHANGE LIVE
            </div>

            <div className="exchange-live-grid">
                {items.map((item) => (
                    <div className="runtime-metric" key={item.label}>
                        <span className="runtime-metric-label">
                            {item.label}
                        </span>
                        <span className="runtime-metric-value">
                            {item.value}
                        </span>
                    </div>
                ))}
            </div>
        </section>
    );
}
