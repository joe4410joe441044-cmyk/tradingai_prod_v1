export default function MoneyManagementCardShell({
    children = null,
    className = "",
    dataNote = null,
    loading = false,
    title,
}) {
    const titles = {
        Runtime: "Runtime（実行状態）",
        Risk: "Risk（リスク）",
        Exposure: "Exposure（エクスポージャー）",
        Capital: "Capital（資産）",
        "Risk State": "Risk State（リスク状態）",
        Configuration: "Configuration（設定）",
        Recovery: "Recovery（回復判定）",
        Performance: "Performance（成績）",
        Statistics: "Statistics（統計）",
        Projection: "Projection（将来予測）",
        "Position Size": "Position Size（ポジションサイズ）",
        Simulation: "Simulation（シミュレーション）",
        "Runtime History": "Runtime History（実行履歴）",
    };
    return (
        <article className={`mi-panel mm-card ${className}`.trim()}>
            <h2 className="mi-panel__title">{titles[title] ?? title}</h2>
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
