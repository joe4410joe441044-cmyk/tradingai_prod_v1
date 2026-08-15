import { useState } from "react";
import SupervisorHistoryPanel from "../../features/supervisor/history/SupervisorHistoryPanel";
import SupervisorSnapshotPanel from "./SupervisorSnapshotPanel";

export default function SupervisorDetailsDisclosure() {
    const [isExpanded, setIsExpanded] = useState(false);
    const contentId = "supervisor-details-content";

    return (
        <section className="supervisor-details" aria-labelledby="supervisor-details-heading">
            <div className="supervisor-details__summary">
                <div>
                    <p className="supervisor-page__section-kicker">ON DEMAND</p>
                    <h2 id="supervisor-details-heading">Details</h2>
                </div>
                <button
                    className="supervisor-disclosure-button"
                    type="button"
                    aria-expanded={isExpanded}
                    aria-controls={contentId}
                    onClick={() => setIsExpanded((expanded) => !expanded)}
                >
                    {isExpanded ? "詳細を閉じる" : "詳細を開く"}
                    <span aria-hidden="true">{isExpanded ? "−" : "+"}</span>
                </button>
            </div>

            {isExpanded && (
                <div className="supervisor-details__content" id={contentId}>
                    <SupervisorSnapshotPanel />
                    <SupervisorHistoryPanel />
                </div>
            )}
        </section>
    );
}
