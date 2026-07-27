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
            {text}
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
                        <span>{row.value.text}</span>
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
