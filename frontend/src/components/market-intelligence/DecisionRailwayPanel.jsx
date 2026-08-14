const STATIONS = [
    "Market / Order Book",
    "Python Detectors",
    "Feature Builder",
    "Python Strategy",
    "Money Management",
    "Governance",
    "Execution",
];

export default function DecisionRailwayPanel() {
    return (
        <section aria-labelledby="mi-railway-panel-title" className="mi-panel mi-railway-panel">
            <h2 className="mi-panel__title" id="mi-railway-panel-title">
                TRADING DECISION RAILWAY
            </h2>

            <div className="mi-panel__content mi-railway-layout">
                <section aria-labelledby="mi-railway-title" className="mi-placeholder-card mi-railway">
                    <h3 id="mi-railway-title">Decision Railway</h3>
                    <p><strong>TRADING AI: OFF / NOT INSTALLED</strong></p>
                    <ol className="mi-railway__stations">
                        {STATIONS.map((station) => (
                            <li className="mi-railway__station" key={station}>
                                <span>{station}</span>
                                <strong>UNAVAILABLE</strong>
                            </li>
                        ))}
                    </ol>
                </section>

                <div className="mi-railway-details">
                    <section className="mi-placeholder-card">
                        <h3>Station Inspector</h3>
                        <p>No station selected.</p>
                    </section>
                    <section className="mi-placeholder-card">
                        <h3>Decision Summary</h3>
                        <p>No decision selected.</p>
                    </section>
                    <section className="mi-placeholder-card">
                        <h3>Execution Outcome</h3>
                        <p>Execution data unavailable.</p>
                    </section>
                </div>
            </div>
        </section>
    );
}
