import React from "react";
import { createRoot } from "react-dom/client";
import { AccountStatusView } from "../../src/pages/AccountStatusPage.jsx";
import "../../src/index.css";
import "../../src/App.css";
import "../../src/styles/dashboard.css";

/* Deterministic fixture: PAPER and REAL values are deliberately different so
   the E2E can prove the switch changes the rendered source without any
   network mutation. Runtime stays PAPER while ACCOUNT VIEW may be REAL. */
const paperPosition = {
    status: "OPEN", mode: "PAPER", control: "BOT", symbol: "PAPERPOSUSDT", side: "LONG",
    orderSide: "BUY", quantity: 6174, quantityUnit: "coin", coinQuantity: 6174, contractQuantity: 12,
    entryPrice: 0.016195, markPrice: 0.016195, unrealizedPnl: 10, positionValue: 100,
    holdingMs: 643, source: "PAPER_SIMULATION", freshness: "FRESH",
};
const livePosition = {
    status: "OPEN", mode: "LIVE", control: "MANUAL", symbol: "REALPOSUSDTM", side: "SHORT",
    orderSide: "SELL", quantity: 5, quantityUnit: "contract", coinQuantity: null, contractQuantity: 5,
    entryPrice: 2, markPrice: 1.9, unrealizedPnl: -0.5, positionValue: 9.5, leverage: 5,
    marginUsed: 2, liquidationPrice: 1.2, holdingMs: 1200, source: "KUCOIN_FUTURES", freshness: "FRESH",
};
const paperEvent = {
    event: "CLOSED", mode: "PAPER", control: "BOT", symbol: "PAPEREVENT", side: "LONG",
    quantity: 1, quantityUnit: "coin", entryPrice: 1, exitPrice: 1.05, realizedPnl: 5,
    holdingMs: 643, exitReason: "TAKE_PROFIT", tradeId: "PAPER-1",
    source: "PARAMETER_PERFORMANCE_TRADE_HISTORY", realizedPnlAuthoritative: true,
};
const liveEvent = {
    event: "CLOSED", mode: "LIVE", control: "MANUAL", symbol: "REALEVENT", side: "SHORT",
    quantity: 2, quantityUnit: "coin", entryPrice: 2, exitPrice: 1.9, realizedPnl: -3,
    holdingMs: 1200, exitReason: "STOP_LOSS", tradeId: "LIVE-1",
    source: "PARAMETER_PERFORMANCE_TRADE_HISTORY", realizedPnlAuthoritative: true,
};

const botStatus = {
    selectedMode: "PAPER",
    exchange: "kucoin",
    executionMode: "SIMULATION",
    realOrderAllowed: false,
    executionEntryAllowed: false,
    liveOrderEntryAllowed: false,
    executionEnabled: false,
    botState: "STOPPED",
    pendingOrder: false,
    accountRuntime: {
        paperAccount: {
            balance: 10000, equity: 10000, availableBalance: 9800, positions: [],
            totalPnl: 42, realizedPnl: 42, unrealizedPnl: 0,
            source: "PAPER_SIMULATION", positionState: "FLAT", available: true,
        },
        realAccount: {
            exchange: "kucoin", accountType: "KUCOIN_FUTURES", connected: true, authenticated: true,
            apiKeyPresent: true, permission: "READ_ONLY", balance: 7.92, equity: 7.92,
            availableBalance: 5.42, walletBalance: 7.92, unrealizedPnl: 1.23,
            realizedPnlToday: 0.5, totalPnlToday: 1.73, marginUsed: 0, marginAvailable: 7.92,
            marginRatio: 5, positions: [], positionSummary: "FLAT", lastSync: 1790728279,
            stale: false, loading: false,
        },
        positionsByMode: { PAPER: paperPosition, LIVE: livePosition },
        lastPositionEventsByMode: { PAPER: paperEvent, LIVE: liveEvent },
        currentPosition: paperPosition,
        lastPositionEvent: paperEvent,
        execution: { selectedMode: "PAPER", executionMode: "SIMULATION", realOrderAllowed: false },
        connection: {
            exchange: "kucoin", connected: true, authenticated: true,
            apiKeyStatus: "VERIFIED", permission: "READ_ONLY",
        },
    },
};

// Isolated header fixtures retain the contradictory legacy FLAT account snapshot.
const scenario = new URLSearchParams(location.search).get("position");
if (["stale", "flat", "unknown"].includes(scenario)) {
    for (const mode of ["PAPER", "LIVE"]) {
        botStatus.accountRuntime.positionsByMode[mode] = {
            mode, status: scenario === "flat" ? "FLAT" : "UNKNOWN",
            freshness: scenario === "stale" ? "STALE" : "FRESH",
            reason: scenario === "stale" ? "STALE_SOURCE" : undefined,
            quantity: null, positions: [],
        };
    }
}

const root = createRoot(document.getElementById("root"));
const render = (accountView) => root.render(
    <div className="dashboard">
        <AccountStatusView
            botStatus={botStatus}
            accountView={accountView}
            onAccountViewChange={render}
        />
    </div>,
);

render("PAPER");
