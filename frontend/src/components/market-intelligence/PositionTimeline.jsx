import { buildReplayPositionTimelineModel } from "../../features/market-intelligence/replay/replayPositionTimelineModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";

export function PositionTimelineView({ model }) {
    return (
        <section aria-labelledby="mi-timeline-title" className="mi-timeline">
            <h2 id="mi-timeline-title">POSITION TIMELINE</h2>
            <div className="mi-timeline__track">
                {model.isEmpty ? <p>NO POSITION EVENTS（ポジションイベントなし）</p> : <ol>
                    {model.items.map((item) => <li aria-current={item === model.items.at(-1) ? "step" : undefined}
                        key={item.id}>
                        <strong>{item.phase} · {item.eventType}</strong>
                        <span>{item.timestamp}</span>
                        <dl>
                            <div><dt>Sequence</dt><dd>{item.sequence ?? "—"}</dd></div>
                            <div><dt>Side</dt><dd>{item.side}</dd></div>
                            <div><dt>Price</dt><dd>{item.price}</dd></div>
                            <div><dt>Quantity</dt><dd>{item.quantity}</dd></div>
                            <div><dt>Unrealized PnL</dt><dd>{item.unrealizedPnl}</dd></div>
                            <div><dt>Realized PnL</dt><dd>{item.realizedPnl}</dd></div>
                            <div><dt>Reason</dt><dd>{item.reason}</dd></div>
                            <div><dt>Data Quality</dt><dd>{item.dataQuality}</dd></div>
                        </dl>
                    </li>)}
                </ol>}
            </div>
        </section>
    );
}

export default function PositionTimeline() {
    const { replayEngine } = useMarketIntelligence();
    return <PositionTimelineView model={buildReplayPositionTimelineModel(replayEngine)} />;
}
