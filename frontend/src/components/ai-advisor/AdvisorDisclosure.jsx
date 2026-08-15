import { useState } from "react";

export default function AdvisorDisclosure({ title, kicker, children }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const contentId = `advisor-disclosure-${title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "")}`;

    return (
        <section className="advisor-disclosure" aria-labelledby={`${contentId}-heading`}>
            <div className="advisor-disclosure__summary">
                <div>
                    {kicker && (
                        <p className="advisor-disclosure__kicker">{kicker}</p>
                    )}
                    <h2 id={`${contentId}-heading`}>{title}</h2>
                </div>
                <button
                    aria-controls={contentId}
                    aria-expanded={isExpanded}
                    className="advisor-disclosure__toggle"
                    onClick={() => setIsExpanded((expanded) => !expanded)}
                    type="button"
                >
                    {isExpanded ? "Collapse（閉じる）" : "Expand（開く）"}
                    <span aria-hidden="true">{isExpanded ? "−" : "+"}</span>
                </button>
            </div>

            {isExpanded && (
                <div className="advisor-disclosure__content" id={contentId}>
                    {children}
                </div>
            )}
        </section>
    );
}
