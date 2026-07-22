import { buildReplayInspectorModel } from "../../features/market-intelligence/replay/replayInspectorModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import { bilingual } from "./marketIntelligenceLabels.js";

const FieldGrid = ({ fields }) => (
    <dl className="mi-replay-inspector__fields">
        {fields.map((item) => (
            <div className={item.isMissing ? "mi-replay-inspector__field--missing" : undefined} key={item.id}>
                <dt>{item.label}</dt>
                <dd>{item.displayValue}</dd>
            </div>
        ))}
    </dl>
);

const AdjacentEvent = ({ label, event }) => (
    <article className="mi-replay-inspector__adjacent">
        <h4>{label}</h4>
        {event ? (
            <dl>
                <div><dt>Type</dt><dd>{event.type}</dd></div>
                <div><dt>Timestamp</dt><dd>{event.timestamp}</dd></div>
                <div><dt>Sequence</dt><dd>{event.sequence}</dd></div>
                <div><dt>Event ID</dt><dd>{event.id}</dd></div>
            </dl>
        ) : <p>—</p>}
    </article>
);

const ValidationList = ({ count, fields, label }) => (
    <div className="mi-replay-inspector__validation">
        <h4>{label}</h4>
        {count === 0 ? <p>NONE</p> : <FieldGrid fields={fields} />}
        {count > fields.length && <p>{count - fields.length} additional items</p>}
    </div>
);

const displayField = (fields, label) => fields.find((item) => item.label === label)?.displayValue ?? "—";

export function ReplayInspectorView({ model }) {
    return (
        <section aria-labelledby="mi-replay-inspector-title" className="mi-replay-inspector">
            <header className="mi-replay-inspector__header">
                <div>
                    <h2 id="mi-replay-inspector-title">{bilingual("replayInspector")}</h2>
                </div>
                <span className="mi-status-label">
                    {model.currentEvent.event?.type ?? "NO CURRENT EVENT"}
                </span>
            </header>

            {model.isEmpty && (
                <div className="mi-replay-inspector__empty">
                    <strong>NO CURRENT EVENT（現在イベントなし）</strong>
                </div>
            )}

            {!model.isEmpty && <dl className="mi-replay-inspector__summary">
                <div><dt>{bilingual("currentEvent")}</dt><dd>{displayField(model.currentEvent.fields, "Event ID")}</dd></div>
                <div><dt>{bilingual("eventType")}</dt><dd>{displayField(model.currentEvent.fields, "Event Type")}</dd></div>
                <div><dt>{bilingual("timestamp")}</dt><dd>{displayField(model.currentEvent.fields, "Timestamp")}</dd></div>
                <div><dt>{bilingual("sequence")}</dt><dd>{displayField(model.currentEvent.fields, "Sequence")}</dd></div>
                <div><dt>Final Decision（最終判断）</dt><dd>{displayField(model.decision.layers[1]?.fields ?? [], "Final Direction")}</dd></div>
                <div><dt>Execution Outcome（実行結果）</dt><dd>{displayField(model.decision.layers[3]?.fields ?? [], "Status")}</dd></div>
            </dl>}

            {model.dataQuality.validationErrorCount > 0 && (
                <p className="mi-replay-inspector__critical" role="alert">
                    Validation errors: {model.dataQuality.validationErrorCount}. Open Inspector Details for the validated messages.
                </p>
            )}

            {!model.isEmpty && <details className="mi-advanced-disclosure mi-replay-inspector__details">
                <summary>Replay Inspector Details（リプレイ詳細情報）</summary>
                <div className="mi-replay-inspector__sections">
                <section aria-labelledby="mi-inspector-replay">
                    <h3 id="mi-inspector-replay">Replay Context</h3>
                    <FieldGrid fields={model.replay} />
                </section>

                <section aria-labelledby="mi-inspector-current">
                    <h3 id="mi-inspector-current">Current Event</h3>
                    <FieldGrid fields={model.currentEvent.fields} />
                    {model.currentEvent.payloadPreview.length > 0 && (
                        <div className="mi-replay-inspector__preview">
                            <h4>Payload Preview</h4>
                            <FieldGrid fields={model.currentEvent.payloadPreview} />
                        </div>
                    )}
                </section>

                <section aria-labelledby="mi-inspector-adjacent">
                    <h3 id="mi-inspector-adjacent">Adjacent Events</h3>
                    <div className="mi-replay-inspector__adjacent-grid">
                        <AdjacentEvent event={model.adjacentEvents.previous} label="Previous Event" />
                        <AdjacentEvent event={model.adjacentEvents.current} label="Current Event" />
                        <AdjacentEvent event={model.adjacentEvents.next} label="Next Event" />
                    </div>
                </section>

                <section aria-labelledby="mi-inspector-decision">
                    <h3 id="mi-inspector-decision">Decision Context</h3>
                    <div className="mi-replay-inspector__layers">
                        {model.decision.layers.map((layer) => (
                            <article key={layer.id}>
                                <h4>{layer.title}</h4>
                                <strong>{layer.status}</strong>
                                <FieldGrid fields={layer.fields} />
                            </article>
                        ))}
                    </div>
                </section>

                <section aria-labelledby="mi-inspector-position">
                    <h3 id="mi-inspector-position">Position Context</h3>
                    <p className="mi-replay-inspector__section-status">{model.position.status}</p>
                    <FieldGrid fields={model.position.fields} />
                </section>

                <section aria-labelledby="mi-inspector-markers">
                    <h3 id="mi-inspector-markers">Marker Context</h3>
                    <p className="mi-replay-inspector__section-status">
                        {model.markers.count === 0 ? "NO MARKERS" : `${model.markers.count} MARKERS · LATEST ${model.markers.latestMarkerId}`}
                    </p>
                    <div className="mi-replay-inspector__collection">
                        {model.markers.items.map((marker) => (
                            <article key={marker.id}><FieldGrid fields={marker.fields} /></article>
                        ))}
                    </div>
                </section>

                <section aria-labelledby="mi-inspector-stations">
                    <h3 id="mi-inspector-stations">Station Context</h3>
                    <div className="mi-replay-inspector__collection">
                        {model.stations.map((station) => (
                            <article key={station.id}>
                                <h4>{station.title}</h4>
                                <strong>{station.status}</strong>
                                <FieldGrid fields={[
                                    { id: "timestamp", label: "Timestamp", displayValue: station.timestamp, isMissing: station.timestamp === "—" },
                                    { id: "primary", label: "Primary Value", displayValue: station.primaryValue, isMissing: station.primaryValue === "—" },
                                    { id: "reason", label: "Reason", displayValue: station.reason, isMissing: station.reason === "—" },
                                    { id: "quality", label: "Data Quality", displayValue: station.dataQuality, isMissing: false },
                                    { id: "event", label: "Event ID", displayValue: station.eventId, isMissing: station.eventId === "—" },
                                ]} />
                            </article>
                        ))}
                    </div>
                </section>

                <section aria-labelledby="mi-inspector-quality">
                    <h3 id="mi-inspector-quality">Data Quality</h3>
                    <FieldGrid fields={[
                        { id: "projection", label: "Projection Data Quality", displayValue: model.dataQuality.projection, isMissing: false },
                        { id: "validation", label: "Dataset Validation", displayValue: model.dataQuality.datasetValidation, isMissing: false },
                        { id: "event", label: "Event Data Quality", displayValue: model.dataQuality.event, isMissing: false },
                        { id: "position", label: "Position Data Quality", displayValue: model.dataQuality.position, isMissing: false },
                        { id: "decision", label: "Decision Data Quality", displayValue: model.dataQuality.decision, isMissing: false },
                        { id: "marker", label: "Marker Data Quality", displayValue: model.dataQuality.marker, isMissing: false },
                        { id: "station", label: "Station Data Quality", displayValue: model.dataQuality.station, isMissing: false },
                        { id: "errors", label: "Validation Errors", displayValue: `${model.dataQuality.validationErrorCount} items`, isMissing: false },
                        { id: "warnings", label: "Validation Warnings", displayValue: `${model.dataQuality.validationWarningCount} items`, isMissing: false },
                    ]} />
                    <div className="mi-replay-inspector__validation-grid">
                        <ValidationList count={model.dataQuality.validationErrorCount}
                            fields={model.dataQuality.validationErrors} label="Validation Errors" />
                        <ValidationList count={model.dataQuality.validationWarningCount}
                            fields={model.dataQuality.validationWarnings} label="Validation Warnings" />
                    </div>
                    <h3 className="mi-replay-inspector__diagnostics-title">Diagnostics</h3>
                    <div aria-live="polite" className="mi-replay-inspector__diagnostics">
                        <FieldGrid fields={model.diagnostics} />
                    </div>
                </section>
                </div>
            </details>}
        </section>
    );
}

export default function ReplayInspector() {
    const { replayEngine } = useMarketIntelligence();
    return <ReplayInspectorView model={buildReplayInspectorModel(replayEngine)} />;
}
