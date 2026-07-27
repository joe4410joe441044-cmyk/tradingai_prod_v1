export default function MoneyManagementCardShell({
    children = null,
    className = "",
    dataNote = null,
    loading = false,
    title,
}) {
    return (
        <article className={`mi-panel mm-card ${className}`.trim()}>
            <h2 className="mi-panel__title">{title}</h2>
            <div
                className={[
                    "mi-panel__content",
                    "mm-card__body",
                    children && !loading
                        ? "mm-card__body--content"
                        : "",
                ].filter(Boolean).join(" ")}
            >
                {dataNote && (
                    <p className="mm-card__data-note">{dataNote}</p>
                )}
                {loading ? (
                    <p className="mm-card__placeholder">Loading</p>
                ) : children ?? (
                    <p className="mm-card__placeholder">Coming Soon</p>
                )}
            </div>
        </article>
    );
}
