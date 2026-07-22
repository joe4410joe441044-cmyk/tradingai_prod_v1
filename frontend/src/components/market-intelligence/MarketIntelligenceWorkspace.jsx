export default function MarketIntelligenceWorkspace({ leftPanel, rightPanel }) {
    return (
        <section aria-label="Market intelligence workspace" className="mi-workspace">
            {leftPanel}
            {rightPanel}
        </section>
    );
}
