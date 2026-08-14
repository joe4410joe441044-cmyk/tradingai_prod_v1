import {
    useState,
} from "react";

import RuntimeOverviewPanel from "./RuntimeOverviewPanel";
import DecisionFlowPanel from "./DecisionFlowPanel";
import DiagnosticsPanel from "./DiagnosticsPanel";
import RuntimeTimelinePanel from "./RuntimeTimelinePanel";
import StageInspectorPanel from "./StageInspectorPanel";

const DISCLOSURE_PANEL_ID = "runtime-diagnostics-panel";

export default function RuntimeDiagnosticsDisclosure({
    runtimeHealth,
    displayedHealth,
    displayedBlockingReason,
    browserWsConnected,
    selectedStageId,
    onSelectStage,
    selectedStage,
}) {
    const [open, setOpen] = useState(false);

    return (
        <section
            className="runtime-diagnostics-disclosure"
            data-testid="runtime-diagnostics-disclosure"
        >
            <button
                aria-controls={DISCLOSURE_PANEL_ID}
                aria-expanded={open}
                className="runtime-diagnostics-toggle"
                onClick={() => setOpen((value) => !value)}
                type="button"
            >
                <span
                    aria-hidden="true"
                    className="runtime-diagnostics-chevron"
                >
                    {open ? "▼" : "▶"}
                </span>

                <span className="runtime-diagnostics-title">
                    RUNTIME &amp; DIAGNOSTICS
                </span>

                <span
                    aria-hidden="true"
                    className="runtime-diagnostics-state"
                >
                    {open ? "EXPANDED" : "COLLAPSED"}
                </span>
            </button>

            <div
                className="runtime-diagnostics-panel"
                hidden={!open}
                id={DISCLOSURE_PANEL_ID}
            >
                <RuntimeOverviewPanel
                    runtimeHealth={runtimeHealth}
                    displayedHealth={displayedHealth}
                    displayedBlockingReason={displayedBlockingReason}
                    browserWsConnected={browserWsConnected}
                />

                <DecisionFlowPanel runtimeHealth={runtimeHealth} />

                <StageInspectorPanel stage={selectedStage} />

                <RuntimeTimelinePanel events={runtimeHealth.timeline} />

                <DiagnosticsPanel
                    runtimeHealth={runtimeHealth}
                    displayedBlockingReason={displayedBlockingReason}
                />
            </div>
        </section>
    );
}
