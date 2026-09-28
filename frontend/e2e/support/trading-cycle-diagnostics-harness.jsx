import React from "react";
import { createRoot } from "react-dom/client";

import TradingDecisionCard from "../../src/components/runtime/TradingDecisionCard.jsx";
import { STAGES } from "../../src/components/runtime/tradingCycleModel.js";
import "../../src/App.css";
import "../../src/index.css";
import "../../src/styles/dashboard.css";

const buildStep = (index) => {
    if (index === 4) {
        return {
            index,
            key: "step-4",
            name: "Micro Edge Strategy",
            status: "BLOCKED",
            reasonCode: "LOW_COMPOSITE_SCORE",
            reasonText: "Micro Edge Strategy blocked entry: COMPOSITE_SCORE is 0.42, required >= 0.55",
            current: { edgeScore: 0.42, blockingCondition: "COMPOSITE_SCORE" },
            required: { minimumCompositeScore: 0.55 },
            comparison: "BLOCK",
            blockerType: "PARAMETER",
            actionable: "YES",
            relatedParameters: [
                { key: "minimumCompositeScore", currentSetting: 0.55, scope: "PAPER" },
            ],
            parameterLocation: { route: "/parameter-settings", anchor: null },
            nextCondition: "ENTRY_ALLOWED",
            nextStep: 5,
            source: "tradingDecision.entryReadiness",
            evaluatedAt: 1000,
            freshness: { state: "FRESH", ageSeconds: 0, evaluatedAt: 1000 },
        };
    }
    const future = index > 4;
    return {
        index,
        key: `step-${index}`,
        name: STAGES[index].label,
        status: index === 5 ? "BYPASSED" : future ? "WAITING" : "COMPLETED",
        reasonCode: future ? "STEP_OK" : "STEP_EVALUATED",
        reasonText: `Step ${index} reason`,
        current: index === 13 ? null : `current-${index}`,
        required: `required-${index}`,
        comparison: future ? "WAITING" : "PASS",
        blockerType: index === 5 ? "MODE" : "NONE",
        actionable: index === 5 ? "CONDITIONAL" : "NO",
        relatedParameters: [],
        nextCondition: `next-condition-${index}`,
        nextStep: index + 1,
        source: `test.source.${index}`,
        evaluatedAt: 1000,
        freshness: { state: "FRESH", ageSeconds: 0, evaluatedAt: 1000 },
    };
};

const diagnostics = {
    schemaVersion: 1,
    cycleState: "BLOCKED",
    rootBlocker: {
        step: 4,
        reasonCode: "LOW_COMPOSITE_SCORE",
        blockerType: "PARAMETER",
        source: "tradingDecision.entryReadiness",
        evaluatedAt: 1000,
    },
    rootBlockerStep: 4,
    steps: Array.from({ length: 15 }, (_, index) => buildStep(index)),
};

createRoot(document.getElementById("root")).render(
    <>
        <header className="app-header">
            <div className="status-strip">HARNESS STATUS STRIP</div>
        </header>
        <div className="dashboard" style={{ minHeight: "100vh" }}>
            <TradingDecisionCard
                decision={{ currentStageIndex: 4, currentActivity: "EVALUATING_STRATEGY" }}
                diagnostics={diagnostics}
            />
            <div style={{ height: 800 }} />
        </div>
    </>,
);
