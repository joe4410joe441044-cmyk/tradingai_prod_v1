import React from "react";
import { createRoot } from "react-dom/client";

import AutoMarketSelectionCard from "../../src/components/AutoMarketSelectionCard.jsx";
import "../../src/App.css";
import "../../src/index.css";
import "../../src/styles/dashboard.css";
import "../../src/styles/market-intelligence.css";

const status = {
    selectionMode: "AUTO",
    activeSymbol: "DYMUSDT",
    requestedSymbol: "XRPUSDTM",
    topCandidate: {
        symbol: "MEWUSDT",
        score: "0.91", spreadScore: "0.84", liquidityScore: "0.77", activityScore: "0.66",
    },
    autoRuntime: {
        mode: "LIVE_READ_ONLY",
        runtimeState: "OBSERVING",
        status: "IDLE",
        cycleId: "ams-cycle-0123456789abcdef0123456789abcdef",
        lastCycleStatus: "COMPLETED_BLOCKED",
        lastCycleId: "ams-cycle-9",
        evaluatedAt: "2026-09-26 22:44:44",
        reasonCodes: ["MM_STALE", "ELIGIBILITY_STALE", "CAPITAL_INELIGIBLE"],
    },
    scanner: {
        status: "READY", universeCount: 120, evaluatedCount: 120,
        eligibleCount: 7, rejectedCount: 113, evaluatedAt: "2026-09-26 22:44:41",
    },
    ranking: { status: "RANKED_CANDIDATES_AVAILABLE", rankedCount: 7 },
    switch: {
        state: "IDLE", previousSymbol: "DYMUSDT", proposedSymbol: "MEWUSDT",
        committedSymbol: "DYMUSDT", transactionId: "txn-0123456789abcdef", reasonCodes: [],
    },
    reasons: [],
    capitalEligibility: {
        status: "ELIGIBLE", availableCapital: "7.9184", riskBudget: "0.0396",
        remainingExposure: "0.0000", remainingPositionCapacity: "1",
        mmRegime: "CAPITAL_PROTECTION_STANDARD",
    },
    freshness: { universe: "FRESH", scanner: "FRESH", ranking: "FRESH", mm: "FRESH" },
};

createRoot(document.getElementById("root")).render(
    <div className="dashboard" style={{ width: "100%", minHeight: "100vh", padding: 16, background: "#070b11", boxSizing: "border-box" }}>
        <AutoMarketSelectionCard collapsible={true} status={status} onReselect={() => {}} />
    </div>,
);
