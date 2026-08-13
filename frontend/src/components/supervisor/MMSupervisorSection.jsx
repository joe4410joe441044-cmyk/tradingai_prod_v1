import { useState } from "react";

import SupervisorConversationShell from "./SupervisorConversationShell";

export default function MMSupervisorSection() {
    const [isExpanded, setIsExpanded] = useState(false);
    const contentId = "mm-supervisor-content";

    return (
        <section className="mm-supervisor" aria-labelledby="mm-supervisor-heading">
            <div className="mm-supervisor__summary">
                <div>
                    <p className="supervisor-page__section-kicker">SPECIALIST SUPERVISOR</p>
                    <h2 id="mm-supervisor-heading">MM SUPERVISOR</h2>
                    <p className="mm-supervisor__state">State: <strong>UNKNOWN</strong></p>
                </div>
                <button
                    className="supervisor-disclosure-button"
                    type="button"
                    aria-expanded={isExpanded}
                    aria-controls={contentId}
                    onClick={() => setIsExpanded((expanded) => !expanded)}
                >
                    {isExpanded ? "閉じる" : "開く"}
                    <span aria-hidden="true">{isExpanded ? "−" : "+"}</span>
                </button>
            </div>

            <div className="mm-supervisor__content" id={contentId} hidden={!isExpanded}>
                    <p className="supervisor-page__description">
                        資金管理、Risk、Drawdown、Exposure、Position Capacity、Compoundingについて質問できます。
                    </p>
                    <SupervisorConversationShell
                        supervisorName="MM Supervisor"
                        agentId="MM_SUPERVISOR"
                    />
            </div>
        </section>
    );
}
