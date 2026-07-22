import { buildReplayTimelineModel } from "../../features/market-intelligence/replay/replayTimelineModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import { bilingual } from "./marketIntelligenceLabels.js";

export function ReplayTimelineView({ model }) {
    const summary = model.summary;
    return (
        <section aria-labelledby="mi-replay-timeline-title" className="mi-replay-timeline">
            <header className="mi-replay-timeline__header">
                <div>
                    <h2 id="mi-replay-timeline-title">{bilingual("replayTimeline")}</h2>
                </div>
                <span className="mi-status-label">QUALITY {model.dataQuality}</span>
            </header>

            {!model.isEmpty && <dl className="mi-replay-timeline__summary">
                <div><dt>Total（総イベント数）</dt><dd>{summary.totalEvents}</dd></div>
                <div><dt>Reached（到達イベント）</dt><dd>{summary.reachedCount}</dd></div>
                <div><dt>Past（過去イベント）</dt><dd>{summary.pastCount}</dd></div>
                <div><dt>Future（未来イベント）</dt><dd>{summary.futureCount}</dd></div>
                <div><dt>{bilingual("currentEvent")}</dt><dd>{summary.currentEvent}</dd></div>
                <div><dt>Cursor（カーソル）</dt><dd>{summary.replayCursor}</dd></div>
            </dl>}

            {model.isEmpty ? (
                <div className="mi-replay-timeline__empty">
                    <strong>NO TIMELINE EVENTS（タイムラインイベントなし）</strong>
                </div>
            ) : (
                <div className="mi-replay-timeline__body">
                    {model.groups.map((group, groupIndex) => (
                        <section
                            aria-labelledby={`mi-replay-group-${groupIndex}`}
                            className={`mi-replay-timeline__group mi-replay-timeline__group--${group.groupStatus}`}
                            key={group.id}
                        >
                            <header className="mi-replay-timeline__group-header">
                                <h3 id={`mi-replay-group-${groupIndex}`}>{group.timestampLabel}</h3>
                                <span>{group.groupStatus.toUpperCase()} · {group.itemCount} EVENT{group.itemCount === 1 ? "" : "S"}</span>
                            </header>
                            <ol className="mi-replay-timeline__items">
                                {group.items.map((item) => (
                                    <li
                                        aria-current={item.status === "current" ? "step" : undefined}
                                        className={`mi-replay-timeline__item mi-replay-timeline__item--${item.status}`}
                                        key={item.id}
                                    >
                                        <span className="mi-replay-timeline__status">
                                            {item.statusLabel}
                                        </span>
                                        <div className="mi-replay-timeline__event">
                                            <strong>{item.eventType}</strong>
                                            <span>{item.timestampLabel}</span>
                                        </div>
                                        <dl className="mi-replay-timeline__metadata">
                                            <div><dt>{bilingual("sequence")}</dt><dd>{item.sequenceLabel}</dd></div>
                                            <div><dt>Event ID（イベントID）</dt><dd>{item.eventId}</dd></div>
                                            <div><dt>{bilingual("source")}</dt><dd>{item.source}</dd></div>
                                            <div><dt>{bilingual("dataQuality")}</dt><dd>{item.dataQuality}</dd></div>
                                        </dl>
                                    </li>
                                ))}
                            </ol>
                        </section>
                    ))}
                </div>
            )}
        </section>
    );
}

export default function ReplayTimeline() {
    const { replayEngine } = useMarketIntelligence();
    return <ReplayTimelineView model={buildReplayTimelineModel(replayEngine)} />;
}
