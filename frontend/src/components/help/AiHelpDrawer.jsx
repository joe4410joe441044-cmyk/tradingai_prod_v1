import { useEffect, useRef } from "react";

export default function AiHelpDrawer({ id, side, open, title, onClose, children }) {
    const panelRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        function onKeyDown(event) {
            if (event.key === "Escape") onClose();
        }
        document.addEventListener("keydown", onKeyDown);
        const previouslyFocused = document.activeElement;
        panelRef.current?.focus();
        return () => {
            document.removeEventListener("keydown", onKeyDown);
            previouslyFocused?.focus?.();
        };
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div className={`ai-help-overlay ai-help-overlay--${side}`} onMouseDown={onClose}>
            <aside
                ref={panelRef}
                className={`ai-help-drawer ai-help-drawer--${side}`}
                id={id}
                role="dialog"
                aria-modal="true"
                aria-labelledby={`${id}-title`}
                tabIndex={-1}
                onMouseDown={(event) => event.stopPropagation()}
            >
                <header className="ai-help-drawer__header">
                    <h2 className="ai-help-drawer__title" id={`${id}-title`}>{title}</h2>
                    <button
                        type="button"
                        className="ai-help-drawer__close"
                        aria-label="ヘルプを閉じる"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </header>
                <div className="ai-help-drawer__body">{children}</div>
            </aside>
        </div>
    );
}
