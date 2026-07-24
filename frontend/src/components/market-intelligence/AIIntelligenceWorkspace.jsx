const skeletonRows = [
    ["Detector Summary", "AI Review"],
    ["Strategy", "Feature Snapshot"],
    ["Governance", "EXECUTION / POSITION"],
];
const priorityClass = (title) => title === "Feature Snapshot" ? " mi-ai-intelligence__section--muted"
    : ["AI Review", "EXECUTION / POSITION"].includes(title) ? " mi-ai-intelligence__section--priority" : "";

export default function AIIntelligenceWorkspace({ finalDecision }) {
    return (
        <section aria-labelledby="mi-ai-intelligence-title" className="mi-panel mi-ai-intelligence">
            <header className="mi-ai-intelligence__header">
                <h2 id="mi-ai-intelligence-title">AI INTELLIGENCE</h2>
                <p>Real-time Market Recognition &amp; AI Decision Engine</p>
            </header>
            <div className="mi-ai-intelligence__content">
                {finalDecision}
                <div className="mi-ai-intelligence__sections">
                    {skeletonRows.flat().map((title) => (
                        <section aria-label={title}
                            className={`mi-placeholder-card mi-ai-intelligence__section${priorityClass(title)}`} key={title}>
                            <h3>{title}</h3>
                        </section>
                    ))}
                </div>
            </div>
        </section>
    );
}
