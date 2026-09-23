// SAVE SETTINGS authority boundary (pure decision core).
//
// This module encodes the SAVE SETTINGS contract in a pure, testable form:
//   1. Validate the draft mode and symbol.
//   2. For LIVE, refresh the authoritative LIVE account context via the
//      caller-supplied read-only function. A failed refresh aborts the save
//      WITHOUT committing a revision (no partial mode/capital mix).
//   3. It performs NO runtime / order mutation — it never starts the runtime,
//      arms execution, creates an order, cancels an order, or mutates a
//      position. The only side effect it can trigger is the injected read.
//
// The caller (Dashboard) owns the actual commit (draft -> saved revision) and
// the transient UI state, and only commits when this returns { ok: true }.

export const SAVE_SETTINGS_CODES = Object.freeze({
    INVALID_MODE: "INVALID_MODE",
    INVALID_SYMBOL: "INVALID_SYMBOL",
    LIVE_ACCOUNT_CONTEXT_UNAVAILABLE: "LIVE_ACCOUNT_CONTEXT_UNAVAILABLE",
});

export const performSaveSettings = async ({
    draft = {},
    refreshLiveContext = async () => {},
} = {}) => {
    const mode = String(draft?.mode ?? "").trim().toUpperCase();
    if (mode !== "PAPER" && mode !== "LIVE") {
        return { ok: false, code: SAVE_SETTINGS_CODES.INVALID_MODE };
    }

    const symbol = String(draft?.symbol ?? "").trim().toUpperCase();
    if (!symbol) {
        return { ok: false, code: SAVE_SETTINGS_CODES.INVALID_SYMBOL };
    }

    if (mode === "LIVE") {
        try {
            await refreshLiveContext();
        } catch {
            return {
                ok: false,
                code: SAVE_SETTINGS_CODES.LIVE_ACCOUNT_CONTEXT_UNAVAILABLE,
            };
        }
    }

    return { ok: true };
};
