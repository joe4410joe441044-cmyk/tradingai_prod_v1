import { createNormalizedMarketModel, NORMALIZED_MARKET_ISSUES } from "./normalizedMarketModel.js";

export const isReplayMarketContextActive = (replayEngine) => Boolean(
    replayEngine?.dataset
    && replayEngine?.machine?.state !== "IDLE",
);

const sharedContext = (context) => context?.contextKey ? {
    exchange: context.exchange,
    marketType: context.marketType,
    exchangeSymbol: context.exchangeSymbol,
    normalizedSymbol: context.normalizedSymbol,
    displaySymbol: context.displaySymbol,
    contextKey: context.contextKey,
} : null;

export function resolveMarketContext({ dashboardContext, replayEngine, replayModel } = {}) {
    if (isReplayMarketContextActive(replayEngine) && replayModel?.context?.contextKey) {
        return { context: sharedContext(replayModel.context), mode: "REPLAY" };
    }
    return {
        context: sharedContext(dashboardContext),
        mode: dashboardContext?.contextKey ? "LIVE" : "NONE",
    };
}

export function createDashboardContextMarketModel(context) {
    return createNormalizedMarketModel({
        context,
        source: { mode: "LIVE", provider: "RUNTIME_WEBSOCKET" },
        currentPrice: null,
        orderBook: {},
        recentTrades: [],
        markers: [],
        issues: [
            NORMALIZED_MARKET_ISSUES.PRICE_UNAVAILABLE,
            NORMALIZED_MARKET_ISSUES.BOOK_UNAVAILABLE,
            NORMALIZED_MARKET_ISSUES.TRADES_UNAVAILABLE,
            NORMALIZED_MARKET_ISSUES.MARKERS_UNAVAILABLE,
            NORMALIZED_MARKET_ISSUES.SOURCE_TIMESTAMP_MISSING,
        ],
        status: context?.contextKey ? "WAITING" : "NO_MARKET",
    });
}

export function runtimeMarketMatchesContext(market, context) {
    const exchange = typeof market?.exchange === "string" ? market.exchange.trim().toUpperCase() : "";
    const symbol = typeof (market?.exchangeSymbol ?? market?.symbol) === "string"
        ? (market.exchangeSymbol ?? market.symbol).trim().toUpperCase() : "";
    if (!exchange || !symbol || !context?.contextKey) return false;
    if (exchange !== context.exchange?.toUpperCase()
        || symbol !== context.exchangeSymbol?.toUpperCase()) return false;
    const marketType = typeof market?.marketType === "string" ? market.marketType.trim().toUpperCase() : "";
    return !marketType || marketType === context.marketType?.toUpperCase();
}
