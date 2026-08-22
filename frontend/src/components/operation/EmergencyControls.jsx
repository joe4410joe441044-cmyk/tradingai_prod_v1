import { useState } from "react";

export default function EmergencyControls({
  emergencyState = "UNKNOWN",
  emergencyPath = "",
  emergencyError,
  unlockError,
  lastResultMessage,
  emergencyLocked,
  emergencyConfirmOpen = false,
  emergencyPending = false,
  unlockPending = false,
  unlockAllowed,
  emergencyButtonDisabled,
  emergencyLockValue,
  emergencyLockClass,
  openEmergencyConfirm,
  cancelEmergencyConfirm,
  confirmEmergency,
  handleReturnToNormal,
  lockedFacts = [],
  actionWarnings = [],
}) {
  const emergencyStateCode = String(emergencyState ?? "UNKNOWN").trim().toUpperCase();

  const emergencyStateCopy = {
    READY: {
      label: "READY",
      text: "緊急停止は作動していません",
      tone: "ready",
    },
    PROCESSING: {
      label: "PROCESSING",
      text: "緊急停止処理を実行中です",
      tone: "processing",
    },
    LOCKED: {
      label: "STOPPED SAFELY",
      text: "緊急停止が正常に完了しました",
      tone: "locked",
    },
    ACTION_REQUIRED: {
      label: "ACTION REQUIRED",
      text: "緊急停止は一部完了、失敗、または確認不能です",
      tone: "action",
    },
    FAILED: {
      label: "FAILED",
      text: "緊急停止処理に失敗しました",
      tone: "action",
    },
    PARTIAL: {
      label: "PARTIAL",
      text: "緊急停止処理は一部完了しました",
      tone: "action",
    },
    STATE_UNKNOWN: {
      label: "STATE UNKNOWN",
      text: "緊急停止後の状態を確認できません",
      tone: "action",
    },
  };
  const emergencyStateDetails =
    emergencyStateCode && emergencyStateCode !== "UNKNOWN"
      ? emergencyStateCopy[emergencyStateCode]
      : emergencyStateCopy.READY;

  const resolvedEmergencyLocked = (
    typeof emergencyLocked === "boolean"
      ? emergencyLocked
      : emergencyStateCode === "LOCKED"
  );
  const resolvedEmergencyLockClass = (
    emergencyLockClass
    || (
      emergencyStateCode === "LOCKED"
        ? "locked"
        : emergencyStateCode === "READY"
            ? "unlocked"
            : "unknown"
    )
  );
  const resolvedEmergencyLockValue = (
    emergencyLockValue
    || (resolvedEmergencyLocked ? "LOCKED" : "UNLOCKED")
  );
  const resolvedUnlockAllowed = (
    typeof unlockAllowed === "boolean"
      ? unlockAllowed
      : (
        emergencyStateCode !== "READY"
        && emergencyStateCode !== "PROCESSING"
      )
  );
  const resolvedEmergencyButtonDisabled = (
    typeof emergencyButtonDisabled === "boolean"
      ? emergencyButtonDisabled
      : emergencyStateCode !== "READY"
  );

  return (
    <div className="operation-top-emergency">
      <section className="operation-emergency-section">
        <div className="operation-emergency-header">
          <button
            className="emergency-stop-button operation-emergency-button"
            disabled={resolvedEmergencyButtonDisabled}
            onClick={openEmergencyConfirm}
            aria-busy={emergencyPending ? "true" : "false"}
            type="button"
          >
            {emergencyPending
              ? "EMERGENCY IN PROGRESS..."
              : "EMERGENCY STOP"
            }
          </button>

          <div className="operation-emergency-lock">
            <strong className={resolvedEmergencyLockClass}>
              ● {resolvedEmergencyLockValue}
            </strong>
          </div>
        </div>

        {emergencyStateCode !== "READY" && (
          <div
            className={
              "operation-emergency-status "
              + `operation-emergency-status--${emergencyStateDetails.tone}`
            }
          >
            <span className="operation-emergency-status__eyebrow">
              EMERGENCY STATUS
            </span>

            <strong className="operation-emergency-status__state">
              {emergencyStateDetails.label}
            </strong>

            <span className="operation-emergency-status__message">
              {emergencyStateDetails.text}
            </span>

            {emergencyStateCode === "PROCESSING" && (
              <span className="operation-emergency-status__pending">
                PROCESSING
              </span>
            )}

            {emergencyStateCode === "LOCKED" && lockedFacts.length > 0 && (
              <div className="operation-emergency-facts">
                {lockedFacts.map((fact) => (
                  <span key={fact}>
                    {fact}
                  </span>
                ))}
              </div>
            )}

            {emergencyStateCode === "ACTION_REQUIRED"
              && actionWarnings.length > 0 && (
              <div className="operation-emergency-warnings">
                {actionWarnings.map((warning) => (
                  <span key={warning}>
                    {warning}
                  </span>
                ))}
              </div>
            )}

            {lastResultMessage && (
              <span className="operation-emergency-status__message">
                {lastResultMessage}
              </span>
            )}
          </div>
        )}

        {emergencyConfirmOpen && (
          <div
            className="operation-emergency-confirm"
            role="dialog"
            aria-modal="false"
            aria-label="Confirm emergency stop"
          >
            <div className="operation-emergency-confirm__title">
              EMERGENCY STOP
            </div>

            <div className="operation-emergency-confirm__body">
              This action will activate Emergency Lock, disable Auto Trade,
              cancel eligible open orders, and flatten eligible positions.
            </div>

            <div className="operation-emergency-confirm__actions">
              <button
                className="operation-emergency-confirm__cancel"
                disabled={emergencyPending}
                onClick={cancelEmergencyConfirm}
                type="button"
              >
                CANCEL
              </button>

              <button
                className="operation-emergency-confirm__confirm"
                disabled={emergencyPending}
                onClick={confirmEmergency}
                type="button"
              >
                CONFIRM EMERGENCY
              </button>
            </div>
          </div>
        )}

        {emergencyStateCode === "LOCKED" && (
          <div className="operation-emergency-note">
            Emergency Lock is active.（Emergency Lockが有効です）
          </div>
        )}

        {emergencyStateCode !== "READY" && (
          <button
            className="operation-emergency-unlock"
            disabled={unlockPending || !resolvedUnlockAllowed}
            onClick={handleReturnToNormal}
            type="button"
          >
            {unlockPending ? "復帰中..." : "通常に戻す"}
          </button>
        )}

        {emergencyStateCode !== "READY" && (
          <div className="operation-emergency-detail">
            Execution path: {String(emergencyPath).toUpperCase()}
          </div>
        )}

        {emergencyError && (
          <div
            className="operation-emergency-error"
            data-testid="emergency-error"
            role="alert"
          >
            {emergencyError}
          </div>
        )}

        {unlockError && (
          <div
            className="operation-emergency-error"
            data-testid="emergency-unlock-error"
            role="alert"
          >
            {unlockError}
          </div>
        )}
      </section>
    </div>
  );
}