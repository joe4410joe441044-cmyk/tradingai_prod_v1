export default function MarketIntelligenceWorkspace({ bottomPanel, leftPanel, rightPanel }) {
    return (
        <section aria-label="Market intelligence workspace" className="mi-workspace">
            <div className="mi-workspace__columns">
                <div className="mi-workspace__left">{leftPanel}</div>
                <div className="mi-workspace__right">{rightPanel}</div>
            </div>
            <section aria-labelledby="mi-replay-workspace-title" className="mi-replay-workspace">
                <h2 className="mi-visually-hidden" id="mi-replay-workspace-title">REPLAY WORKSPACE</h2>
                {bottomPanel}
            </section>
        </section>
    );
}
