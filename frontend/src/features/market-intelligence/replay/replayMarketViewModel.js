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
        sourceMode: safe(value.sourceMode), isSample: value.isSample === true,
    };
};

export const normalizedTradeTime = (value) => {
    if (typeof value !== "string" || !value.trim() || !Number.isFinite(Date.parse(value))) return "TIME UNKNOWN";
    const match = value.match(/T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?/);
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
        if (!finite(row.price) || !finite(row.quantity) || row.quantity < 0) {
            invalid += 1;
            continue;
        }
        valid.push({
            numericPrice: row.price,
            numericSize: row.quantity,
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
            optionalTotal: marketDisplayValue(cumulative),
            numericCumulativeQuantity: cumulative,
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
    if (!trade || typeof trade !== "object" || Array.isArray(trade)
        || !finite(trade.price) || !finite(trade.quantity) || trade.quantity < 0) return null;
    return {
        id: marketDisplayValue(trade.tradeId ?? trade.id) === DASH ? `${event?.id ?? "trade"}-${index}` : String(trade.tradeId ?? trade.id),
        eventId: marketDisplayValue(trade.eventId),
        timestamp: marketTimestamp(trade.timestamp ?? event?.timestamp),
        time: normalizedTradeTime(trade.timestamp ?? event?.timestamp),
        side: normalizeMarketSide(trade.side ?? trade.aggressor),
        aggressorSide: normalizeMarketSide(trade.aggressorSide ?? trade.aggressor),
        price: marketDisplayValue(trade.price),
        size: marketDisplayValue(trade.quantity),
        tradeId: marketDisplayValue(trade.tradeId ?? trade.id),
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

export function buildRecentTradesDisplay(recentTrades, currentIdentity, markers = [], rowLimit = 50) {
    const safeLimit = [20, 50, 100].includes(rowLimit) ? rowLimit : 50;
    const rows = (Array.isArray(recentTrades?.rows) ? recentTrades.rows : []).slice(0, safeLimit);
    const maxSize = rows.reduce((max, row) => finite(row.numericSize) ? Math.max(max, row.numericSize) : max, 0);
    const decorated = rows.map((row) => ({ ...row,
        intensity: maxSize > 0 ? Math.min(100, Math.max(0, row.numericSize / maxSize * 100)) : 0,
        isCurrent: identityMatch(row, currentIdentity),
        markers: (Array.isArray(markers) ? markers : []).filter((marker) => identityMatch(row, {
            eventId: marker.eventId ?? DASH, tradeId: marker.tradeId ?? DASH,
            sequence: marker.sourceSequence, timestamp: marker.timestamp ?? DASH, price: marker.price ?? DASH,
        })),
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

export function buildReplayMarketViewModel(replayEngine) {
    const projection = replayEngine?.projection && typeof replayEngine.projection === "object"
        ? replayEngine.projection : {};
    const current = projection.currentEvent && typeof projection.currentEvent === "object"
        ? projection.currentEvent : null;
    const visibleEvents = Array.isArray(projection.visibleEvents)
        ? projection.visibleEvents.filter((event) => event && typeof event === "object") : [];
    // currentEvent is itself an authoritative Projection value. Include it only as
    // a fallback for partial projections, without consulting the Dataset or Cursor.
    const events = current && !visibleEvents.includes(current)
        ? [...visibleEvents, current] : visibleEvents;
    const bookEvent = events.findLast((event) => {
        const payload = payloadOf(event);
        return payload.orderBook && typeof payload.orderBook === "object" && !Array.isArray(payload.orderBook)
            || Array.isArray(payload.asks) || Array.isArray(payload.bids);
    }) ?? null;
    const bookPayload = payloadOf(bookEvent);
    const book = bookPayload.orderBook && typeof bookPayload.orderBook === "object"
        && !Array.isArray(bookPayload.orderBook) ? bookPayload.orderBook : bookPayload;
    const asks = normalizeBookSide(book.asks, "ASK");
    const bids = normalizeBookSide(book.bids, "BID");
    const bestAskNumber = asks.valid.length ? Math.min(...asks.valid.map(({ numericPrice }) => numericPrice)) : null;
    const bestBidNumber = bids.valid.length ? Math.max(...bids.valid.map(({ numericPrice }) => numericPrice)) : null;
    const midpointNumber = finite(bestAskNumber) && finite(bestBidNumber) ? (bestAskNumber + bestBidNumber) / 2 : null;
    const payloadSpread = finite(book.spread) ? book.spread : finite(bookPayload.spread) ? bookPayload.spread : null;
    const spreadNumber = finite(bestAskNumber) && finite(bestBidNumber)
        ? Number((bestAskNumber - bestBidNumber).toPrecision(12)) : payloadSpread;
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
    const source = normalizeMarketSource(marketPayload.marketSource ?? marketPayload);
    const currentPayload = payloadOf(current);
    const currentTradeIdentity = {
        eventId: marketDisplayValue(currentPayload.currentTradeEventId ?? currentPayload.tradeEventId),
        tradeId: marketDisplayValue(currentPayload.currentTradeId ?? currentPayload.tradeId),
        sequence: finite(currentPayload.currentTradeSequence) ? currentPayload.currentTradeSequence : null,
        timestamp: marketTimestamp(currentPayload.currentTradeTimestamp),
        price: marketDisplayValue(currentPayload.currentTradePrice),
    };
    const headerValues = {
        symbol: marketPayload.symbol,
        exchange: marketPayload.exchange,
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
        source,
        currentTradeIdentity,
        header: Object.fromEntries(Object.entries(headerValues).map(([key, value]) => [key,
            key === "timestamp" ? marketTimestamp(value) : marketDisplayValue(value)])),
        orderBook: {
            asks: asks.rows, bids: bids.rows,
            spread: marketDisplayValue(spreadNumber), spreadPct: marketDisplayValue(spreadPctNumber),
            bestAsk: marketDisplayValue(bestAskNumber), bestBid: marketDisplayValue(bestBidNumber),
            midpoint: marketDisplayValue(midpointNumber), totalAskQuantity: marketDisplayValue(totalAsk),
            totalBidQuantity: marketDisplayValue(totalBid),
            imbalance: marketDisplayValue(totalDepth === 0 ? null : (totalBid - totalAsk) / totalDepth),
            depth: asks.rows.length + bids.rows.length,
        },
        recentTrades: {
            rows: tradeRows, count: tradeRows.length, buyCount: buyRows.length, sellCount: sellRows.length,
            buyQuantity: marketDisplayValue(buyQuantity), sellQuantity: marketDisplayValue(sellQuantity),
            totalQuantity: marketDisplayValue(totalQuantity),
            vwap: marketDisplayValue(totalQuantity === 0 ? null : notional / totalQuantity),
            lastTrade: marketDisplayValue(lastTrade?.numericPrice),
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
        },
        hasMarketData: Boolean(marketEvent || bookEvent || allTrades.length || metric.sourceEvent),
        isEmpty: !(marketEvent || bookEvent || allTrades.length || metric.sourceEvent),
    };
}
