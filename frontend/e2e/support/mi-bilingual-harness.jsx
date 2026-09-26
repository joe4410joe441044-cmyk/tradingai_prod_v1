import React from "react";
import { createRoot } from "react-dom/client";

import AutoMarketSelectionCard from "../../src/components/AutoMarketSelectionCard.jsx";
import { ReplayMarketViewContent } from "../../src/components/market-intelligence/ReplayMarketView.jsx";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../src/features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../src/features/market-intelligence/replay/replayFixtures.js";
import { buildReplayMarkerOverlayModel } from "../../src/features/market-intelligence/replay/replayMarkerOverlayModel.js";
import { buildReplayMarketViewModel } from "../../src/features/market-intelligence/replay/replayMarketViewModel.js";
import "../../src/App.css";
import "../../src/index.css";
import "../../src/styles/dashboard.css";
import "../../src/styles/market-intelligence.css";

const engine = applyReplayCommand(createInitialReplayEngineState(), {
    type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
});
const marketModel = buildReplayMarketViewModel(engine);
const markerModel = buildReplayMarkerOverlayModel(engine, marketModel);

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
    <div className="app-shell market-intelligence" style={{ minHeight: "100vh", background: "#070b11" }}>
        <div className="mi-page">
            <div style={{ display: "grid", gap: 12, gridTemplateColumns: "minmax(0, 1.15fr) minmax(0, 1fr)" }}>
                <ReplayMarketViewContent model={marketModel} markerModel={markerModel} />
                <AutoMarketSelectionCard collapsible={true} status={status} onReselect={() => {}} />
            </div>
        </div>
    </div>,
);
