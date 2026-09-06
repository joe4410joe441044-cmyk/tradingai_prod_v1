export default function MarketIntelligenceWorkspace({ primaryLeft, primaryRight, secondary, investigation }) {
    return (
        <section aria-label="Market intelligence workspace" className="mi-workspace">
            <div className="mi-workspace__columns">
                <div className="mi-workspace__left">{primaryLeft}</div>
                <div className="mi-workspace__right">{primaryRight}</div>
            </div>
            <div className="mi-workspace__secondary">
                {secondary}
            </div>
            <div className="mi-workspace__investigation">
                {investigation}
            </div>
        </section>
    );
}
