import {
    createNormalizedMarketModel,
    isNormalizedMarketModelStale,
    NORMALIZED_MARKET_ISSUES,
} from "./normalizedMarketModel.js";

const finite = (value) => typeof value === "number" && Number.isFinite(value);

export function normalizeLiveMarketModel({
    market,
    runtime,
    connection,
    context,
    orderBook,
    receivedAt,
    staleAfterMs,
    now,
} = {}) {
    const marketValue = market && typeof market === "object" && !Array.isArray(market) ? market : {};
    const runtimeValue = runtime && typeof runtime === "object" && !Array.isArray(runtime) ? runtime : {};
    const connectionValue = connection && typeof connection === "object" && !Array.isArray(connection)
        ? connection : {};
    const sourceUpdatedAt = marketValue.timestamp ?? runtimeValue.lastPacketTimestamp
        ?? runtimeValue.lastMessageTimestamp;
    const staleResult = sourceUpdatedAt === null || sourceUpdatedAt === undefined || sourceUpdatedAt === ""
        ? { stale: null, issue: NORMALIZED_MARKET_ISSUES.SOURCE_TIMESTAMP_MISSING }
        : !Number.isFinite(typeof sourceUpdatedAt === "number" ? sourceUpdatedAt : Date.parse(sourceUpdatedAt))
            ? { stale: null, issue: NORMALIZED_MARKET_ISSUES.SOURCE_TIMESTAMP_INVALID }
            : staleAfterMs === undefined ? { stale: runtimeValue.streamStale === true, issue: null }
                : isNormalizedMarketModelStale({ sourceUpdatedAt, staleAfterMs, now });
    const connected = connectionValue.connected ?? runtimeValue.websocketConnected
        ?? runtimeValue.wsStatus === "LIVE";
    const unavailable = connected === false;
    const issues = [
        NORMALIZED_MARKET_ISSUES.TRADES_UNAVAILABLE,
        NORMALIZED_MARKET_ISSUES.MARKERS_UNAVAILABLE,
    ];
    if (staleResult.issue) issues.push(staleResult.issue);
    const timestampStatus = staleResult.issue === NORMALIZED_MARKET_ISSUES.SOURCE_TIMESTAMP_INVALID
        ? "INVALID" : staleResult.issue === NORMALIZED_MARKET_ISSUES.SOURCE_TIMESTAMP_MISSING
            ? "WAITING" : undefined;
    const book = orderBook ?? marketValue.orderBook ?? {
        asks: marketValue.asks,
        bids: marketValue.bids,
    };
    const bookQuality = typeof book?.dataQuality === "string" ? book.dataQuality.toUpperCase() : null;
    const syncState = typeof book?.syncState === "string" ? book.syncState.toUpperCase() : null;
    if (bookQuality === "INVALID" || syncState === "UNSYNCED")
        issues.push(NORMALIZED_MARKET_ISSUES.BOOK_INVALID);
    const bestBid = finite(marketValue.bestBid) ? marketValue.bestBid : finite(marketValue.bid)
        ? marketValue.bid : Array.isArray(book?.bids) ? (Array.isArray(book.bids[0])
            ? book.bids[0][0] : book.bids[0]?.price) : null;
    const bestAsk = finite(marketValue.bestAsk) ? marketValue.bestAsk : finite(marketValue.ask)
        ? marketValue.ask : Array.isArray(book?.asks) ? (Array.isArray(book.asks[0])
            ? book.asks[0][0] : book.asks[0]?.price) : null;
    const currentPrice = finite(marketValue.price) ? marketValue.price
        : finite(marketValue.lastPrice) ? marketValue.lastPrice
            : finite(bestBid) && finite(bestAsk) && bestBid <= bestAsk ? (bestBid + bestAsk) / 2 : null;
    return createNormalizedMarketModel({
        context,
        source: {
            mode: "LIVE",
            provider: "RUNTIME_WEBSOCKET",
            datasetId: null,
            connectionId: connectionValue.connectionId,
        },
        timestamps: {
            observedAt: marketValue.timestamp,
            receivedAt,
            sourceUpdatedAt,
            cursorTimestamp: null,
        },
        currentPrice,
        bestBid,
        bestAsk,
        orderBook: book,
        recentTrades: [],
        markers: [],
        issues,
        status: unavailable || bookQuality === "UNAVAILABLE" ? "UNAVAILABLE"
            : bookQuality === "INVALID" || syncState === "UNSYNCED" ? "INVALID"
                : bookQuality === "STALE" ? "STALE" : timestampStatus,
        unavailable,
        stale: staleResult.stale === true,
    });
}
