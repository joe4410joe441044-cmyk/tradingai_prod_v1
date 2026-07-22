import { buildDecisionRailwayModel } from "../../features/market-intelligence/replay/decisionRailwayModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import { bilingual } from "./marketIntelligenceLabels.js";

const stationValue = (model, stationId, label) => model.stations.find(({ id }) => id === stationId)
    ?.secondaryValues.find((value) => value.label === label)?.value ?? "—";

export const DecisionFinalSummary = ({ model }) => {
    const hasDecision = model.hasData && !["—", "UNKNOWN"].includes(model.finalDecision.ai);
    return (
    <section aria-labelledby="mi-final-decision-title" className="mi-final-decision">
        <header>
            <div><h2 id="mi-final-decision-title">{bilingual("aiFinalDecision")}</h2></div>
            <strong>{model.finalDecision.ai}</strong>
        </header>
        {!hasDecision ? <p className="mi-final-decision__empty"><strong>UNKNOWN（未判定）</strong>
            <span>Decision is not available at the current cursor.（現在のカーソルでは判断情報がありません）</span></p> : <>
            <dl className="mi-decision-railway__final mi-decision-railway__final--primary">
                <div><dt>{bilingual("finalDirection")}</dt><dd>{model.finalDecision.ai}</dd></div>
                <div><dt>{bilingual("confidence")}</dt><dd>{stationValue(model, "ai-review", "Confidence")}</dd></div>
                <div><dt>{bilingual("reason")}</dt><dd>{model.stations.find(({ id }) => id === "ai-review")?.reason ?? "—"}</dd></div>
                <div><dt>{bilingual("governanceResult")}</dt><dd>{model.finalDecision.governance}</dd></div>
                <div><dt>{bilingual("executionResult")}</dt><dd>{model.finalDecision.execution}</dd></div>
            </dl>
            <details className="mi-advanced-disclosure"><summary>Decision Details（判断詳細）</summary>
                <dl className="mi-decision-railway__final">
                    <div><dt>{bilingual("strategyCandidate")}</dt><dd>{model.finalDecision.strategy}</dd></div>
                    <div><dt>{bilingual("aiReviewResult")}</dt><dd>{model.finalDecision.aiRelation}</dd></div>
                    <div><dt>{bilingual("dataQuality")}</dt><dd>{model.dataQuality}</dd></div>
                </dl>
            </details>
        </>}
    </section>
    );
};

export function DecisionRailwayView({ model, showSummary = true }) {
    return (
        <section aria-labelledby="mi-decision-railway-title" className="mi-decision-railway">
            <header className="mi-decision-railway__header">
                <div>
                    <h2 id="mi-decision-railway-title">{bilingual("decisionRailway")}</h2>
                    <p>Python Analysis → Strategy → AI Review → Governance → Execution</p>
                </div>
                <span className="mi-status-label">QUALITY {model.dataQuality}</span>
            </header>

            {showSummary && <dl className="mi-decision-railway__final">
                <div><dt>Strategy Candidate</dt><dd>{model.finalDecision.strategy}</dd></div>
                <div><dt>AI Final Decision</dt><dd>{model.finalDecision.ai}</dd></div>
                <div><dt>AI / Strategy</dt><dd>{model.finalDecision.aiRelation}</dd></div>
                <div><dt>Governance Result</dt><dd>{model.finalDecision.governance}</dd></div>
                <div><dt>Execution Result</dt><dd>{model.finalDecision.execution}</dd></div>
                <div><dt>Stations Reached</dt><dd>{model.summary.reachedStations} / {model.summary.totalStations}</dd></div>
            </dl>}

            {!model.hasData && (
                <p className="mi-decision-railway__empty">
                    Load a replay dataset to inspect the decision path.
                </p>
            )}

            {model.hasData && <div className="mi-decision-railway__track">
                {model.stations.map((station, index) => (
                    <div className="mi-decision-railway__segment" key={station.id}>
                        <article
                            aria-current={station.active ? "step" : undefined}
                            className={`mi-decision-railway__station mi-decision-railway__station--${station.status}`}
                        >
                            <header>
                                <span>{station.order}</span>
                                <div>
                                    <h3>{station.title}</h3>
                                    <p>{station.subtitle}</p>
                                </div>
                            </header>
                            <strong className="mi-decision-railway__status">{station.statusLabel}</strong>
                            <p className="mi-decision-railway__primary">{station.primaryValue}</p>
                            <details className="mi-decision-railway__station-details"><summary>Details（詳細）</summary><dl>
                                {station.secondaryValues.map((value) => (
                                    <div key={value.label}>
                                        <dt>{value.label}</dt>
                                        <dd>{value.value}</dd>
                                    </div>
                                ))}
                                <div><dt>Timestamp</dt><dd>{station.timestampLabel}</dd></div>
                                <div><dt>Event ID</dt><dd>{station.eventId}</dd></div>
                                <div><dt>Data Quality</dt><dd>{station.dataQuality}</dd></div>
                                {station.reason !== "—" && (
                                    <div><dt>Reason</dt><dd>{station.reason}</dd></div>
                                )}
                            </dl></details>
                        </article>
                        {index < model.stations.length - 1 && (
                            <span aria-hidden="true" className="mi-decision-railway__connector">→</span>
                        )}
                    </div>
                ))}
            </div>}
        </section>
    );
}

export function DecisionRailwaySummary() {
    const { replayEngine } = useMarketIntelligence();
    return <DecisionFinalSummary model={buildDecisionRailwayModel(replayEngine)} />;
}

export default function DecisionRailway({ showSummary = true }) {
    const { replayEngine } = useMarketIntelligence();
    return <DecisionRailwayView model={buildDecisionRailwayModel(replayEngine)} showSummary={showSummary} />;
}
