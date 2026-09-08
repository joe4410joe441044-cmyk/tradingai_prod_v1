import { useEffect, useState } from "react";

import { getSupervisorSnapshot } from "../../api/supervisorClient";

import SupervisorConversationShell from "./SupervisorConversationShell";

const KNOWN_MM_STATES = new Set([
    "NORMAL",
    "CAUTION",
    "DEFENSIVE",
    "LOCKED",
    "RECOVERY_25",
    "RECOVERY_50",
]);

function deriveMMState(snapshot) {
    const raw = snapshot?.moneyManagement?.ruinGuardStatus;
    if (typeof raw === "string" && KNOWN_MM_STATES.has(raw.trim().toUpperCase())) {
        return raw.trim().toUpperCase();
    }
    return "UNKNOWN";
}

export default function MMSupervisorSection({ onRequestSupervisorHelp }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const [state, setState] = useState("UNKNOWN");
    const contentId = "mm-supervisor-content";

    useEffect(() => {
        let active = true;
        getSupervisorSnapshot()
            .then((next) => {
                if (active) setState(deriveMMState(next));
            })
            .catch(() => {
                if (active) setState("UNKNOWN");
            });
        return () => {
            active = false;
        };
    }, []);

    return (
        <section className="mm-supervisor" aria-labelledby="mm-supervisor-heading">
            <div className="mm-supervisor__summary">
                <div>
                    <p className="supervisor-page__section-kicker">SPECIALIST SUPERVISOR</p>
                    <div className="supervisor-page__section-heading-text">
                        <h2 id="mm-supervisor-heading" tabIndex={-1}>MM SUPERVISOR</h2>
                        {typeof onRequestSupervisorHelp === "function" && (
                            <button
                                type="button"
                                className="supervisor-heading-help"
                                aria-label="MM Supervisor ヘルプを開く"
                                onClick={() => onRequestSupervisorHelp("mm")}
                            >
                                ?
                            </button>
                        )}
                    </div>
                    <p className="mm-supervisor__state">State: <strong>{state}</strong></p>
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
