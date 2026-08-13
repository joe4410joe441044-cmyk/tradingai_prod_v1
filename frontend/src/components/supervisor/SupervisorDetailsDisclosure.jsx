import { useState } from "react";
import SupervisorHistoryPanel from "../../features/supervisor/history/SupervisorHistoryPanel";
import SupervisorSnapshotPanel from "./SupervisorSnapshotPanel";

const DETAIL_SECTIONS = [
    "MM Assessment",
    "Reasons and Recovery Conditions",
    "Current Settings",
    "Numeric Evidence",
    "System / Runtime",
    "Diagnostics",
];

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
                    {DETAIL_SECTIONS.map((title) => (
                        <section key={title}>
                            <h3>{title}</h3>
                            <p>NOT CONNECTED</p>
                        </section>
                    ))}
                </div>
            )}
        </section>
    );
}
