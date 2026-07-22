const positionId = "position-xrpusdtm-001";
const decisionId = "decision-xrpusdtm-001";

const event = (sequence, eventType, source, timestamp, payload, references = {}) => ({
    id: `replay-event-${String(sequence).padStart(3, "0")}`,
    timestamp,
    sequence,
    eventType,
    source,
    positionId: references.positionId ?? null,
    decisionId: references.decisionId ?? null,
    markerId: references.markerId ?? null,
    stationId: references.stationId ?? null,
    payload,
    dataQuality: "VALID",
});

const deepFreeze = (value) => {
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
        Object.freeze(value);
        Object.values(value).forEach(deepFreeze);
    }
    return value;
};

export const XRP_REPLAY_FIXTURE = deepFreeze({
    datasetId: "replay-xrpusdtm-paper-001",
    symbol: "XRPUSDTM",
    exchange: "KUCOIN",
    marketType: "FUTURES",
    exchangeSymbol: "XRPUSDTM",
    canonicalSymbol: "XRPUSDT",
    tradeMode: "PAPER",
    startedAt: "2026-07-20T12:00:00.000Z",
    endedAt: "2026-07-20T12:01:30.000Z",
    events: [
        event(1, "MARKET_SNAPSHOT", "MARKET", "2026-07-20T12:00:00.000Z", {
            symbol: "XRPUSDTM",
            exchange: "KUCOIN",
            marketType: "FUTURES",
            exchangeSymbol: "XRPUSDTM",
            canonicalSymbol: "XRPUSDT",
            sourceMode: "REPLAY",
            isSample: true,
            markPrice: 0.6124,
            lastTradePrice: 0.6124,
            bestBid: 0.6123,
            bestAsk: 0.6125,
            spread: 0.0002,
            volatility: 0.18,
            buyPressure: 0.58,
            sellPressure: 0.42,
            liquidity: 0.81,
            momentum: 0.36,
            markerType: "BUY",
            side: "BUY",
            price: 0.6123,
            quantity: 80,
            tradeId: "trade-current",
            currentTradeId: "trade-current",
            orderBook: {
                asks: [
                    [0.6125, 130], [0.6126, 210], [0.6127, 95], [0.6128, 175],
                    [0.6129, 320], [0.613, 140], [0.6131, 260], [0.6132, 110],
                    [0.6133, 185], [0.6134, 920], [0.6135, 240], [0.6136, 155],
                ],
                bids: [
                    [0.6123, 160], [0.6122, 190], [0.6121, 125], [0.612, 220],
                    [0.6119, 310], [0.6118, 145], [0.6117, 275], [0.6116, 105],
                    [0.6115, 195], [0.6114, 840], [0.6113, 235], [0.6112, 150],
                ],
                dataQuality: "VALID",
            },
            trades: [
                { tradeId: "trade-boundary", sequence: 77, timestamp: "2026-07-20T11:59:40Z", price: 0, quantity: 0 },
                { tradeId: "trade-002", sequence: 78, timestamp: "2026-07-20T11:59:41.110Z", side: "SELL", price: 0.6118, quantity: 25 },
                { tradeId: "trade-003", sequence: 79, timestamp: "2026-07-20T11:59:42.220Z", side: "BUY", price: 0.6119, quantity: 75 },
                { tradeId: "trade-004", sequence: 80, timestamp: "2026-07-20T11:59:43.330Z", side: "SELL", price: 0.6118, quantity: 140 },
                { tradeId: "trade-005", sequence: 81, timestamp: "2026-07-20T11:59:44.440Z", side: "UNKNOWN", price: 0.612, quantity: 10 },
                { tradeId: "trade-006", sequence: 82, timestamp: "2026-07-20T11:59:45.550Z", side: "BUY", price: 0.6121, quantity: 420 },
                { tradeId: "trade-007", sequence: 83, timestamp: "2026-07-20T11:59:46.660Z", side: "SELL", price: 0.612, quantity: 95 },
                { tradeId: "trade-008", sequence: 84, timestamp: "2026-07-20T11:59:47.770Z", side: "BUY", price: 0.6122, quantity: 5800 },
                { tradeId: "trade-009", sequence: 85, timestamp: "2026-07-20T11:59:48.880Z", side: "SELL", price: 0.6121, quantity: 230 },
                { tradeId: "trade-010", sequence: 86, timestamp: "2026-07-20T11:59:49.990Z", side: "BUY", price: 0.6122, quantity: 55 },
                { tradeId: "trade-011", sequence: 87, timestamp: "2026-07-20T11:59:50.100Z", price: 0.6122, quantity: 12 },
                { tradeId: "trade-012", sequence: 88, timestamp: "2026-07-20T11:59:51.210Z", side: "SELL", price: 0.6121, quantity: 320 },
                { tradeId: "trade-013", sequence: 89, timestamp: "2026-07-20T11:59:52.320Z", side: "BUY", price: 0.6123, quantity: 180 },
                { tradeId: "trade-014", sequence: 90, timestamp: "2026-07-20T11:59:53.430Z", side: "SELL", price: 0.6122, quantity: 65 },
                { tradeId: "trade-015", sequence: 91, timestamp: "2026-07-20T11:59:54.540Z", side: "BUY", price: 0.6123, quantity: 880 },
                { tradeId: "trade-016", sequence: 92, timestamp: "2026-07-20T11:59:55.650Z", side: "SELL", price: 0.6122, quantity: 35 },
                { tradeId: "trade-017", sequence: 93, timestamp: "2026-07-20T11:59:56.760Z", side: "BUY", price: 0.6124, quantity: 1250 },
                { tradeId: "trade-018", sequence: 94, timestamp: "2026-07-20T11:59:57.870Z", side: "SELL", price: 0.6123, quantity: 210 },
                { tradeId: "trade-019", sequence: 95, timestamp: "2026-07-20T11:59:58.980Z", side: "BUY", price: 0.6124, quantity: 80 },
                { tradeId: "trade-020", sequence: 96, timestamp: "2026-07-20T11:59:59.100Z", side: "SELL", price: 0.6123, quantity: 55 },
                { tradeId: "trade-021", sequence: 97, timestamp: "2026-07-20T11:59:59.500Z", side: "BUY", price: 0.6124, quantity: 260 },
                { tradeId: "trade-022", sequence: 98, timestamp: "2026-07-20T11:59:59.900Z", side: "SELL", price: 0.6123, quantity: 160 },
                { tradeId: "trade-same-time-low", sequence: 99, timestamp: "2026-07-20T12:00:00.000Z", side: "SELL", price: 0.6122, quantity: 40 },
                { tradeId: "trade-current", sequence: 100, timestamp: "2026-07-20T12:00:00.000Z", side: "BUY", price: 0.6123, quantity: 80 },
            ],
        }, { markerId: "marker-market-001" }),
        event(2, "DETECTOR_SIGNAL", "DETECTOR", "2026-07-20T12:00:05.000Z", {
            signal: "MOMENTUM_BREAKOUT",
            confidence: 0.78,
        }, { decisionId, stationId: "detector" }),
        event(3, "STRATEGY_DECISION", "STRATEGY", "2026-07-20T12:00:10.000Z", {
            direction: "LONG",
            result: "PROPOSED",
        }, { decisionId, stationId: "python-strategy" }),
        event(4, "AI_DECISION", "AI", "2026-07-20T12:00:15.000Z", {
            direction: "LONG",
            confidence: 0.82,
        }, { decisionId, stationId: "ai-final-decision" }),
        event(5, "GOVERNANCE_DECISION", "GOVERNANCE", "2026-07-20T12:00:20.000Z", {
            outcome: "APPROVED",
        }, { decisionId, stationId: "governance" }),
        event(6, "ORDER_SUBMITTED", "EXECUTION", "2026-07-20T12:00:25.000Z", {
            clientOrderId: "paper-order-001",
            side: "BUY",
        }, { decisionId, stationId: "execution" }),
        event(7, "ORDER_ACKNOWLEDGED", "EXECUTION", "2026-07-20T12:00:27.000Z", {
            clientOrderId: "paper-order-001",
            status: "ACKNOWLEDGED",
        }, { decisionId, stationId: "execution" }),
        event(8, "POSITION_OPENED", "POSITION", "2026-07-20T12:00:30.000Z", {
            markerType: "ENTRY",
            side: "LONG",
            price: 0.613,
            entryPrice: 0.613,
            quantity: 100,
        }, { positionId, decisionId, markerId: "marker-position-opened" }),
        event(9, "POSITION_UPDATED", "POSITION", "2026-07-20T12:01:00.000Z", {
            markPrice: 0.6151,
            unrealizedPnl: 0.21,
        }, { positionId, decisionId }),
        event(10, "POSITION_CLOSED", "POSITION", "2026-07-20T12:01:30.000Z", {
            markerType: "EXIT",
            side: "SELL",
            price: 0.616,
            exitPrice: 0.616,
            realizedPnl: 0.3,
            reason: "TARGET_REACHED",
        }, { positionId, decisionId, markerId: "marker-position-closed" }),
    ],
    metadata: {
        fixtureVersion: 1,
        description: "Static paper-trade replay for Timeline and Railway development.",
    },
});
