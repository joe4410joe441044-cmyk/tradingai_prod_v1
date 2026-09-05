import { useEffect, useState } from "react";
import { API } from "../../api";
import {
    authenticatedControlRequest,
    authErrorMessage,
    isAuthErrorStatus,
} from "../../features/auth/operatorAuth";
import {
    formatAmount,
    isAvailable,
} from "./accountRuntimeModel";

function PaperCapitalControl({
    paperBalance,
    realAvailableRaw,
    realConnected,
    realLoading,
    realStale,
    onPaperCapitalApplied,
}) {
    const [capitalExpanded, setCapitalExpanded] = useState(false);
    const [capitalInput, setCapitalInput] = useState("");
    const [capitalSource, setCapitalSource] = useState("DASHBOARD_MANUAL");
    const [capitalConfirming, setCapitalConfirming] = useState(false);
    const [capitalSubmitting, setCapitalSubmitting] = useState(false);
    const [capitalMessage, setCapitalMessage] = useState(null);
    const [capitalDirty, setCapitalDirty] = useState(false);

    useEffect(() => {
        if (!capitalDirty && isAvailable(paperBalance)) {
            setCapitalInput(String(paperBalance));
        }
    }, [capitalDirty, paperBalance]);

    const capitalNumber = Number(capitalInput);
    const capitalError = !capitalInput.trim()
        ? "Simulation capital is required."
        : !/^\d+(?:\.\d{1,2})?$/.test(capitalInput.trim())
            ? "Enter a valid amount with up to 2 decimal places."
            : !Number.isFinite(capitalNumber) || capitalNumber < 0.01
                ? "Simulation capital must be at least 0.01 USDT."
                : capitalNumber > 1_000_000_000
                    ? "Simulation capital must not exceed 1,000,000,000.00 USDT."
                    : null;

    const chooseCapital = (value, source = "DASHBOARD_MANUAL") => {
        setCapitalInput(String(value));
        setCapitalSource(source);
        setCapitalDirty(true);
        setCapitalConfirming(false);
        setCapitalMessage(null);
    };

    const submitPaperCapital = async () => {
        if (capitalSubmitting || capitalError) return;
        setCapitalSubmitting(true);
        setCapitalMessage(null);
        try {
            const response = await authenticatedControlRequest(API.paperAccountCapital(), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    capital: capitalInput.trim(),
                    source: capitalSource,
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                if (isAuthErrorStatus(response.status)) {
                    throw new Error(authErrorMessage(response.status));
                }
                throw new Error(payload.detail || "Unable to reset paper capital.");
            }
            if (onPaperCapitalApplied) await onPaperCapitalApplied();
            setCapitalDirty(false);
            setCapitalConfirming(false);
            setCapitalMessage({
                type: "success",
                text: `Paper simulation capital reset to ${formatAmount(payload.paperBalance)} USDT.`,
            });
        } catch (error) {
            setCapitalMessage({
                type: "error",
                text: `Unable to reset paper capital. Reason: ${error.message}`,
            });
        } finally {
            setCapitalSubmitting(false);
        }
    };

    const realAvailablePresetEnabled = realConnected
        && !realLoading
        && !realStale
        && Number.isFinite(Number(realAvailableRaw));

    return (
        <div className="paper-capital-control">
            <button
                type="button"
                className="paper-capital-toggle"
                aria-expanded={capitalExpanded}
                onClick={() => setCapitalExpanded((value) => !value)}
            >
                {capitalExpanded ? "▼" : "▶"} Set Paper Capital
            </button>
            {capitalExpanded && (
                <div className="paper-capital-panel">
                    <label htmlFor="simulation-capital-input">Simulation Capital (USDT)</label>
                    <input
                        id="simulation-capital-input"
                        inputMode="decimal"
                        value={capitalInput}
                        aria-invalid={Boolean(capitalError)}
                        onChange={(event) => chooseCapital(event.target.value)}
                    />
                    <div className="paper-capital-presets">
                        <button
                            type="button"
                            disabled={!realAvailablePresetEnabled}
                            title={realAvailablePresetEnabled ? "Copy current real available balance" : "REAL_ACCOUNT_NOT_SYNCED"}
                            onClick={() => chooseCapital(realAvailableRaw, "REAL_AVAILABLE_PRESET")}
                        >
                            Real Available
                        </button>
                        {["100", "1000", "10000"].map((preset) => (
                            <button type="button" key={preset} onClick={() => chooseCapital(preset)}>
                                {formatAmount(preset)}
                            </button>
                        ))}
                    </div>
                    {capitalError && capitalDirty && (
                        <p className="paper-capital-feedback error">{capitalError}</p>
                    )}
                    {!capitalConfirming ? (
                        <button
                            type="button"
                            className="paper-capital-apply"
                            disabled={Boolean(capitalError) || capitalSubmitting}
                            onClick={() => setCapitalConfirming(true)}
                        >
                            Apply Paper Capital
                        </button>
                    ) : (
                        <div className="paper-capital-confirm" role="alertdialog" aria-labelledby="paper-capital-confirm-title">
                            <strong id="paper-capital-confirm-title">Reset Paper Account?</strong>
                            <span>New Simulation Capital: {formatAmount(capitalNumber)} USDT</span>
                            <span>Balance, equity, PnL and paper positions will reset. Real funds are not affected.</span>
                            <div>
                                <button type="button" disabled={capitalSubmitting} onClick={() => setCapitalConfirming(false)}>Cancel</button>
                                <button type="button" disabled={capitalSubmitting} onClick={submitPaperCapital}>
                                    {capitalSubmitting ? "Applying…" : "Reset Paper Account"}
                                </button>
                            </div>
                        </div>
                    )}
                    <div className="paper-capital-live" aria-live="polite">
                        {capitalMessage && (
                            <p className={`paper-capital-feedback ${capitalMessage.type}`}>{capitalMessage.text}</p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export default PaperCapitalControl;
