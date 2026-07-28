const OPERATIONAL_TEXT = Object.freeze({
    ACTIVE: "ACTIVE（稼働中）",
    AVAILABLE: "AVAILABLE（利用可能）",
    "ENTRY BLOCKED": "ENTRY BLOCKED（新規エントリー禁止）",
    "ENTRY ALLOWED": "ENTRY ALLOWED（新規エントリー許可）",
    "FAIL CLOSED": "FAIL CLOSED（安全停止）",
    READY: "READY（準備完了）",
    RUNNING: "RUNNING（稼働中）",
    UNAVAILABLE: "UNAVAILABLE（利用不可）",
    UNKNOWN: "UNKNOWN（不明）",
    "UNKNOWN MODE": "UNKNOWN MODE（モード不明）",
});

export function formatMoneyManagementOperationalText(text) {
    return OPERATIONAL_TEXT[text] ?? text;
}

export function MoneyManagementStatusBadge({
    text,
    variant = "muted",
}) {
    return (
        <span
            className={[
                "mi-status-label",
                "mm-status-badge",
                `mm-status-badge--${variant}`,
            ].join(" ")}
        >
            {formatMoneyManagementOperationalText(text)}
        </span>
    );
}

export function MoneyManagementMetricRows({
    rows,
}) {
    return (
        <dl className="mm-metric-list">
            {rows.map((row) => (
                <div className="mm-metric-row" key={row.label}>
                    <dt>{row.label}</dt>
                    <dd
                        className={[
                            row.value.unavailable
                                ? "mm-value--unavailable"
                                : "",
                            row.variant
                                ? `mm-value--${row.variant}`
                                : "",
                        ].filter(Boolean).join(" ")}
                    >
                        <span>
                            {formatMoneyManagementOperationalText(
                                row.value.text,
                            )}
                        </span>
                        {row.value.unit && (
                            <small>{row.value.unit}</small>
                        )}
                    </dd>
                </div>
            ))}
        </dl>
    );
}

export function MoneyManagementReasonList({
    group,
    title,
}) {
    const items = !group.available
        ? ["Reason data unavailable"]
        : group.items.length > 0
            ? group.items
            : [group.emptyLabel];
    return (
        <section className="mm-reason-group">
            <h3>{title}</h3>
            <ul>
                {items.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                ))}
            </ul>
        </section>
    );
}
