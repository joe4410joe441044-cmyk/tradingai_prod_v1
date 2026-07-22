import { useState } from "react";

import { buildOrderBookDomDisplay, buildRecentTradesDisplay, buildReplayMarketViewModel } from "../../features/market-intelligence/replay/replayMarketViewModel.js";
import { buildReplayMarkerOverlayModel } from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import ReplayMarkerOverlay from "./ReplayMarkerOverlay.jsx";
import { bilingual } from "./marketIntelligenceLabels.js";

const FieldGrid = ({ fields }) => (
    <dl className="mi-market-view__fields">
        {fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
);

const BookTable = ({ label, markerModel, rows }) => (
    <div className={`mi-market-view__book-side mi-market-view__book-side--${label.toLowerCase()}`}>
        <h4>{label} LEVELS（{label === "ASK" ? "売板" : "買板"}）</h4>
        <div className="mi-market-view__table-wrap">
            <table>
                <thead><tr><th>{bilingual("price")}</th><th>{bilingual("size")}</th><th>{bilingual("total")}</th><th>{bilingual("marker")}</th></tr></thead>
                <tbody>{rows.map((row) => {
                    const markers = markerModel.priceMarkers.filter((marker) => marker.priceMatch && marker.price === row.price);
                    return (
                        <tr key={row.id}>
                            <td className="mi-order-book__price"><span aria-hidden="true" className="mi-order-book__depth"
                                style={{ width: `${row.depthPercent}%` }} /><span>{row.price}</span></td>
                            <td>{row.size}</td><td>{row.optionalTotal}</td>
                            <td className="mi-order-book__marker-slot">
                                {markers.length === 0 ? "—" : markers.map((marker) => (
                                    <span className="mi-order-book__marker" key={marker.displayKey}>{marker.label}</span>
                                ))}
                            </td>
                        </tr>
                    );
                })}</tbody>
            </table>
        </div>
    </div>
);

const SourceBadge = ({ source }) => <div className="mi-market-source" aria-label="Panel market identity">
    <span><strong>{source.exchange}</strong> / <strong>{source.exchangeSymbol}</strong></span>
</div>;

export function ReplayMarketViewContent({
    model,
    markerModel = buildReplayMarkerOverlayModel(null, model),
    displayMode = "BOTH",
    rowLimit = 20,
    tradeRowLimit = 50,
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
            <section aria-labelledby="mi-market-header-title" className="mi-market-view__market-header">
                <h2 className="mi-visually-hidden" id="mi-market-view-title">REPLAY MARKET VIEW（リプレイ市場表示）</h2>
                <h3 className="mi-visually-hidden" id="mi-market-header-title">Market Summary（市場サマリー）</h3>
                {model.isEmpty ? <p className="mi-market-view__empty-banner"><strong>NO REPLAY SELECTED（リプレイ未選択）</strong>
                    <span>Load a sample replay or select a position.（サンプルリプレイを読み込むか、対象ポジションを選択してください）</span></p> : (
                    <dl className="mi-market-summary">
                        <div className="mi-market-summary__identity"><dt className="mi-visually-hidden">Market identity</dt>
                            <dd>{model.source.exchange} / {model.source.marketType}（先物） / {model.source.exchangeSymbol}</dd></div>
                        <div><dt>Mark Price（マーク価格）</dt><dd>{model.header.markPrice}</dd></div>
                        <div><dt>Last Price（最終約定価格）</dt><dd>{model.header.lastTradePrice}</dd></div>
                        <div><dt>Spread（スプレッド）</dt><dd>{model.orderBook.spread}</dd></div>
                        <div><dt>{bilingual("quality")}</dt><dd>{model.header.dataQuality}</dd></div>
                        <div><dt>{bilingual("source")}</dt><dd>{model.source.sourceMode}{model.source.isSample ? " · SAMPLE REPLAY" : ""}</dd></div>
                    </dl>
                )}
            </section>
            <div className="mi-market-view__body">
                <section aria-labelledby="mi-market-book-title" className="mi-market-view__card">
                    <h3 id="mi-market-book-title">{bilingual("orderBook")}</h3>
                    <SourceBadge source={model.source} />
                    <div className="mi-order-book__toolbar">
                        <div aria-label="Order book display mode" className="mi-order-book__modes">
                            {["BOTH", "BIDS", "ASKS"].map((mode) => <button aria-pressed={dom.mode === mode}
                                key={mode} onClick={() => onDisplayModeChange(mode)} type="button">{mode}</button>)}
                        </div>
                        <label>ROWS（行数） <select aria-label="Displayed order book rows" onChange={(event) => onRowLimitChange(Number(event.target.value))}
                            value={dom.rowLimit}>{[10, 20, 50].map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
                    </div>
                    {model.orderBook.asks.length + model.orderBook.bids.length === 0 ? (
                        <div className="mi-market-view__empty"><strong>ORDER BOOK EMPTY（板情報なし）</strong></div>
                    ) : <>
                        {displayMode !== "BIDS" && (dom.asks.length > 0
                            ? <BookTable label="ASK" markerModel={markerModel} rows={dom.asks} />
                            : <p className="mi-market-view__empty">ASK DATA UNAVAILABLE</p>)}
                        <div className="mi-order-book__current">
                            <span>{model.header.currentPriceSource}</span>
                            <strong>{model.header.currentPrice}</strong>
                            <span>{model.header.priceDirection}</span>
                            <small>Spread（スプレッド） {model.orderBook.spread} · {model.orderBook.spreadPct}%</small>
                        </div>
                        {displayMode !== "ASKS" && (dom.bids.length > 0
                            ? <BookTable label="BID" markerModel={markerModel} rows={dom.bids} />
                            : <p className="mi-market-view__empty">BID DATA UNAVAILABLE</p>)}
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
                    <SourceBadge source={model.source} />
                    <div className="mi-recent-trades__toolbar"><label>ROWS（行数） <select aria-label="Displayed recent trade rows"
                        onChange={(event) => onTradeRowLimitChange(Number(event.target.value))} value={trades.rowLimit}>
                        {[20, 50, 100].map((count) => <option key={count} value={count}>{count}</option>)}</select></label></div>
                    {model.recentTrades.rows.length === 0 ? (
                        <div className="mi-market-view__empty"><strong>{model.diagnostics.invalidTradeRows > 0
                            ? "RECENT TRADES UNAVAILABLE（約定履歴取得不可）" : "RECENT TRADES EMPTY（約定履歴なし）"}</strong></div>
                    ) : <div className="mi-market-view__table-wrap"><table>
                        <thead><tr><th>{bilingual("price")}</th><th>{bilingual("size")}</th><th>{bilingual("time")}</th><th>{bilingual("side")}</th><th>{bilingual("marker")}</th></tr></thead>
                        <tbody>{trades.rows.map((trade) => (
                            <tr key={`${trade.id}-${trade.inputIndex}`} aria-label={trade.isCurrent ? "Current trade" : undefined}
                                className={`mi-market-view__trade--${trade.side.toLowerCase()}${trade.isCurrent ? " mi-market-view__trade--current" : ""}`}>
                                <td>{trade.price}</td><td className="mi-recent-trades__size"><span aria-hidden="true"
                                    className="mi-recent-trades__intensity" style={{ width: `${trade.intensity}%` }} /><span>{trade.size}</span></td>
                                <td>{trade.time}</td><td>{trade.side}{trade.isCurrent && <small>CURRENT</small>}</td>
                                <td>{trade.markers.length ? trade.markers.map((marker) => <span className="mi-order-book__marker"
                                    key={marker.displayKey}>{marker.label}</span>) : "—"}</td>
                            </tr>
                        ))}</tbody>
                    </table></div>}
                    {!model.isEmpty && <><h4>Trade Summary</h4>
                        <FieldGrid fields={[
                            ["Visible Trades", trades.count], ["BUY Count", trades.buyCount], ["SELL Count", trades.sellCount],
                            ["UNKNOWN Count", trades.unknownCount], ["Visible BUY Size", trades.buySize], ["Visible SELL Size", trades.sellSize],
                            ["VISIBLE TRADE FLOW", trades.buyRatio === null ? "BUY — / SELL —"
                                : `BUY ${trades.buyRatio.toFixed(1)}% / SELL ${trades.sellRatio.toFixed(1)}%`],
                        ]} /></>}
                </section>
            </div>
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
    const { replayEngine } = useMarketIntelligence();
    const [displayMode, setDisplayMode] = useState("BOTH");
    const [rowLimit, setRowLimit] = useState(20);
    const [tradeRowLimit, setTradeRowLimit] = useState(50);
    const model = buildReplayMarketViewModel(replayEngine);
    return <ReplayMarketViewContent model={model}
        displayMode={displayMode}
        markerModel={buildReplayMarkerOverlayModel(replayEngine, model)}
        onDisplayModeChange={setDisplayMode}
        onRowLimitChange={setRowLimit}
        onTradeRowLimitChange={setTradeRowLimit}
        rowLimit={rowLimit} tradeRowLimit={tradeRowLimit} />;
}
