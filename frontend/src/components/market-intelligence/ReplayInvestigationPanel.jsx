import { useState } from "react";

const REPLAY_INVESTIGATION_TITLE_ID = "mi-replay-investigation-title";

export function ReplayInvestigationView({ expanded = false, onToggle = () => {}, children }) {
    return (
        <section aria-labelledby={REPLAY_INVESTIGATION_TITLE_ID} className="mi-replay-investigation">
            <header className="mi-replay-investigation__header">
                <button
                    aria-controls="mi-replay-investigation-content"
                    aria-expanded={expanded}
                    className="mi-replay-investigation__toggle"
                    onClick={onToggle}
                    type="button"
                >
                    <span aria-hidden="true" className="mi-replay-investigation__disclosure-icon">
                        {expanded ? "▼" : "▶"}
                    </span>
                    <span className="mi-replay-investigation__title" id={REPLAY_INVESTIGATION_TITLE_ID}>
                        REPLAY / INVESTIGATION
                    </span>
                </button>
            </header>
            {expanded && (
                <div className="mi-replay-investigation__content" id="mi-replay-investigation-content">
                    {children}
                </div>
            )}
        </section>
    );
}

export default function ReplayInvestigationPanel({ children, defaultCollapsed = true }) {
    const [expanded, setExpanded] = useState(!defaultCollapsed);
    return (
        <ReplayInvestigationView onToggle={() => setExpanded((value) => !value)} expanded={expanded}>
            {children}
        </ReplayInvestigationView>
    );
}
