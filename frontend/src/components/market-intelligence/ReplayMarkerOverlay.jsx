const MarkerBadge = ({ marker, matchLabel }) => (
    <article className={`mi-marker-overlay__marker mi-marker-overlay__marker--${marker.type.toLowerCase()}`}>
        <header><strong>{marker.label}</strong><span>{marker.category}</span></header>
        <dl>
            <div><dt>ID</dt><dd>{marker.id}</dd></div>
            <div><dt>Marker ID</dt><dd>{marker.markerId}</dd></div>
            <div><dt>Type</dt><dd>{marker.type}</dd></div>
            <div><dt>Side</dt><dd>{marker.side}</dd></div>
            <div><dt>Price</dt><dd>{marker.price}</dd></div>
            <div><dt>Quantity</dt><dd>{marker.quantity}</dd></div>
            <div><dt>Timestamp</dt><dd>{marker.timestamp}</dd></div>
            <div><dt>Sequence</dt><dd>{marker.sequence}</dd></div>
            <div><dt>Reason</dt><dd>{marker.reason}</dd></div>
            <div><dt>Order ID</dt><dd>{marker.orderId}</dd></div>
            <div><dt>Reduce Only</dt><dd>{marker.reduceOnly ? "TRUE" : "FALSE"}</dd></div>
            <div><dt>Flatten</dt><dd>{marker.flatten ? "TRUE" : "FALSE"}</dd></div>
            <div><dt>Blocked</dt><dd>{marker.blocked ? "TRUE" : "FALSE"}</dd></div>
            <div><dt>Failed</dt><dd>{marker.failed ? "TRUE" : "FALSE"}</dd></div>
            <div><dt>Source</dt><dd>{marker.source}</dd></div>
            <div><dt>Event Type</dt><dd>{marker.eventType}</dd></div>
            <div><dt>Data Quality</dt><dd>{marker.dataQuality}</dd></div>
            <div><dt>Event ID</dt><dd>{marker.eventId}</dd></div>
            <div><dt>Trade ID</dt><dd>{marker.tradeId}</dd></div>
            <div><dt>Decision ID</dt><dd>{marker.decisionId}</dd></div>
            <div><dt>Position ID</dt><dd>{marker.positionId}</dd></div>
            <div><dt>Station ID</dt><dd>{marker.stationId}</dd></div>
            <div><dt>Match</dt><dd>{matchLabel}</dd></div>
        </dl>
    </article>
);

const CompactMarkerBadge = ({ marker, matchLabel }) => (
    <span className={`mi-marker-overlay__compact mi-marker-overlay__marker--${marker.type.toLowerCase()}`}>
        <strong>{marker.label}</strong>
        <span>{marker.side} · {marker.price} · {marker.timestamp}</span>
        <small>{matchLabel}</small>
    </span>
);

export const PriceMarkerLayer = ({ model }) => (
    <section aria-labelledby="mi-price-marker-title" className="mi-marker-overlay__layer">
        <h4 id="mi-price-marker-title">Price Marker Overlay</h4>
        {model.priceMarkers.length === 0 ? <p>NO PRICE MARKERS</p> : (
            <div className="mi-marker-overlay__lane">
                {model.priceMarkers.map((marker) => <CompactMarkerBadge key={marker.displayKey} marker={marker}
                    matchLabel={marker.priceMatch ? "EXACT BOOK PRICE" : "UNMATCHED PRICE"} />)}
            </div>
        )}
    </section>
);

export const TimeMarkerLayer = ({ model }) => (
    <section aria-labelledby="mi-time-marker-title" className="mi-marker-overlay__layer">
        <h4 id="mi-time-marker-title">Time Marker Overlay</h4>
        {model.timeMarkers.length === 0 ? <p>NO TIME MARKERS</p> : (
            <div className="mi-marker-overlay__lane">
                {model.timeMarkers.map((marker) => <CompactMarkerBadge key={marker.displayKey} marker={marker}
                    matchLabel={marker.timeMatch ? "EXACT TRADE LINK" : "UNMATCHED TIME"} />)}
            </div>
        )}
    </section>
);

const SummaryFields = ({ fields }) => (
    <dl className="mi-marker-overlay__summary-fields">
        {fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
);

export default function ReplayMarkerOverlay({ model }) {
    const latest = model.latestMarker;
    return (
        <section aria-labelledby="mi-marker-overlay-title" className="mi-marker-overlay">
            <h3 id="mi-marker-overlay-title">Marker Summary</h3>
            <SummaryFields fields={[
                ["Visible Marker Count", model.counts.visible], ["Price Matched Count", model.counts.priceMatched],
                ["Time Matched Count", model.counts.timeMatched], ["Unmatched Count", model.counts.unmatched],
                ["Latest Marker Type", latest?.label ?? "—"], ["Latest Marker Timestamp", latest?.timestamp ?? "—"],
                ["Latest Marker Price", latest?.price ?? "—"], ["Latest Marker Reason", latest?.reason ?? "—"],
            ]} />
            <h4>Marker Type Counts</h4>
            <SummaryFields fields={Object.entries(model.counts.byType).map(([type, count]) => [type.replaceAll("_", " "), count])} />
            <h4>Formal Marker Summary</h4>
            <SummaryFields fields={[
                ["Total", model.summary.total], ["Buy", model.summary.buy], ["Sell", model.summary.sell],
                ["Entry", model.summary.entry], ["Exit", model.summary.exit],
                ["Reduce Only", model.summary.reduceOnly], ["Flatten", model.summary.flatten],
                ["Failed", model.summary.failed], ["Blocked", model.summary.blocked], ["Unknown", model.summary.unknown],
            ]} />
            <h4>Marker Details</h4>
            {model.detailMarkers.length === 0 ? <p>NONE</p> : <div className="mi-marker-overlay__lane">
                {model.detailMarkers.map((marker) => <MarkerBadge key={marker.displayKey} marker={marker}
                    matchLabel={marker.priceMatch || marker.timeMatch ? "MATCHED" : "UNMATCHED"} />)}
            </div>}
            <h4>Unmatched Markers</h4>
            {model.unmatchedMarkers.length === 0 ? <p>NONE</p> : <div className="mi-marker-overlay__lane">
                {model.unmatchedMarkers.map((marker) => <MarkerBadge key={marker.displayKey} marker={marker} matchLabel="UNMATCHED" />)}
            </div>}
            <h4>Marker Legend</h4>
            <dl className="mi-marker-overlay__legend">
                {model.legend.map((item) => <div key={item.type}><dt>{item.label}</dt><dd>{item.description}</dd></div>)}
            </dl>
            <h4>Marker Diagnostics</h4>
            <SummaryFields fields={[
                ["Source Marker Count", model.diagnostics.sourceMarkerCount],
                ["Displayed Marker Count", model.diagnostics.displayedMarkerCount],
                ["Invalid Marker Count", model.diagnostics.invalidMarkerCount],
                ["Missing Price Count", model.diagnostics.missingPriceCount],
                ["Missing Timestamp Count", model.diagnostics.missingTimestampCount],
                ["Unmatched Price Count", model.diagnostics.unmatchedPriceCount],
                ["Unmatched Time Count", model.diagnostics.unmatchedTimeCount],
                ["Truncated Marker Count", model.diagnostics.truncatedMarkerCount],
                ["Unknown Type Count", model.diagnostics.unknownTypeCount],
                ...Object.entries(model.diagnostics.byQuality).map(([quality, count]) => [`${quality} Quality Count`, count]),
            ]} />
        </section>
    );
}
