const DASH = "—";
const UNKNOWN = "UNKNOWN";
const MAX_BOOK_ROWS = 50;
const MAX_TRADES = 100;
const METRIC_KEYS = [
    "buyPressure", "sellPressure", "pressureBalance", "liquidity", "momentum",
    "spread", "spreadPct", "volatility", "absorption", "fakePressure", "spoofing", "iceberg",
];

const finite = (value) => typeof value === "number" && Number.isFinite(value);
export const marketDisplayValue = (value) => {
    if (typeof value === "string") return value === "" ? DASH : value;
    if (finite(value)) return String(value);
    if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
    return DASH;
};
export const marketTimestamp = (value) => {
    if (value === null || value === undefined || value === "") return DASH;
    const epoch = typeof value === "number" ? value : Date.parse(value);
    if (!Number.isFinite(epoch)) return DASH;
    const date = new Date(epoch);
    return Number.isFinite(date.getTime()) ? date.toISOString() : DASH;
};
export const normalizeMarketSide = (side) => {
    const value = typeof side === "string" ? side.toUpperCase() : "";
    if (["BUY", "LONG", "BID"].includes(value)) return "BUY";
    if (["SELL", "SHORT", "ASK"].includes(value)) return "SELL";
    return UNKNOWN;
};
export const normalizeMarketSource = (source) => {
    const value = source && typeof source === "object" && !Array.isArray(source) ? source : {};
    const safe = (candidate) => typeof candidate === "string" && candidate.trim() ? candidate.trim() : UNKNOWN;
    return {
        exchange: safe(value.exchange), marketType: safe(value.marketType),
        exchangeSymbol: safe(value.exchangeSymbol), canonicalSymbol: safe(value.canonicalSymbol),
        displaySymbol: safe(value.displaySymbol), sourceMode: safe(value.sourceMode),
        pricePrecision: Number.isInteger(value.pricePrecision) && value.pricePrecision >= 0
            ? value.pricePrecision : null,
        tickSize: finite(value.tickSize) && value.tickSize > 0 ? value.tickSize : null,
        quantityPrecision: Number.isInteger(value.quantityPrecision) && value.quantityPrecision >= 0
            ? value.quantityPrecision : null,
        lotSize: finite(value.lotSize) && value.lotSize > 0 ? value.lotSize : null,
        isSample: value.isSample === true,
    };
};

const rawMarketContext = (event) => {
    const payload = payloadOf(event);
    const source = payload.marketSource && typeof payload.marketSource === "object"
        && !Array.isArray(payload.marketSource) ? payload.marketSource : payload;
    const value = {
        exchange: source.exchange,
        marketType: source.marketType,
        exchangeSymbol: source.exchangeSymbol ?? source.symbol,
        canonicalSymbol: source.canonicalSymbol,
        displaySymbol: source.displaySymbol,
        sourceMode: source.sourceMode,
        pricePrecision: source.pricePrecision,
        tickSize: source.tickSize,
        quantityPrecision: source.quantityPrecision,
        lotSize: source.lotSize,
        isSample: source.isSample,
    };
    const hasIdentity = [value.exchange, value.marketType, value.exchangeSymbol]
        .every((item) => typeof item === "string" && item.trim());
    return hasIdentity ? normalizeMarketSource(value) : null;
};

const tickPrecision = (tickSize) => {
    if (!finite(tickSize) || tickSize <= 0) return null;
    const text = String(tickSize).toLowerCase();
    if (text.includes("e-")) return Number(text.split("e-")[1]);
    return text.includes(".") ? text.split(".")[1].length : 0;
};
export const formatMarketPrice = (value, source = {}) => {
    if (!finite(value)) return DASH;
    const precision = source.pricePrecision ?? tickPrecision(source.tickSize);
    return Number.isInteger(precision) && precision >= 0 && precision <= 20
        ? value.toFixed(precision) : marketDisplayValue(value);
};
export const formatMarketQuantity = (value, source = {}) => {
    if (!finite(value)) return DASH;
    const precision = source.quantityPrecision ?? tickPrecision(source.lotSize);
    return Number.isInteger(precision) && precision >= 0 && precision <= 20
        ? value.toFixed(precision) : marketDisplayValue(value);
};
const marketDataState = ({ replayEngine, source, hasContext, hasMarketData, quality, crossed }) => {
    const machineState = replayEngine?.machine?.state;
    if (!hasContext) return "NO MARKET SELECTED";
    if (machineState === "REPLAY_LOADING" || machineState === "LOADING") return "LOADING";
    if (machineState === "REPLAY_ERROR" || quality === "INVALID" || crossed) return "UNAVAILABLE";
    if (!hasMarketData) return "WAITING";
    if (quality === "STALE") return "STALE";
    if (source.sourceMode === "LIVE") return "LIVE";
    if (source.sourceMode === "REPLAY") return "REPLAY";
    return "UNAVAILABLE";
};
const normalizedPresentationState = (model) => {
    if (!model) return null;
    if (model.status === "NO_MARKET") return "NO MARKET SELECTED";
    if (model.status === "READY") return model.source?.mode === "LIVE" ? "READY" : "REPLAY";
    if (model.status === "INVALID") return "UNAVAILABLE";
    return model.status;
};

export const marketContextKey = (context) => context
    && [context.exchange, context.marketType, context.exchangeSymbol]
        .every((value) => typeof value === "string" && value && value !== UNKNOWN)
    ? `${context.exchange}\u0000${context.marketType}\u0000${context.exchangeSymbol}` : null;

const scopeEventsToMarketContext = (events) => {
    const contexts = events.map(rawMarketContext);
    const activeIndex = contexts.findLastIndex(Boolean);
    if (activeIndex < 0) return { activeContext: null, events, contextChanged: false };
    const activeContext = contexts[activeIndex];
    const activeKey = marketContextKey(activeContext);
    let runKey = null;
    let runStart = 0;
    let contextChanged = false;
    contexts.forEach((context, index) => {
        if (!context) return;
        const key = marketContextKey(context);
        if (runKey === null) runStart = index;
        else if (key !== runKey) {
            runStart = index;
            contextChanged = true;
        }
        runKey = key;
    });
    const scoped = events.slice(runStart).filter((event) => {
        const context = rawMarketContext(event);
        return !context || marketContextKey(context) === activeKey;
    });
    return { activeContext, events: scoped, contextChanged };
};

export const normalizedTradeTime = (value) => {
    const normalized = finite(value) ? new Date(value).toISOString() : value;
    if (typeof normalized !== "string" || !normalized.trim() || !Number.isFinite(Date.parse(normalized))) return "TIME UNKNOWN";
    const match = normalized.match(/T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?/);
    if (!match) return "TIME UNKNOWN";
    return match[2] ? `${match[1]}.${match[2].slice(0, 3).padEnd(Math.min(3, match[2].length), "0")}` : match[1];
};

const payloadOf = (event) => event?.payload && typeof event.payload === "object"
    && !Array.isArray(event.payload) ? event.payload : {};
const qualityOf = (event, nested) => marketDisplayValue(nested?.dataQuality ?? event?.dataQuality) === DASH
    ? UNKNOWN : marketDisplayValue(nested?.dataQuality ?? event?.dataQuality);
const rowValues = (row) => Array.isArray(row)
    ? { price: row[0], quantity: row[1], largeSize: row[2] }
    : row && typeof row === "object" ? row : {};

const normalizeBookSide = (rows, side) => {
    const source = Array.isArray(rows) ? rows : [];
    let invalid = 0;
    const valid = [];
    for (const candidate of source) {
        const row = rowValues(candidate);
        if (!finite(row.price) || row.price <= 0 || !finite(row.quantity) || row.quantity <= 0) {
            invalid += 1;
            continue;
        }
        valid.push({
            numericPrice: row.price,
            numericSize: row.quantity,
            formalCumulativeSize: finite(row.cumulativeSize) && row.cumulativeSize >= 0
                ? row.cumulativeSize : null,
            largeSize: marketDisplayValue(row.largeSize),
        });
    }
    const nearToFar = [...valid].sort((left, right) => side === "ASK"
        ? left.numericPrice - right.numericPrice : right.numericPrice - left.numericPrice);
    let cumulative = 0;
    const normalized = nearToFar.map((row, index) => {
        cumulative += row.numericSize;
        return {
            ...row,
            id: `${side}-${index}-${row.numericPrice}`,
            side,
            level: index + 1,
            price: marketDisplayValue(row.numericPrice),
            size: marketDisplayValue(row.numericSize),
            optionalTotal: marketDisplayValue(row.formalCumulativeSize ?? cumulative),
            cumulativeSize: marketDisplayValue(row.formalCumulativeSize ?? cumulative),
            numericCumulativeQuantity: row.formalCumulativeSize ?? cumulative,
            cumulativeSource: row.formalCumulativeSize === null ? "CALCULATED" : "FORMAL",
        };
    });
    const displayOrder = side === "ASK" ? [...normalized].reverse() : normalized;
    return {
        rows: side === "ASK" ? displayOrder.slice(-MAX_BOOK_ROWS) : displayOrder.slice(0, MAX_BOOK_ROWS),
        valid: normalized,
        invalid,
        duplicatePrices: valid.length - new Set(valid.map(({ numericPrice }) => numericPrice)).size,
        truncated: Math.max(0, valid.length - MAX_BOOK_ROWS),
    };
};

export function buildOrderBookDomDisplay(orderBook, mode = "BOTH", rowLimit = 20) {
    const safeMode = ["BOTH", "BIDS", "ASKS"].includes(mode) ? mode : "BOTH";
    const safeLimit = [10, 20, 50].includes(rowLimit) ? rowLimit : 20;
    const sourceAsks = Array.isArray(orderBook?.asks) ? orderBook.asks : [];
    const sourceBids = Array.isArray(orderBook?.bids) ? orderBook.bids : [];
    const asks = safeMode === "BIDS" ? [] : sourceAsks.slice(-safeLimit);
    const bids = safeMode === "ASKS" ? [] : sourceBids.slice(0, safeLimit);
    const displayed = [...asks, ...bids];
    const maxQuantity = displayed.reduce((max, row) => Number.isFinite(row.numericSize)
        ? Math.max(max, row.numericSize) : max, 0);
    const withDepth = (rows) => rows.map((row) => ({
        ...row,
        depthPercent: maxQuantity > 0 && Number.isFinite(row.numericSize)
            ? Math.min(100, Math.max(0, row.numericSize / maxQuantity * 100)) : 0,
    }));
    const askQuantity = asks.reduce((sum, row) => Number.isFinite(row.numericSize) ? sum + row.numericSize : sum, 0);
    const bidQuantity = bids.reduce((sum, row) => Number.isFinite(row.numericSize) ? sum + row.numericSize : sum, 0);
    const total = askQuantity + bidQuantity;
    return {
        mode: safeMode,
        rowLimit: safeLimit,
        asks: withDepth(asks),
        bids: withDepth(bids),
        buyRatio: total > 0 ? bidQuantity / total * 100 : null,
        sellRatio: total > 0 ? askQuantity / total * 100 : null,
    };
}

const tradeCandidates = (event) => {
    const payload = payloadOf(event);
    if (Array.isArray(payload.trades)) return payload.trades;
    if (["RECENT_TRADE", "TRADE"].includes(event?.eventType)) return [payload];
    return [];
};

const normalizeTrade = (trade, event, index) => {
    const timestamp = marketTimestamp(trade?.timestamp ?? event?.timestamp);
    const side = normalizeMarketSide(trade?.side ?? trade?.aggressor);
    if (!trade || typeof trade !== "object" || Array.isArray(trade)
        || !finite(trade.price) || trade.price <= 0 || !finite(trade.quantity) || trade.quantity <= 0
        || timestamp === DASH || side === UNKNOWN) return null;
    return {
        id: marketDisplayValue(trade.tradeId ?? trade.id) === DASH ? `${event?.id ?? "trade"}-${index}` : String(trade.tradeId ?? trade.id),
        eventId: marketDisplayValue(trade.eventId ?? (["RECENT_TRADE", "TRADE"].includes(event?.eventType)
            ? event?.id : null)),
        timestamp,
        time: normalizedTradeTime(trade.timestamp ?? event?.timestamp),
        side,
        aggressorSide: normalizeMarketSide(trade.aggressorSide ?? trade.aggressor),
        price: marketDisplayValue(trade.price),
        size: marketDisplayValue(trade.quantity),
        tradeId: marketDisplayValue(trade.tradeId ?? trade.id),
        orderId: marketDisplayValue(trade.orderId ?? trade.clientOrderId),
        sourceSequence: finite(trade.sequence) ? trade.sequence : finite(event?.sequence) ? event.sequence : null,
        numericPrice: trade.price,
        numericSize: trade.quantity,
        inputIndex: index,
    };
};

const identityMatch = (trade, identity) => {
    if (!identity) return false;
    if (identity.tradeId !== DASH && trade.tradeId !== DASH && identity.tradeId === trade.tradeId) return true;
    if (identity.eventId !== DASH && trade.eventId !== DASH && identity.eventId === trade.eventId) return true;
    if (finite(identity.sequence) && finite(trade.sourceSequence) && identity.sequence === trade.sourceSequence) return true;
    return identity.timestamp !== DASH && identity.timestamp === trade.timestamp
        && identity.price !== DASH && identity.price === trade.price;
};
const markerMatchesTrade = (marker, trade) => (
    marker.eventId !== DASH && trade.eventId !== DASH && marker.eventId === trade.eventId
) || (
    marker.tradeId !== DASH && trade.tradeId !== DASH && marker.tradeId === trade.tradeId
) || (
    marker.orderId !== DASH && trade.orderId !== DASH && marker.orderId === trade.orderId
) || (
    finite(marker.sourceSequence) && finite(trade.sourceSequence)
        && marker.sourceSequence === trade.sourceSequence
);

export function buildRecentTradesDisplay(recentTrades, currentIdentity, markers = [], rowLimit = 20) {
    const safeLimit = [10, 20, 50].includes(rowLimit) ? rowLimit : 20;
    const rows = (Array.isArray(recentTrades?.rows) ? recentTrades.rows : []).slice(0, safeLimit);
    const maxSize = rows.reduce((max, row) => finite(row.numericSize) ? Math.max(max, row.numericSize) : max, 0);
    const decorated = rows.map((row) => ({ ...row,
        intensity: maxSize > 0 ? Math.min(100, Math.max(0, row.numericSize / maxSize * 100)) : 0,
        isCurrent: identityMatch(row, currentIdentity),
        markers: (Array.isArray(markers) ? markers : []).filter((marker) => markerMatchesTrade(marker, row)),
    }));
    const bySide = (side) => decorated.filter((row) => row.side === side);
    const size = (side) => bySide(side).reduce((sum, row) => sum + row.numericSize, 0);
    const buySize = size("BUY"); const sellSize = size("SELL"); const known = buySize + sellSize;
    return { rowLimit: safeLimit, rows: decorated, count: decorated.length,
        buyCount: bySide("BUY").length, sellCount: bySide("SELL").length,
        unknownCount: bySide(UNKNOWN).length, buySize, sellSize,
        buyRatio: known > 0 ? buySize / known * 100 : null, sellRatio: known > 0 ? sellSize / known * 100 : null };
}

const metricSource = (events) => {
    const values = {};
    let sourceEvent = null;
    for (const event of events) {
        const payload = payloadOf(event);
        const metrics = payload.metrics && typeof payload.metrics === "object" && !Array.isArray(payload.metrics)
            ? payload.metrics : payload;
        for (const key of METRIC_KEYS) {
            if (Object.hasOwn(metrics, key)) {
                values[key] = metrics[key];
                sourceEvent = event;
            }
        }
    }
    return { values, sourceEvent };
};

export function buildReplayMarketViewModel(replayEngine, normalizedMarketModel = null) {
    const projection = replayEngine?.projection && typeof replayEngine.projection === "object"
        ? replayEngine.projection : {};
    const current = projection.currentEvent && typeof projection.currentEvent === "object"
        ? projection.currentEvent : null;
    const visibleEvents = Array.isArray(projection.visibleEvents)
        ? projection.visibleEvents.filter((event) => event && typeof event === "object") : [];
    // currentEvent is itself an authoritative Projection value. Include it only as
    // a fallback for partial projections, without consulting the Dataset or Cursor.
    const reachedEvents = current && !visibleEvents.includes(current)
        ? [...visibleEvents, current] : visibleEvents;
    const scoped = scopeEventsToMarketContext(reachedEvents);
    const events = scoped.events;
    const bookEvent = events.findLast((event) => {
        const payload = payloadOf(event);
        return payload.orderBook && typeof payload.orderBook === "object" && !Array.isArray(payload.orderBook)
            || Array.isArray(payload.asks) || Array.isArray(payload.bids);
    }) ?? null;
    const bookPayload = payloadOf(bookEvent);
    const projectionBook = bookPayload.orderBook && typeof bookPayload.orderBook === "object"
        && !Array.isArray(bookPayload.orderBook) ? bookPayload.orderBook : bookPayload;
    const normalizedBook = normalizedMarketModel?.orderBook;
    const useLiveBook = normalizedMarketModel?.source?.mode === "LIVE"
        && !replayEngine?.dataset
        && normalizedBook && typeof normalizedBook === "object" && !Array.isArray(normalizedBook);
    const book = useLiveBook ? normalizedBook : projectionBook;
    const asks = normalizeBookSide(book.asks, "ASK");
    const bids = normalizeBookSide(book.bids, "BID");
    const bestAskNumber = asks.valid.length ? Math.min(...asks.valid.map(({ numericPrice }) => numericPrice)) : null;
    const bestBidNumber = bids.valid.length ? Math.max(...bids.valid.map(({ numericPrice }) => numericPrice)) : null;
    const validTopOfBook = finite(bestAskNumber) && finite(bestBidNumber) && bestAskNumber >= bestBidNumber;
    const crossedBook = finite(bestAskNumber) && finite(bestBidNumber) && bestBidNumber > bestAskNumber;
    const lockedBook = finite(bestAskNumber) && finite(bestBidNumber) && bestBidNumber === bestAskNumber;
    const midpointNumber = validTopOfBook ? (bestAskNumber + bestBidNumber) / 2 : null;
    const payloadSpread = finite(book.spread) ? book.spread : finite(bookPayload.spread) ? bookPayload.spread : null;
    const spreadNumber = validTopOfBook
        ? Number((bestAskNumber - bestBidNumber).toPrecision(12))
        : !finite(bestAskNumber) && !finite(bestBidNumber) && finite(payloadSpread) && payloadSpread >= 0
            ? payloadSpread : null;
    const spreadPctNumber = finite(book.spreadPct) ? book.spreadPct
        : finite(spreadNumber) && finite(midpointNumber) && midpointNumber !== 0
            ? Number((spreadNumber / midpointNumber * 100).toFixed(6)) : null;
    const totalAsk = asks.valid.reduce((sum, row) => sum + row.numericSize, 0);
    const totalBid = bids.valid.reduce((sum, row) => sum + row.numericSize, 0);
    const totalDepth = totalAsk + totalBid;

    let invalidTrades = 0;
    const allTrades = events.flatMap((event, eventIndex) => tradeCandidates(event).map((trade, index) => {
        const normalized = normalizeTrade(trade, event, index);
        if (!normalized) invalidTrades += 1;
        return normalized ? { ...normalized, inputIndex: eventIndex * 100000 + index } : null;
    })).filter(Boolean);
    const tradeRows = [...allTrades].sort((left, right) => {
        const time = Date.parse(right.timestamp) - Date.parse(left.timestamp);
        if (Number.isFinite(time) && time !== 0) return time;
        if (finite(left.sourceSequence) && finite(right.sourceSequence) && left.sourceSequence !== right.sourceSequence)
            return right.sourceSequence - left.sourceSequence;
        return left.inputIndex - right.inputIndex;
    }).slice(0, MAX_TRADES);
    const buyRows = tradeRows.filter(({ side }) => side === "BUY");
    const sellRows = tradeRows.filter(({ side }) => side === "SELL");
    const buyQuantity = buyRows.reduce((sum, row) => sum + row.numericSize, 0);
    const sellQuantity = sellRows.reduce((sum, row) => sum + row.numericSize, 0);
    const totalQuantity = tradeRows.reduce((sum, row) => sum + row.numericSize, 0);
    const notional = tradeRows.reduce((sum, row) => sum + row.numericPrice * row.numericSize, 0);
    const lastTrade = tradeRows[0] ?? null;

    const metric = metricSource(events);
    const metricValues = metric.values;
    const buyPressure = metricValues.buyPressure;
    const sellPressure = metricValues.sellPressure;
    // Display-only fallback allowed by MI-0A13 when both formal pressure values are finite.
    const pressureBalance = Object.hasOwn(metricValues, "pressureBalance") ? metricValues.pressureBalance
        : finite(buyPressure) && finite(sellPressure) ? buyPressure - sellPressure : null;
    const marketEvent = [...events].reverse().find((event) => {
        const payload = payloadOf(event);
        return event.eventType === "MARKET_SNAPSHOT" || payload.symbol || payload.markPrice;
    }) ?? null;
    const marketPayload = payloadOf(marketEvent);
    const normalizedContext = normalizedMarketModel?.context?.contextKey
        ? normalizedMarketModel.context : null;
    const source = normalizedContext ? normalizeMarketSource({
        exchange: normalizedContext.exchange,
        marketType: normalizedContext.marketType,
        exchangeSymbol: normalizedContext.exchangeSymbol,
        canonicalSymbol: normalizedContext.normalizedSymbol,
        displaySymbol: normalizedContext.displaySymbol,
        sourceMode: normalizedMarketModel.source?.mode,
        pricePrecision: normalizedContext.pricePrecision,
        tickSize: normalizedContext.tickSize,
        quantityPrecision: normalizedContext.quantityPrecision,
        lotSize: normalizedContext.lotSize,
    }) : scoped.activeContext ?? normalizeMarketSource(marketPayload.marketSource ?? marketPayload);
    const currentPayload = payloadOf(current);
    const currentTradeIdentity = {
        eventId: marketDisplayValue(currentPayload.currentTradeEventId ?? currentPayload.tradeEventId),
        tradeId: marketDisplayValue(currentPayload.currentTradeId ?? currentPayload.tradeId),
        sequence: finite(currentPayload.currentTradeSequence) ? currentPayload.currentTradeSequence : null,
        timestamp: marketTimestamp(currentPayload.currentTradeTimestamp),
        price: marketDisplayValue(currentPayload.currentTradePrice),
    };
    const headerValues = {
        symbol: source.exchangeSymbol === UNKNOWN ? marketPayload.symbol : source.exchangeSymbol,
        exchange: source.exchange,
        marketType: source.marketType,
        timestamp: current?.timestamp,
        markPrice: marketPayload.markPrice,
        lastTradePrice: lastTrade?.numericPrice ?? marketPayload.lastTradePrice,
        currentPrice: marketPayload.lastTradePrice ?? lastTrade?.numericPrice
            ?? payloadOf(current).price ?? midpointNumber,
        currentPriceSource: finite(marketPayload.lastTradePrice) || finite(lastTrade?.numericPrice)
            || finite(payloadOf(current).price) ? "LAST" : finite(midpointNumber) ? "MID" : "UNKNOWN",
        priceDirection: marketPayload.priceDirection ?? payloadOf(current).priceDirection ?? "UNKNOWN",
        dataQuality: projection.dataQuality ?? marketEvent?.dataQuality ?? UNKNOWN,
        sequence: current?.sequence,
        eventType: current?.eventType,
        progress: finite(projection.progress) ? `${projection.progress * 100}%` : DASH,
    };
    const hasContext = marketContextKey(source) !== null;
    const hasMarketData = finite(headerValues.currentPrice) || asks.valid.length > 0 || bids.valid.length > 0
        || tradeRows.length > 0 || Object.keys(metricValues).length > 0;
    const quality = marketDisplayValue(projection.dataQuality) === DASH ? UNKNOWN : projection.dataQuality;
    const liveBookUnavailable = useLiveBook && (
        ["UNAVAILABLE", "INVALID"].includes(normalizedMarketModel.status)
        || ["UNAVAILABLE", "INVALID"].includes(String(book.dataQuality ?? "").toUpperCase())
        || ["UNAVAILABLE", "UNSYNCED"].includes(String(book.syncState ?? "").toUpperCase())
    );
    const displaySymbol = source.displaySymbol !== UNKNOWN ? source.displaySymbol
        : source.exchangeSymbol !== UNKNOWN ? source.exchangeSymbol : source.canonicalSymbol;
    const summary = {
        exchange: hasContext ? source.exchange : DASH,
        marketType: hasContext ? source.marketType : DASH,
        exchangeSymbol: hasContext ? source.exchangeSymbol : DASH,
        normalizedSymbol: hasContext ? source.canonicalSymbol : DASH,
        displaySymbol: hasContext ? displaySymbol : DASH,
        currentPrice: formatMarketPrice(normalizedMarketModel?.price?.current ?? headerValues.currentPrice, source),
        bestBid: formatMarketPrice(normalizedMarketModel?.price?.bestBid ?? bestBidNumber, source),
        bestAsk: formatMarketPrice(normalizedMarketModel?.price?.bestAsk ?? bestAskNumber, source),
        spread: formatMarketPrice(normalizedMarketModel?.price?.spread ?? spreadNumber, source),
        state: normalizedPresentationState(normalizedMarketModel)
            ?? marketDataState({ replayEngine, source, hasContext, hasMarketData, quality, crossed: crossedBook }),
    };
    const bookHasData = asks.valid.length > 0 || bids.valid.length > 0;
    const machineState = replayEngine?.machine?.state;
    const orderBookState = !hasContext ? "NO MARKET SELECTED"
        : machineState === "REPLAY_LOADING" || machineState === "LOADING" ? "LOADING"
            : liveBookUnavailable || crossedBook || machineState === "REPLAY_ERROR" || quality === "INVALID" ? "UNAVAILABLE"
                : !bookHasData && asks.invalid + bids.invalid > 0 ? "UNAVAILABLE"
                    : !bookHasData ? "WAITING" : asks.valid.length === 0 || bids.valid.length === 0 ? "PARTIAL" : "AVAILABLE";
    const formatBookRows = (rows) => rows.map((row) => ({
        ...row,
        price: formatMarketPrice(row.numericPrice, source),
        size: formatMarketQuantity(row.numericSize, source),
        optionalTotal: formatMarketQuantity(row.numericCumulativeQuantity, source),
        cumulativeSize: formatMarketQuantity(row.numericCumulativeQuantity, source),
    }));
    const formattedTradeRows = tradeRows.map((trade) => ({
        ...trade,
        price: formatMarketPrice(trade.numericPrice, source),
        size: formatMarketQuantity(trade.numericSize, source),
    }));
    const tradeDataReceived = events.some((event) => Array.isArray(payloadOf(event).trades)
        || ["RECENT_TRADE", "TRADE"].includes(event?.eventType));
    const tradeState = !hasContext ? "NO MARKET SELECTED"
        : machineState === "REPLAY_LOADING" || machineState === "LOADING" ? "LOADING"
            : machineState === "REPLAY_ERROR" || quality === "INVALID" ? "UNAVAILABLE"
                : tradeRows.length > 0 ? "AVAILABLE"
                    : invalidTrades > 0 ? "UNAVAILABLE" : tradeDataReceived ? "NO TRADES" : "WAITING";
    const metrics = {
        buyPressure, sellPressure, pressureBalance,
        liquidity: metricValues.liquidity, momentum: metricValues.momentum,
        spread: metricValues.spread ?? spreadNumber, spreadPct: metricValues.spreadPct ?? spreadPctNumber,
        volatility: metricValues.volatility, absorption: metricValues.absorption,
        fakePressure: metricValues.fakePressure, spoofing: metricValues.spoofing, iceberg: metricValues.iceberg,
    };
    const missingFields = [headerValues.symbol, headerValues.exchange, headerValues.markPrice,
        metrics.buyPressure, metrics.sellPressure, metrics.liquidity, metrics.momentum, metrics.volatility]
        .filter((value) => marketDisplayValue(value) === DASH).length;

    return {
        normalizedMarketModel,
        source,
        marketContext: {
            exchange: source.exchange,
            marketType: source.marketType,
            exchangeSymbol: source.exchangeSymbol,
            normalizedSymbol: source.canonicalSymbol,
            displaySymbol,
            pricePrecision: source.pricePrecision,
            tickSize: source.tickSize,
            quantityPrecision: source.quantityPrecision,
            lotSize: source.lotSize,
            key: marketContextKey(source),
        },
        currentPriceSummary: summary,
        contextEventIds: events.map(({ id }) => id).filter((id) => typeof id === "string" && id),
        currentTradeIdentity,
        header: Object.fromEntries(Object.entries(headerValues).map(([key, value]) => [key,
            key === "timestamp" ? marketTimestamp(value)
                : ["markPrice", "lastTradePrice", "currentPrice"].includes(key)
                    ? formatMarketPrice(value, source) : marketDisplayValue(value)])),
        orderBook: {
            asks: formatBookRows(useLiveBook ? asks.valid : asks.rows), bids: formatBookRows(bids.rows),
            spread: formatMarketPrice(spreadNumber, source), spreadPct: marketDisplayValue(spreadPctNumber),
            bestAsk: formatMarketPrice(bestAskNumber, source), bestBid: formatMarketPrice(bestBidNumber, source),
            midpoint: formatMarketPrice(midpointNumber, source), totalAskQuantity: marketDisplayValue(totalAsk),
            totalBidQuantity: marketDisplayValue(totalBid),
            imbalance: marketDisplayValue(totalDepth === 0 ? null : (totalBid - totalAsk) / totalDepth),
            depth: asks.rows.length + bids.rows.length,
            timestamp: marketTimestamp(book.timestamp),
            sequence: finite(book.sequence) ? book.sequence : null,
            sourceDepth: Number.isInteger(book.depth) && book.depth >= 0 ? book.depth : null,
            dataQuality: marketDisplayValue(book.dataQuality),
            syncState: marketDisplayValue(book.syncState),
            state: orderBookState,
            hasData: bookHasData,
            crossed: crossedBook,
            locked: lockedBook,
        },
        recentTrades: {
            rows: formattedTradeRows, count: formattedTradeRows.length,
            buyCount: buyRows.length, sellCount: sellRows.length,
            buyQuantity: marketDisplayValue(buyQuantity), sellQuantity: marketDisplayValue(sellQuantity),
            totalQuantity: marketDisplayValue(totalQuantity),
            vwap: marketDisplayValue(totalQuantity === 0 ? null : notional / totalQuantity),
            lastTrade: marketDisplayValue(lastTrade?.numericPrice),
            state: tradeState,
            hasData: formattedTradeRows.length > 0,
        },
        metrics: Object.fromEntries(Object.entries(metrics).map(([key, value]) => [key, marketDisplayValue(value)])),
        quality: {
            market: marketDisplayValue(projection.dataQuality) === DASH ? UNKNOWN : projection.dataQuality,
            orderBook: qualityOf(bookEvent, book),
            trades: qualityOf(events.findLast((event) => tradeCandidates(event).length > 0), null),
            metrics: qualityOf(metric.sourceEvent, null),
        },
        diagnostics: {
            missingFields,
            invalidOrderBookRows: asks.invalid + bids.invalid,
            duplicateOrderBookPrices: asks.duplicatePrices + bids.duplicatePrices,
            invalidTradeRows: invalidTrades,
            duplicateTradeIds: allTrades.length - new Set(allTrades.filter(({ tradeId }) => tradeId !== DASH)
                .map(({ tradeId }) => tradeId)).size - allTrades.filter(({ tradeId }) => tradeId === DASH).length,
            duplicateTradeSequences: allTrades.length - new Set(allTrades.filter(({ sourceSequence }) => finite(sourceSequence))
                .map(({ sourceSequence }) => sourceSequence)).size - allTrades.filter(({ sourceSequence }) => !finite(sourceSequence)).length,
            truncatedAsks: asks.truncated,
            truncatedBids: bids.truncated,
            truncatedTrades: Math.max(0, allTrades.length - MAX_TRADES),
            sourceEventType: marketDisplayValue(marketEvent?.eventType),
            contextChanged: scoped.contextChanged,
            excludedContextEventCount: reachedEvents.length - events.length,
        },
        hasMarketData,
        isEmpty: !hasMarketData,
    };
}
