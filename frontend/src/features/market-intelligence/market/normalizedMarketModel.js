export const NORMALIZED_MARKET_SOURCE_MODES = Object.freeze(["NONE", "REPLAY", "LIVE"]);
export const NORMALIZED_MARKET_PROVIDERS = Object.freeze([
    "NONE", "REPLAY_PROJECTION", "RUNTIME_WEBSOCKET",
]);
export const NORMALIZED_MARKET_STATUSES = Object.freeze([
    "NO_MARKET", "WAITING", "LOADING", "READY", "STALE", "UNAVAILABLE", "INVALID",
]);

const ISSUE = Object.freeze({
    CONTEXT_MISSING: "CONTEXT_MISSING",
    CONTEXT_INVALID: "CONTEXT_INVALID",
    CONTEXT_MISMATCH: "CONTEXT_MISMATCH",
    PRICE_UNAVAILABLE: "PRICE_UNAVAILABLE",
    PRICE_INVALID: "PRICE_INVALID",
    BOOK_UNAVAILABLE: "BOOK_UNAVAILABLE",
    BOOK_INVALID: "BOOK_INVALID",
    BOOK_CROSSED: "BOOK_CROSSED",
    TRADES_UNAVAILABLE: "TRADES_UNAVAILABLE",
    TRADES_INVALID: "TRADES_INVALID",
    MARKERS_UNAVAILABLE: "MARKERS_UNAVAILABLE",
    MARKERS_INVALID: "MARKERS_INVALID",
    SOURCE_TIMESTAMP_MISSING: "SOURCE_TIMESTAMP_MISSING",
    SOURCE_TIMESTAMP_INVALID: "SOURCE_TIMESTAMP_INVALID",
    SOURCE_STALE: "SOURCE_STALE",
    SOURCE_UNAVAILABLE: "SOURCE_UNAVAILABLE",
});
export const NORMALIZED_MARKET_ISSUES = ISSUE;

const finite = (value) => typeof value === "number" && Number.isFinite(value);
const positive = (value) => finite(value) && value > 0;
const nonNegative = (value) => finite(value) && value >= 0;
const text = (value) => typeof value === "string" && value.trim() ? value.trim() : null;
const nullableText = (value) => text(value);
const precision = (value) => Number.isInteger(value) && value >= 0 ? value : null;
const positiveOrNull = (value) => positive(value) ? value : null;
const unique = (values) => [...new Set(values)];

export const normalizedMarketContextKey = (context) => {
    const exchange = text(context?.exchange);
    const marketType = text(context?.marketType);
    const exchangeSymbol = text(context?.exchangeSymbol);
    return exchange && marketType && exchangeSymbol
        ? `${exchange}:${marketType}:${exchangeSymbol}` : null;
};

export const normalizeMarketTimestamp = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const numericEpoch = typeof value === "number" && Math.abs(value) < 1e12
        ? value * 1000 : value;
    const epoch = typeof numericEpoch === "number" ? numericEpoch : Date.parse(numericEpoch);
    if (!Number.isFinite(epoch)) return null;
    const date = new Date(epoch);
    return Number.isFinite(date.getTime()) ? date.toISOString() : null;
};

export const normalizeMarketContext = (input) => {
    const value = input && typeof input === "object" && !Array.isArray(input) ? input : {};
    const context = {
        exchange: text(value.exchange),
        marketType: text(value.marketType),
        exchangeSymbol: text(value.exchangeSymbol ?? value.symbol),
        normalizedSymbol: nullableText(value.normalizedSymbol ?? value.canonicalSymbol),
        displaySymbol: nullableText(value.displaySymbol),
        contextKey: null,
        tickSize: positiveOrNull(value.tickSize),
        pricePrecision: precision(value.pricePrecision),
        lotSize: positiveOrNull(value.lotSize),
        quantityPrecision: precision(value.quantityPrecision),
    };
    context.contextKey = normalizedMarketContextKey(context);
    return context;
};

const emptyQuality = () => ({
    contextValid: false,
    priceValid: false,
    bookValid: false,
    tradesValid: false,
    markersValid: false,
    isStale: false,
    issues: [ISSUE.CONTEXT_MISSING],
});

export const createEmptyNormalizedMarketModel = () => ({
    context: normalizeMarketContext(null),
    source: { mode: "NONE", provider: "NONE", datasetId: null, connectionId: null },
    status: "NO_MARKET",
    timestamps: { observedAt: null, receivedAt: null, sourceUpdatedAt: null, cursorTimestamp: null },
    price: { current: null, bestBid: null, bestAsk: null, spread: null, midpoint: null },
    orderBook: { asks: [], bids: [] },
    recentTrades: [],
    markers: [],
    dataQuality: emptyQuality(),
});

const rowValues = (row) => Array.isArray(row) ? {
    price: row[0], quantity: row[1], cumulativeQuantity: row[2],
} : row && typeof row === "object" ? {
    ...row,
    quantity: row.quantity ?? row.size,
    cumulativeQuantity: row.cumulativeQuantity ?? row.cumulativeSize,
} : {};

export const normalizeMarketBook = (input) => {
    const value = input && typeof input === "object" && !Array.isArray(input) ? input : {};
    const invalid = { count: 0 };
    const side = (rows, direction) => {
        if (!Array.isArray(rows)) return [];
        const normalized = rows.flatMap((candidate) => {
            const row = rowValues(candidate);
            if (!positive(row.price) || !nonNegative(row.quantity)) {
                invalid.count += 1;
                return [];
            }
            return [{
                price: row.price,
                quantity: row.quantity,
                cumulativeQuantity: finite(row.cumulativeQuantity) && row.cumulativeQuantity >= 0
                    ? row.cumulativeQuantity : null,
                sequence: finite(row.sequence) ? row.sequence : null,
                timestamp: normalizeMarketTimestamp(row.timestamp),
            }];
        });
        return normalized.sort((left, right) => direction * (left.price - right.price));
    };
    const asks = side(value.asks, 1);
    const bids = side(value.bids, -1);
    const cumulative = (rows) => {
        let total = 0;
        return rows.map((row, level) => {
            total += row.quantity;
            return {
                ...row,
                cumulativeQuantity: row.cumulativeQuantity ?? total,
                cumulativeSize: row.cumulativeQuantity ?? total,
                level: level + 1,
                size: row.quantity,
            };
        });
    };
    const hasFormalMetadata = ["timestamp", "sequence", "depth", "dataQuality", "syncState"]
        .some((key) => Object.hasOwn(value, key));
    const orderBook = {
        asks: cumulative(asks),
        bids: cumulative(bids),
    };
    if (hasFormalMetadata) Object.assign(orderBook, {
            timestamp: normalizeMarketTimestamp(value.timestamp),
            sequence: finite(value.sequence) ? value.sequence : null,
            depth: Number.isInteger(value.depth) && value.depth >= 0 ? value.depth : Math.max(asks.length, bids.length),
            dataQuality: text(value.dataQuality) ?? "UNAVAILABLE",
            syncState: text(value.syncState) ?? "UNAVAILABLE",
    });
    return {
        orderBook,
        invalidCount: invalid.count,
        inputInvalid: (!Array.isArray(value.asks) && value.asks !== undefined)
            || (!Array.isArray(value.bids) && value.bids !== undefined),
    };
};

const normalizeSide = (value) => {
    const side = text(value)?.toUpperCase();
    if (["BUY", "LONG", "BID"].includes(side)) return "BUY";
    if (["SELL", "SHORT", "ASK"].includes(side)) return "SELL";
    return "UNKNOWN";
};

export const normalizeMarketTrades = (input, contextKey) => {
    if (!Array.isArray(input)) return {
        recentTrades: [], invalidCount: 0, contextMismatchCount: 0, inputInvalid: input !== undefined,
    };
    let invalidCount = 0;
    let contextMismatchCount = 0;
    const recentTrades = input.flatMap((candidate, index) => {
        if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
            invalidCount += 1;
            return [];
        }
        const timestamp = normalizeMarketTimestamp(candidate.timestamp);
        const side = normalizeSide(candidate.side ?? candidate.aggressor);
        const candidateContextKey = text(candidate.contextKey);
        if (!positive(candidate.price) || !positive(candidate.quantity ?? candidate.size) || !timestamp) {
            invalidCount += 1;
            return [];
        }
        if (candidateContextKey && contextKey && candidateContextKey !== contextKey) {
            contextMismatchCount += 1;
            return [];
        }
        const tradeId = text(candidate.tradeId);
        const eventId = text(candidate.eventId);
        return [{
            id: text(candidate.id) ?? tradeId ?? eventId ?? `trade-${index}`,
            timestamp,
            sequence: finite(candidate.sequence) ? candidate.sequence : null,
            price: candidate.price,
            quantity: candidate.quantity ?? candidate.size,
            side,
            eventId,
            tradeId,
            orderId: text(candidate.orderId),
            contextKey,
        }];
    }).sort((left, right) => {
        const time = Date.parse(right.timestamp) - Date.parse(left.timestamp);
        if (time !== 0) return time;
        if (finite(left.sequence) && finite(right.sequence)) return right.sequence - left.sequence;
        return 0;
    });
    return { recentTrades, invalidCount, contextMismatchCount, inputInvalid: false };
};

const priceState = (currentCandidate, orderBook, issues, quotes = {}) => {
    const bestAsk = positive(quotes.bestAsk) ? quotes.bestAsk : orderBook.asks[0]?.price ?? null;
    const bestBid = positive(quotes.bestBid) ? quotes.bestBid : orderBook.bids[0]?.price ?? null;
    const crossed = finite(bestAsk) && finite(bestBid) && bestBid > bestAsk;
    if (crossed) issues.push(ISSUE.BOOK_CROSSED);
    const spread = finite(bestAsk) && finite(bestBid) && !crossed
        ? Number((bestAsk - bestBid).toPrecision(12)) : null;
    const midpoint = finite(bestAsk) && finite(bestBid) && !crossed
        ? (bestAsk + bestBid) / 2 : null;
    return {
        current: positive(currentCandidate) ? currentCandidate : midpoint,
        bestBid,
        bestAsk,
        spread,
        midpoint,
    };
};

export function createNormalizedMarketModel({
    context: contextInput,
    source = {},
    status,
    timestamps = {},
    currentPrice,
    bestBid,
    bestAsk,
    orderBook: bookInput,
    recentTrades: tradeInput,
    markers: markerInput,
    issues: initialIssues = [],
    loading = false,
    unavailable = false,
    stale = false,
} = {}) {
    const context = normalizeMarketContext(contextInput);
    if (!context.contextKey) {
        const empty = createEmptyNormalizedMarketModel();
        empty.dataQuality.issues = unique([
            contextInput ? ISSUE.CONTEXT_INVALID : ISSUE.CONTEXT_MISSING,
            ...initialIssues,
        ]);
        return empty;
    }
    const issues = [...initialIssues];
    const { orderBook, invalidCount: invalidBookCount, inputInvalid: bookInputInvalid } = normalizeMarketBook(bookInput);
    if (bookInputInvalid || invalidBookCount > 0) issues.push(ISSUE.BOOK_INVALID);
    if (!orderBook.asks.length && !orderBook.bids.length) issues.push(ISSUE.BOOK_UNAVAILABLE);
    const { recentTrades, invalidCount: invalidTradeCount, contextMismatchCount, inputInvalid: tradeInputInvalid }
        = normalizeMarketTrades(tradeInput, context.contextKey);
    if (tradeInputInvalid || invalidTradeCount > 0) issues.push(ISSUE.TRADES_INVALID);
    if (contextMismatchCount > 0) issues.push(ISSUE.CONTEXT_MISMATCH);
    const markers = Array.isArray(markerInput)
        ? markerInput.filter((marker) => marker && typeof marker === "object" && !Array.isArray(marker)
            && text(marker.id ?? marker.markerId) && text(marker.type)
            && (!text(marker.contextKey) || marker.contextKey === context.contextKey))
        : [];
    if (!Array.isArray(markerInput) && markerInput !== undefined) issues.push(ISSUE.MARKERS_INVALID);
    else if (Array.isArray(markerInput) && markers.length !== markerInput.length) issues.push(ISSUE.MARKERS_INVALID);
    if (Array.isArray(markerInput) && markerInput.some((marker) => text(marker?.contextKey)
        && marker.contextKey !== context.contextKey)) issues.push(ISSUE.CONTEXT_MISMATCH);
    const price = priceState(currentPrice, orderBook, issues, { bestBid, bestAsk });
    if (!positive(currentPrice) && currentPrice !== null && currentPrice !== undefined)
        issues.push(ISSUE.PRICE_INVALID);
    if (!positive(price.current)) issues.push(ISSUE.PRICE_UNAVAILABLE);
    const normalizedTimestamps = Object.fromEntries(
        ["observedAt", "receivedAt", "sourceUpdatedAt", "cursorTimestamp"]
            .map((key) => [key, normalizeMarketTimestamp(timestamps[key])]),
    );
    for (const key of ["observedAt", "receivedAt", "sourceUpdatedAt", "cursorTimestamp"]) {
        if (timestamps[key] !== null && timestamps[key] !== undefined && normalizedTimestamps[key] === null)
            issues.push(ISSUE.SOURCE_TIMESTAMP_INVALID);
    }
    if (!normalizedTimestamps.sourceUpdatedAt) issues.push(ISSUE.SOURCE_TIMESTAMP_MISSING);
    if (stale) issues.push(ISSUE.SOURCE_STALE);
    if (unavailable) issues.push(ISSUE.SOURCE_UNAVAILABLE);
    const hasData = positive(price.current) || orderBook.asks.length > 0
        || orderBook.bids.length > 0 || recentTrades.length > 0 || markers.length > 0;
    const resolvedStatus = status ?? (unavailable ? "UNAVAILABLE" : loading ? "LOADING"
        : issues.includes(ISSUE.BOOK_CROSSED) ? "INVALID"
            : stale && hasData ? "STALE" : hasData ? "READY" : "WAITING");
    return {
        context,
        source: {
            mode: NORMALIZED_MARKET_SOURCE_MODES.includes(source.mode) ? source.mode : "NONE",
            provider: NORMALIZED_MARKET_PROVIDERS.includes(source.provider) ? source.provider : "NONE",
            datasetId: nullableText(source.datasetId),
            connectionId: nullableText(source.connectionId),
        },
        status: NORMALIZED_MARKET_STATUSES.includes(resolvedStatus) ? resolvedStatus : "INVALID",
        timestamps: normalizedTimestamps,
        price,
        orderBook,
        recentTrades,
        markers,
        dataQuality: {
            contextValid: true,
            priceValid: positive(price.current),
            bookValid: !issues.includes(ISSUE.BOOK_INVALID) && !issues.includes(ISSUE.BOOK_CROSSED)
                && (orderBook.asks.length > 0 || orderBook.bids.length > 0),
            tradesValid: !issues.includes(ISSUE.TRADES_INVALID) && !issues.includes(ISSUE.TRADES_UNAVAILABLE),
            markersValid: !issues.includes(ISSUE.MARKERS_INVALID) && !issues.includes(ISSUE.MARKERS_UNAVAILABLE),
            isStale: resolvedStatus === "STALE",
            issues: unique(issues),
        },
    };
}

export function isNormalizedMarketModelStale({ sourceUpdatedAt, staleAfterMs, now } = {}) {
    const sourceTime = normalizeMarketTimestamp(sourceUpdatedAt);
    const nowTime = normalizeMarketTimestamp(now);
    if (sourceUpdatedAt === null || sourceUpdatedAt === undefined || sourceUpdatedAt === "")
        return { stale: null, issue: ISSUE.SOURCE_TIMESTAMP_MISSING };
    if (!sourceTime || !nowTime || !finite(staleAfterMs) || staleAfterMs < 0)
        return { stale: null, issue: ISSUE.SOURCE_TIMESTAMP_INVALID };
    return { stale: Date.parse(nowTime) - Date.parse(sourceTime) > staleAfterMs, issue: null };
}

export function validateNormalizedMarketModel(model) {
    const issues = [];
    if (!model || typeof model !== "object" || Array.isArray(model))
        return { valid: false, issues: [ISSUE.CONTEXT_INVALID] };
    const contextKey = normalizedMarketContextKey(model.context);
    if (!contextKey) issues.push(ISSUE.CONTEXT_INVALID);
    else if (model.context?.contextKey !== contextKey) issues.push(ISSUE.CONTEXT_MISMATCH);
    if (!NORMALIZED_MARKET_SOURCE_MODES.includes(model.source?.mode)
        || !NORMALIZED_MARKET_PROVIDERS.includes(model.source?.provider))
        issues.push(ISSUE.SOURCE_UNAVAILABLE);
    if (!NORMALIZED_MARKET_STATUSES.includes(model.status)) issues.push(ISSUE.SOURCE_UNAVAILABLE);
    for (const value of Object.values(model.price ?? {})) {
        if (value !== null && !finite(value)) issues.push(ISSUE.PRICE_INVALID);
    }
    const book = normalizeMarketBook(model.orderBook);
    const asks = Array.isArray(model.orderBook?.asks) ? model.orderBook.asks : [];
    const bids = Array.isArray(model.orderBook?.bids) ? model.orderBook.bids : [];
    if (book.inputInvalid || book.invalidCount
        || asks.some((row, index) => index && rowValues(asks[index - 1]).price > rowValues(row).price)
        || bids.some((row, index) => index && rowValues(bids[index - 1]).price < rowValues(row).price))
        issues.push(ISSUE.BOOK_INVALID);
    const trades = normalizeMarketTrades(model.recentTrades, contextKey);
    if (trades.inputInvalid || trades.invalidCount) issues.push(ISSUE.TRADES_INVALID);
    if (!Array.isArray(model.markers)) issues.push(ISSUE.MARKERS_INVALID);
    if (!model.timestamps || typeof model.timestamps !== "object") issues.push(ISSUE.SOURCE_TIMESTAMP_INVALID);
    else if (Object.values(model.timestamps).some((value) => value !== null
        && normalizeMarketTimestamp(value) === null)) issues.push(ISSUE.SOURCE_TIMESTAMP_INVALID);
    return { valid: issues.length === 0, issues: unique(issues) };
}
