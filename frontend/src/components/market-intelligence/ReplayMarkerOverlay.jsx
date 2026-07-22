const MarkerBadge = ({ marker, matchLabel }) => (
    <article className={`mi-marker-overlay__marker mi-marker-overlay__marker--${marker.type.toLowerCase()}`}>
        <header><strong>{marker.label}</strong><span>{marker.category}</span></header>
        <dl>
            <div><dt>Side</dt><dd>{marker.side}</dd></div>
            <div><dt>Price</dt><dd>{marker.price}</dd></div>
            <div><dt>Quantity</dt><dd>{marker.quantity}</dd></div>
            <div><dt>Timestamp</dt><dd>{marker.timestamp}</dd></div>
            <div><dt>Reason</dt><dd>{marker.reason}</dd></div>
            <div><dt>Match</dt><dd>{matchLabel}</dd></div>
            {marker.orderId !== "—" && <div><dt>Order ID</dt><dd>{marker.orderId}</dd></div>}
            {marker.reduceOnly && <div><dt>Reduce Only</dt><dd>TRUE</dd></div>}
            {marker.flatten && <div><dt>Flatten</dt><dd>TRUE</dd></div>}
            {marker.blocked && <div><dt>Blocked</dt><dd>TRUE</dd></div>}
            {marker.failed && <div><dt>Error</dt><dd>TRUE</dd></div>}
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
            ]} />
        </section>
    );
}
