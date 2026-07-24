import { useState } from "react";

import { buildOrderBookDomDisplay, buildRecentTradesDisplay, buildReplayMarketViewModel, formatMarketPrice, formatMarketQuantity, marketTimestamp } from "../../features/market-intelligence/replay/replayMarketViewModel.js";
import { buildReplayMarkerOverlayModel, reconcileMarkerUiSelection, resolveSelectedMarker } from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";
import { normalizeReplayMarketModel } from "../../features/market-intelligence/market/replayMarketAdapter.js";
import { createDashboardContextMarketModel, isReplayMarketContextActive } from "../../features/market-intelligence/market/marketContextSelection.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import ReplayMarkerOverlay from "./ReplayMarkerOverlay.jsx";
import { bilingual } from "./marketIntelligenceLabels.js";

const FieldGrid = ({ fields }) => (
    <dl className="mi-market-view__fields">
        {fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
);

const present = (value) => value !== null && value !== undefined && value !== "—" && value !== "";
const booleanValue = (value) => value === true ? "YES" : value === false ? "NO" : "—";

export const MarkerInspector = ({ marker, marketContext }) => {
    const required = marker ? [
        ["Marker Type", marker.label], ["Timestamp", marketTimestamp(marker.timestamp)],
        ["Price", formatMarketPrice(marker.numericPrice, marketContext)], ["Side", marker.side],
        ["Quantity", formatMarketQuantity(marker.numericQuantity, marketContext)],
        ["Source", marker.source], ["Data Quality", marker.dataQuality],
    ] : [];
    const optional = marker ? [
        ["Reason", marker.reason, "reason"], ["Order ID", marker.orderId, "id"],
        ["Event ID", marker.eventId, "id"], ["Trade ID", marker.tradeId, "id"],
        ["Decision ID", marker.decisionId, "id"], ["Position ID", marker.positionId, "id"],
        ["Sequence", marker.sequence], ["Reduce Only", booleanValue(marker.reduceOnly)],
        ["Flatten", booleanValue(marker.flatten)], ["Blocked", booleanValue(marker.blocked)],
        ["Failed", booleanValue(marker.failed)],
    ].filter(([, value]) => present(value)) : [];
    return <section aria-labelledby="mi-marker-inspector-title" className={`mi-marker-inspector${marker ? "" : " mi-marker-inspector--empty"}`}>
        <header><h3 id="mi-marker-inspector-title">MARKER INSPECTOR</h3>
            {marker && <strong>{marker.label}</strong>}</header>
        {!marker ? <div className="mi-marker-inspector__empty"><strong>SELECT A MARKER</strong>
            <span>Select a marker in DOM or Recent Trades to inspect its details.</span></div>
            : <dl className="mi-marker-inspector__fields">{[...required, ...optional].map(([label, value, kind]) => (
                <div className={kind ? `mi-marker-inspector__field--${kind}` : undefined} key={label}>
                    <dt>{label}</dt><dd title={kind ? String(value) : undefined}>{present(value) ? value : "—"}</dd>
                </div>
            ))}</dl>}
    </section>;
};

const MarkerStack = ({ allMarkers, expanded = false, groupKey, onSelectMarker, onToggle,
    selectedMarkerId, visibleMarkers, remainingCount = 0 }) => {
    const markers = expanded ? allMarkers : visibleMarkers;
    return <span className={`mi-marker-stack${expanded ? " mi-marker-stack--expanded" : ""}`}>
        {markers.map((marker) => <button aria-label={marker.accessibilityLabel}
            aria-pressed={selectedMarkerId === marker.id} className="mi-order-book__marker"
            key={marker.displayKey} onClick={() => onSelectMarker(marker.id)} title={marker.accessibilityLabel}
            type="button">{marker.shortLabel}</button>)}
        {remainingCount > 0 && <button aria-expanded={expanded}
            aria-label={expanded ? `Close ${remainingCount} additional markers at ${groupKey}`
                : `Show ${remainingCount} additional markers at ${groupKey}`}
            className="mi-marker-stack__more" onClick={() => onToggle(groupKey)}
            title={expanded ? "Close marker list" : `Show ${remainingCount} more markers`} type="button">
            {expanded ? "CLOSE" : `+${remainingCount}`}
        </button>}
    </span>;
};

const BookTable = ({ expandedMarkerGroupKey, label, markerModel, onMarkerGroupToggle, onMarkerSelect,
    rows, selectedMarkerId }) => (
    <div className={`mi-market-view__book-side mi-market-view__book-side--${label.toLowerCase()}`}>
        <h4>{label} LEVELS（{label === "ASK" ? "売板" : "買板"}）</h4>
        <div className="mi-market-view__table-wrap">
            <table>
                <thead><tr><th>{bilingual("price")}</th><th>{bilingual("size")}</th><th>{bilingual("total")}</th><th>{bilingual("marker")}</th></tr></thead>
                <tbody>{rows.map((row) => {
                    const group = markerModel.domMarkerGroups.find(({ price }) => price === row.numericPrice);
                    return (
                        <tr key={row.id}>
                            <td className="mi-order-book__price"><span aria-hidden="true" className="mi-order-book__depth"
                                style={{ width: `${row.depthPercent}%` }} /><span>{row.price} <small>{row.side}</small></span></td>
                            <td>{row.size}</td><td>{row.cumulativeSize}</td>
                            <td className="mi-order-book__marker-slot">
                                {!group ? "—" : <MarkerStack allMarkers={group.markers}
                                    expanded={expandedMarkerGroupKey === `dom:${group.price}`} groupKey={`dom:${group.price}`}
                                    onSelectMarker={onMarkerSelect} onToggle={onMarkerGroupToggle}
                                    remainingCount={group.remainingCount} selectedMarkerId={selectedMarkerId}
                                    visibleMarkers={group.visibleMarkers} />}
                            </td>
                        </tr>
                    );
                })}</tbody>
            </table>
        </div>
    </div>
);

const SourceBadge = ({ marketContext }) => <div className="mi-market-source" aria-label="Panel market identity">
    <span><strong>{marketContext.exchange}</strong> / <strong>{marketContext.displaySymbol}</strong></span>
</div>;

export const CurrentPriceSummary = ({ summary }) => (
    <section aria-label="Current Price Summary" className="mi-current-price-summary">
        <div className="mi-current-price-summary__identity">
            <span>{summary.exchange} · {summary.marketType}</span>
            <strong>{summary.displaySymbol}</strong>
        </div>
        <div className="mi-current-price-summary__price">
            <span>CURRENT PRICE</span><strong>{summary.currentPrice}</strong>
        </div>
        <dl className="mi-current-price-summary__quotes">
            <div><dt>BEST BID</dt><dd>{summary.bestBid}</dd></div>
            <div><dt>BEST ASK</dt><dd>{summary.bestAsk}</dd></div>
            <div><dt>SPREAD</dt><dd>{summary.spread}</dd></div>
        </dl>
        <span aria-label={`Market data state: ${summary.state}`}
            className={`mi-current-price-summary__state mi-current-price-summary__state--${summary.state.toLowerCase().replaceAll(" ", "-")}`}>
            {summary.state}
        </span>
    </section>
);

export function ReplayMarketViewContent({
    model,
    markerModel = buildReplayMarkerOverlayModel(null, model),
    displayMode = "BOTH",
    rowLimit = 20,
    tradeRowLimit = 20,
    expandedMarkerGroupKey = null,
    onMarkerGroupToggle = () => {},
    onMarkerSelect = () => {},
    selectedMarkerId = null,
    onDisplayModeChange = () => {},
    onRowLimitChange = () => {},
    onTradeRowLimitChange = () => {},
}) {
    const dom = buildOrderBookDomDisplay(model.orderBook, displayMode, rowLimit);
    const trades = buildRecentTradesDisplay(model.recentTrades, model.currentTradeIdentity, markerModel.markers, tradeRowLimit);
    const ratio = dom.buyRatio === null ? { buy: "—", sell: "—" }
        : { buy: `${dom.buyRatio.toFixed(1)}%`, sell: `${dom.sellRatio.toFixed(1)}%` };
    return (
        <section aria-labelledby="mi-market-view-title" className={`mi-market-view${model.isEmpty ? " mi-market-view--empty" : ""}`}>
            <section aria-label="Market summary" className="mi-market-view__market-header">
                <div className="mi-market-view__heading">
                    <h2 id="mi-market-view-title">MARKET VIEW</h2>
                </div>
                <CurrentPriceSummary summary={model.currentPriceSummary} />
            </section>
            <div className="mi-market-view__body">
                <section aria-labelledby="mi-market-book-title" className="mi-market-view__card">
                    <h3 id="mi-market-book-title">{bilingual("orderBook")}</h3>
                    {!model.isEmpty && <SourceBadge marketContext={model.marketContext} />}
                    {model.orderBook.hasData && model.orderBook.state !== "UNAVAILABLE" && <div className="mi-order-book__toolbar">
                        <div aria-label="Order book display mode" className="mi-order-book__modes">
                            {["BOTH", "BIDS", "ASKS"].map((mode) => <button aria-pressed={dom.mode === mode}
                                key={mode} onClick={() => onDisplayModeChange(mode)} type="button">{mode}</button>)}
                        </div>
                        <label>ROWS（行数） <select aria-label="Displayed order book rows" onChange={(event) => onRowLimitChange(Number(event.target.value))}
                            value={dom.rowLimit}>{[10, 20, 50].map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
                    </div>}
                    {model.orderBook.state === "NO MARKET SELECTED" ? (
                        <div className="mi-market-view__empty"><strong>NO MARKET SELECTED</strong></div>
                    ) : model.orderBook.state === "LOADING" ? (
                        <div className="mi-market-view__empty"><strong>LOADING MARKET DATA</strong></div>
                    ) : model.orderBook.state === "UNAVAILABLE" ? (
                        <div className="mi-market-view__empty"><strong>ORDER BOOK UNAVAILABLE</strong></div>
                    ) : model.orderBook.state === "WAITING" ? (
                        <div className="mi-market-view__empty"><strong>WAITING FOR MARKET DATA</strong></div>
                    ) : <>
                        {displayMode !== "BIDS" && (dom.asks.length > 0
                            ? <BookTable expandedMarkerGroupKey={expandedMarkerGroupKey} label="ASK" markerModel={markerModel}
                                onMarkerGroupToggle={onMarkerGroupToggle} onMarkerSelect={onMarkerSelect}
                                rows={dom.asks} selectedMarkerId={selectedMarkerId} />
                            : <p className="mi-market-view__empty">NO ASK DATA</p>)}
                        <div className="mi-order-book__current">
                            <span>CURRENT PRICE · {model.header.currentPriceSource}</span>
                            <strong>{model.header.currentPrice}</strong>
                            <span>{model.header.priceDirection}</span>
                            <small>SPREAD {model.orderBook.spread}</small>
                        </div>
                        {displayMode !== "ASKS" && (dom.bids.length > 0
                            ? <BookTable expandedMarkerGroupKey={expandedMarkerGroupKey} label="BID" markerModel={markerModel}
                                onMarkerGroupToggle={onMarkerGroupToggle} onMarkerSelect={onMarkerSelect}
                                rows={dom.bids} selectedMarkerId={selectedMarkerId} />
                            : <p className="mi-market-view__empty">NO BID DATA</p>)}
                        <div className="mi-order-book__ratio" aria-label="Visible depth ratio">
                            <span>VISIBLE DEPTH RATIO</span><strong>BUY {ratio.buy}</strong><strong>SELL {ratio.sell}</strong>
                        </div>
                    </>}
                    {!model.isEmpty && <><h4>Book Summary</h4>
                        <FieldGrid fields={[
                            ["Best Ask", model.orderBook.bestAsk], ["Best Bid", model.orderBook.bestBid],
                            ["Spread", model.orderBook.spread], ["Spread %", model.orderBook.spreadPct],
                            ["Midpoint", model.orderBook.midpoint], ["Book Imbalance", model.orderBook.imbalance],
                        ]} /></>}
                </section>
                <section aria-labelledby="mi-market-trades-title" className="mi-market-view__card">
                    <h3 id="mi-market-trades-title">{bilingual("recentTrades")}</h3>
                    {model.marketContext.key && <SourceBadge marketContext={model.marketContext} />}
                    {model.recentTrades.hasData && <div className="mi-recent-trades__toolbar"><label>ROWS（行数） <select aria-label="Displayed recent trade rows"
                        onChange={(event) => onTradeRowLimitChange(Number(event.target.value))} value={trades.rowLimit}>
                        {[10, 20, 50].map((count) => <option key={count} value={count}>{count}</option>)}</select></label></div>}
                    {model.recentTrades.state === "NO MARKET SELECTED" ? (
                        <div className="mi-market-view__empty"><strong>NO MARKET SELECTED</strong></div>
                    ) : model.recentTrades.state === "LOADING" ? (
                        <div className="mi-market-view__empty"><strong>LOADING TRADE DATA</strong></div>
                    ) : model.recentTrades.state === "UNAVAILABLE" ? (
                        <div className="mi-market-view__empty"><strong>TRADE DATA UNAVAILABLE</strong></div>
                    ) : model.recentTrades.state === "NO TRADES" ? (
                        <div className="mi-market-view__empty"><strong>NO TRADES</strong></div>
                    ) : model.recentTrades.state === "WAITING" ? (
                        <div className="mi-market-view__empty"><strong>WAITING FOR TRADE DATA</strong></div>
                    ) : <div className="mi-market-view__table-wrap"><table>
                        <thead><tr><th>TIME</th><th>PRICE</th><th>SIZE</th><th>SIDE</th><th>MARKER</th></tr></thead>
                        <tbody>{trades.rows.map((trade) => (
                            <tr key={`${trade.id}-${trade.inputIndex}`} aria-label={trade.isCurrent ? "Current trade" : undefined}
                                className={`mi-market-view__trade--${trade.side.toLowerCase()}${trade.isCurrent ? " mi-market-view__trade--current" : ""}`}>
                                <td>{trade.time}</td><td>{trade.price}</td><td className="mi-recent-trades__size"><span aria-hidden="true"
                                    className="mi-recent-trades__intensity" style={{ width: `${trade.intensity}%` }} /><span>{trade.size}</span></td>
                                <td>{trade.side}{trade.isCurrent && <small>CURRENT</small>}</td>
                                <td>{trade.markers.length ? <MarkerStack allMarkers={trade.markers}
                                    expanded={expandedMarkerGroupKey === `trade:${trade.id}`} groupKey={`trade:${trade.id}`}
                                    onSelectMarker={onMarkerSelect} onToggle={onMarkerGroupToggle}
                                    remainingCount={Math.max(0, trade.markers.length - 3)} selectedMarkerId={selectedMarkerId}
                                    visibleMarkers={trade.markers.slice(0, 3)} /> : "—"}</td>
                            </tr>
                        ))}</tbody>
                    </table></div>}
                    {model.recentTrades.hasData && <><h4>Trade Summary</h4>
                        <FieldGrid fields={[
                            ["Visible Trades", trades.count], ["BUY Count", trades.buyCount], ["SELL Count", trades.sellCount],
                            ["UNKNOWN Count", trades.unknownCount], ["Visible BUY Size", trades.buySize], ["Visible SELL Size", trades.sellSize],
                            ["VISIBLE TRADE FLOW", trades.buyRatio === null ? "BUY — / SELL —"
                                : `BUY ${trades.buyRatio.toFixed(1)}% / SELL ${trades.sellRatio.toFixed(1)}%`],
                        ]} /></>}
                </section>
            </div>
            <MarkerInspector marker={resolveSelectedMarker(markerModel, selectedMarkerId)}
                marketContext={model.marketContext} />
            <details className="mi-advanced-disclosure mi-market-view__analysis-details">
                <summary>Market Analysis Details（市場分析詳細）</summary>
                <section aria-labelledby="mi-market-metrics-title" className="mi-market-view__card mi-market-view__metrics">
                    <h3 id="mi-market-metrics-title">Market Metrics</h3>
                    <FieldGrid fields={[
                        ["Buy Pressure", model.metrics.buyPressure], ["Sell Pressure", model.metrics.sellPressure],
                        ["Pressure Balance", model.metrics.pressureBalance], ["Liquidity", model.metrics.liquidity],
                        ["Momentum", model.metrics.momentum], ["Spread", model.metrics.spread],
                        ["Spread %", model.metrics.spreadPct], ["Volatility", model.metrics.volatility],
                        ["Absorption", model.metrics.absorption], ["Fake Pressure", model.metrics.fakePressure],
                        ["Spoofing", model.metrics.spoofing], ["Iceberg", model.metrics.iceberg],
                        ["Market Data Quality", model.quality.market],
                    ]} />
                    <h4>Data Quality</h4>
                    <FieldGrid fields={[["Market Quality", model.quality.market], ["Order Book Quality", model.quality.orderBook],
                        ["Trade Quality", model.quality.trades], ["Metrics Quality", model.quality.metrics]]} />
                    <h4>Diagnostics</h4>
                    <FieldGrid fields={[
                        ["Source Event Type", model.diagnostics.sourceEventType], ["Missing Field Count", model.diagnostics.missingFields],
                        ["Invalid Order Book Row Count", model.diagnostics.invalidOrderBookRows],
                        ["Duplicate Order Book Price Count", model.diagnostics.duplicateOrderBookPrices],
                        ["Invalid Trade Row Count", model.diagnostics.invalidTradeRows],
                        ["Duplicate Trade ID Count", model.diagnostics.duplicateTradeIds],
                        ["Duplicate Trade Sequence Count", model.diagnostics.duplicateTradeSequences],
                        ["Truncated Ask Count", model.diagnostics.truncatedAsks],
                        ["Truncated Bid Count", model.diagnostics.truncatedBids],
                        ["Truncated Trade Count", model.diagnostics.truncatedTrades],
                    ]} />
                </section>
            </details>
            <details className="mi-advanced-disclosure mi-market-view__marker-details">
                <summary>Marker Details（マーカー詳細）</summary>
                <ReplayMarkerOverlay model={markerModel} />
            </details>
        </section>
    );
}

export default function ReplayMarketView() {
    const { marketContext, normalizedMarketModel: providedMarketModel, replayEngine } = useMarketIntelligence();
    const [displayMode, setDisplayMode] = useState("BOTH");
    const [rowLimit, setRowLimit] = useState(20);
    const [tradeRowLimit, setTradeRowLimit] = useState(20);
    const normalizedMarketModel = providedMarketModel ?? (isReplayMarketContextActive(replayEngine)
        ? normalizeReplayMarketModel({ replayEngine })
        : createDashboardContextMarketModel(marketContext));
    const model = buildReplayMarketViewModel(replayEngine, normalizedMarketModel);
    const markerModel = buildReplayMarkerOverlayModel(replayEngine, model);
    const contextKey = model.marketContext.key;
    const [markerUi, setMarkerUi] = useState({
        contextKey, expandedMarkerGroupKey: null, selectedMarkerId: null,
    });
    const reconciledSelection = reconcileMarkerUiSelection({ currentContextKey: contextKey,
        expandedMarkerGroupKey: markerUi.expandedMarkerGroupKey, markerModel,
        previousContextKey: markerUi.contextKey, selectedMarkerId: markerUi.selectedMarkerId });
    if (markerUi.contextKey !== contextKey
        || markerUi.selectedMarkerId !== reconciledSelection.selectedMarkerId
        || markerUi.expandedMarkerGroupKey !== reconciledSelection.expandedMarkerGroupKey) {
        setMarkerUi({ contextKey, ...reconciledSelection });
    }
    const handleGroupToggle = (key) => setMarkerUi((current) => ({ ...current,
        expandedMarkerGroupKey: current.expandedMarkerGroupKey === key ? null : key }));
    const handleMarkerSelect = (id) => setMarkerUi((current) => ({ ...current, selectedMarkerId: id }));
    return <ReplayMarketViewContent model={model}
        expandedMarkerGroupKey={reconciledSelection.expandedMarkerGroupKey}
        displayMode={displayMode}
        markerModel={markerModel}
        onMarkerGroupToggle={handleGroupToggle}
        onMarkerSelect={handleMarkerSelect}
        onDisplayModeChange={setDisplayMode}
        onRowLimitChange={setRowLimit}
        onTradeRowLimitChange={setTradeRowLimit}
        rowLimit={rowLimit} selectedMarkerId={reconciledSelection.selectedMarkerId} tradeRowLimit={tradeRowLimit} />;
}
