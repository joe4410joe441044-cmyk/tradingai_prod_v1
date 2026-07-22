const REPLAY_AREAS = [
    ["Order Book Replay", "Order book snapshot unavailable."],
    ["Recent Trades Replay", "Recent trades snapshot unavailable."],
    ["Market Event Summary", "No replay selected."],
    ["Replay Controller", "Replay controls are unavailable until a position is selected."],
];

export default function MarketReplayPanel() {
    return (
        <section aria-labelledby="mi-replay-title" className="mi-panel mi-replay-panel">
            <h2 className="mi-panel__title" id="mi-replay-title">MARKET REPLAY</h2>

            <div className="mi-panel__content mi-replay-grid">
                {REPLAY_AREAS.map(([title, message]) => (
                    <section className="mi-placeholder-card" key={title}>
                        <h3>{title}</h3>
                        <p>{message}</p>
                    </section>
                ))}
            </div>
        </section>
    );
}
