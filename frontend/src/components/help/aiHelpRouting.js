export const AI_ADVISOR_PATH = "/ai-advisor";
export const SUPERVISOR_PATH = "/supervisor";

export const AI_HELP_TARGETS = Object.freeze({
    master: Object.freeze({ path: SUPERVISOR_PATH, targetId: "master-supervisor-heading" }),
    mm: Object.freeze({ path: SUPERVISOR_PATH, targetId: "mm-supervisor-heading" }),
    advisor: Object.freeze({ path: AI_ADVISOR_PATH, targetId: "advisor-prompt" }),
});

const SCROLL_TARGET_KEY = "tradingai:ai-help-scroll-target";

export function setAiHelpScrollTarget(targetId) {
    try {
        window.sessionStorage.setItem(SCROLL_TARGET_KEY, targetId);
    } catch {
        /* storage unavailable */
    }
}

export function consumeAiHelpScrollTarget() {
    try {
        const targetId = window.sessionStorage.getItem(SCROLL_TARGET_KEY);
        if (targetId) window.sessionStorage.removeItem(SCROLL_TARGET_KEY);
        return targetId;
    } catch {
        return null;
    }
}

export function focusAiHelpTarget(targetId) {
    if (!targetId) return;
    if (typeof document === "undefined") return;
    const node = document.getElementById(targetId);
    if (!node) return;
    if (typeof node.scrollIntoView === "function") node.scrollIntoView({ block: "start" });
    if (typeof node.focus === "function") node.focus({ preventScroll: true });
}

export function navigateAiHelp(target, { onClose } = {}) {
    const spec = AI_HELP_TARGETS[target];
    if (!spec) return;
    onClose?.();
    const currentPath = typeof window !== "undefined" ? window.location.pathname : "/";
    if (currentPath === spec.path) {
        if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(() => focusAiHelpTarget(spec.targetId));
        } else {
            focusAiHelpTarget(spec.targetId);
        }
        return;
    }
    setAiHelpScrollTarget(spec.targetId);
    window.history.pushState({}, "", spec.path);
    window.dispatchEvent(new PopStateEvent("popstate"));
}
