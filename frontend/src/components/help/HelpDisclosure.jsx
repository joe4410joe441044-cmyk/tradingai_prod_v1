import { useState } from "react";

export default function HelpDisclosure({
    title,
    children,
    defaultOpen = false,
    open: controlledOpen,
    onToggle,
}) {
    const [internalOpen, setInternalOpen] = useState(defaultOpen);
    const isExpanded = typeof controlledOpen === "boolean" ? controlledOpen : internalOpen;
    const contentId = `ai-help-disclosure-${title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "")}`;

    function toggle() {
        if (typeof onToggle === "function") {
            onToggle(!isExpanded);
        } else {
            setInternalOpen((open) => !open);
        }
    }

    return (
        <section className="ai-help-disclosure">
            <button
                className="ai-help-disclosure__toggle"
                type="button"
                aria-expanded={isExpanded}
                aria-controls={contentId}
                onClick={toggle}
            >
                <span>{title}</span>
                <span aria-hidden="true">{isExpanded ? "−" : "+"}</span>
            </button>
            {isExpanded && (
                <div className="ai-help-disclosure__content" id={contentId}>
                    {children}
                </div>
            )}
        </section>
    );
}
