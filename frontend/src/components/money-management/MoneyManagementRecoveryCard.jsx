import { useState } from "react";

import MoneyManagementCardShell from "./MoneyManagementCardShell";
import {
    formatMoneyManagementOperationalText,
} from "./MoneyManagementPrimitives";

export default function MoneyManagementRecoveryCard({
    interaction,
    isRecovering,
    onRecover,
}) {
    const [confirming, setConfirming] = useState(false);
    const recovery = interaction.recovery;

    const confirm = async () => {
        setConfirming(false);
        await onRecover();
    };

    return (
        <MoneyManagementCardShell
            className="mm-card--recovery"
            title="Recovery"
        >
            <dl className="mm-metric-list">
                <div className="mm-metric-row">
                    <dt>Recovery Availability</dt>
                    <dd>
                        {formatMoneyManagementOperationalText(
                            recovery.availability,
                        )}
                    </dd>
                </div>
                <div className="mm-metric-row">
                    <dt>Current Risk State</dt>
                    <dd>
                        {formatMoneyManagementOperationalText(
                            recovery.currentRiskState === "UNKNOWN"
                                ? "—"
                                : recovery.currentRiskState,
                        )}
                    </dd>
                </div>
                <div className="mm-metric-row">
                    <dt>Entry Permission</dt>
                    <dd>
                        {formatMoneyManagementOperationalText(
                            recovery.entryPermission,
                        )}
                    </dd>
                </div>
                <div className="mm-metric-row">
                    <dt>Recovery Preconditions</dt>
                    <dd>
                        {recovery.preconditions === "Not reported"
                            ? "—"
                            : recovery.preconditions}
                    </dd>
                </div>
            </dl>
            {recovery.errorCode === "RECOVERY_CONFLICT" ? (
                <div className="mm-operation-notice mm-operation-notice--danger" role="alert">
                    <strong>RECOVERY CONFLICT</strong>
                    <p>
                        Recovery could not be started because the runtime
                        state changed. Status has been refreshed. Review
                        the current state before retrying.
                    </p>
                </div>
            ) : recovery.errorMessage ? (
                <p className="mm-operation-notice mm-operation-notice--danger" role="alert">
                    {recovery.errorMessage}
                </p>
            ) : null}
            {recovery.result && (
                <section
                    aria-live="polite"
                    className="mm-recovery-result"
                >
                    <h3>Last Recovery Result</h3>
                    <dl>
                        <div>
                            <dt>Accepted</dt>
                            <dd>{recovery.result.accepted}</dd>
                        </div>
                        <div>
                            <dt>Recovered</dt>
                            <dd>{recovery.result.recovered}</dd>
                        </div>
                        <div>
                            <dt>Result</dt>
                            <dd>{recovery.result.result}</dd>
                        </div>
                        <div>
                            <dt>Updated</dt>
                            <dd>{recovery.result.updated}</dd>
                        </div>
                    </dl>
                </section>
            )}
            {confirming ? (
                <div
                    aria-label="Confirm recovery evaluation"
                    className="mm-recovery-confirmation"
                    role="group"
                >
                    <p>
                        Recovery evaluation may update the Money
                        Management state.
                    </p>
                    <div className="mm-action-row">
                        <button
                            disabled={isRecovering}
                            onClick={() => setConfirming(false)}
                            type="button"
                        >
                            Cancel
                        </button>
                        <button
                            disabled={isRecovering}
                            onClick={confirm}
                            type="button"
                        >
                            Confirm Recovery
                        </button>
                    </div>
                </div>
            ) : (
                <button
                    disabled={Boolean(recovery.disabledReason)}
                    onClick={() => setConfirming(true)}
                    title={recovery.disabledReason ?? "Run recovery evaluation"}
                    type="button"
                >
                    {isRecovering
                        ? "RECOVERY IN PROGRESS"
                        : "Run Recovery Evaluation"}
                </button>
            )}
        </MoneyManagementCardShell>
    );
}
