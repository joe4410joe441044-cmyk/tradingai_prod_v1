const EXECUTION_STATE_KEY =
  "TRADINGAI_EXECUTION_STATE";

const EXCHANGE_AUTHORITY_KEY =
  "TRADINGAI_EXCHANGE_AUTHORITY";

const RECONCILIATION_STATE_KEY =
  "TRADINGAI_RECONCILIATION_STATE";

const TELEMETRY_SNAPSHOT_KEY =
  "TRADINGAI_TELEMETRY_SNAPSHOT";

const PERSISTENCE_VERSION =
  "EXECUTION_AI_CORE_V1";

const MAX_STATE_AGE_MS =
  1000 * 60 * 30;

function safeSerialize(data) {
  try {
    return JSON.stringify(data);
  } catch (error) {
    return null;
  }
}

function safeDeserialize(serialized) {
  try {
    return JSON.parse(serialized);
  } catch (error) {
    return null;
  }
}

function saveToStorage({
  key,
  payload,
}) {
  if (
    typeof window === "undefined" ||
    !window.localStorage
  ) {
    return {
      success: false,
      reason: "LOCAL_STORAGE_UNAVAILABLE",
    };
  }

  const serializedPayload =
    safeSerialize(payload);

  if (!serializedPayload) {
    return {
      success: false,
      reason: "SERIALIZATION_FAILED",
    };
  }

  try {
    window.localStorage.setItem(
      key,
      serializedPayload
    );

    return {
      success: true,
      key,
    };
  } catch (error) {
    return {
      success: false,
      reason: "LOCAL_STORAGE_WRITE_FAILED",
      error,
    };
  }
}

function loadFromStorage(key) {
  if (
    typeof window === "undefined" ||
    !window.localStorage
  ) {
    return {
      success: false,
      reason: "LOCAL_STORAGE_UNAVAILABLE",
      payload: null,
    };
  }

  try {
    const serializedPayload =
      window.localStorage.getItem(key);

    if (!serializedPayload) {
      return {
        success: false,
        reason: "STATE_NOT_FOUND",
        payload: null,
      };
    }

    const payload =
      safeDeserialize(serializedPayload);

    if (!payload) {
      return {
        success: false,
        reason: "DESERIALIZATION_FAILED",
        payload: null,
      };
    }

    return {
      success: true,
      payload,
    };
  } catch (error) {
    return {
      success: false,
      reason: "LOCAL_STORAGE_READ_FAILED",
      payload: null,
      error,
    };
  }
}

function removeFromStorage(key) {
  if (
    typeof window === "undefined" ||
    !window.localStorage
  ) {
    return {
      success: false,
      reason: "LOCAL_STORAGE_UNAVAILABLE",
    };
  }

  try {
    window.localStorage.removeItem(key);

    return {
      success: true,
      key,
    };
  } catch (error) {
    return {
      success: false,
      reason: "LOCAL_STORAGE_REMOVE_FAILED",
      error,
    };
  }
}

export function createPersistenceSnapshot({
  activePosition = null,
  authoritativePosition = null,
  authoritativeBalance = 0,
  executionCount = 0,
  rejectedCount = 0,
  reconciliationFailures = 0,
  recoveryCount = 0,
  exchangeReconciliationStatus =
    "UNKNOWN",
  exchangeMismatchDetected = false,
  lastExecutionHash = null,
  lastExchangeSyncPacket = null,
  lastRecoveryReason = null,
  lastRecoveryTriggered = false,
  exchangeTelemetry = null,
} = {}) {
  return {
    version:
      PERSISTENCE_VERSION,

    activePosition,

    authoritativePosition,

    authoritativeBalance:
      Number(authoritativeBalance || 0),

    executionCount:
      Number(executionCount || 0),

    rejectedCount:
      Number(rejectedCount || 0),

    reconciliationFailures:
      Number(reconciliationFailures || 0),

    recoveryCount:
      Number(recoveryCount || 0),

    exchangeReconciliationStatus,

    exchangeMismatchDetected:
      Boolean(exchangeMismatchDetected),

    lastExecutionHash,

    lastExchangeSyncPacket,

    lastRecoveryReason,

    lastRecoveryTriggered:
      Boolean(lastRecoveryTriggered),

    exchangeTelemetry,

    persistedAt:
      Date.now(),
  };
}

export function validatePersistedState(
  persistedState
) {
  if (!persistedState) {
    return {
      valid: false,
      reason: "MISSING_PERSISTED_STATE",
    };
  }

  if (
    persistedState.version !==
    PERSISTENCE_VERSION
  ) {
    return {
      valid: false,
      reason: "INVALID_PERSISTENCE_VERSION",
    };
  }

  if (!persistedState.persistedAt) {
    return {
      valid: false,
      reason: "MISSING_PERSISTED_TIMESTAMP",
    };
  }

  const stateAge =
    Date.now() -
    persistedState.persistedAt;

  if (stateAge > MAX_STATE_AGE_MS) {
    return {
      valid: false,
      reason: "STALE_PERSISTED_STATE",
      stateAge,
    };
  }

  return {
    valid: true,
    reason: null,
    stateAge,
  };
}

export function persistExecutionState({
  activePosition = null,
  executionCount = 0,
  rejectedCount = 0,
  lastExecutionHash = null,
  recoveryCount = 0,
  reconciliationFailures = 0,
  lastRecoveryReason = null,
  lastRecoveryTriggered = false,
} = {}) {
  const snapshot =
    createPersistenceSnapshot({
      activePosition,
      executionCount,
      rejectedCount,
      lastExecutionHash,
      recoveryCount,
      reconciliationFailures,
      lastRecoveryReason,
      lastRecoveryTriggered,
    });

  return saveToStorage({
    key: EXECUTION_STATE_KEY,
    payload: snapshot,
  });
}

export function restoreExecutionState() {
  const restoredState =
    loadFromStorage(
      EXECUTION_STATE_KEY
    );

  if (!restoredState.success) {
    return restoredState;
  }

  const validation =
    validatePersistedState(
      restoredState.payload
    );

  if (!validation.valid) {
    return {
      success: false,
      reason: validation.reason,
      payload: null,
    };
  }

  return {
    success: true,
    payload:
      restoredState.payload,
    validation,
  };
}

export function clearExecutionState() {
  return removeFromStorage(
    EXECUTION_STATE_KEY
  );
}

export function persistExchangeAuthority({
  authoritativePosition = null,
  authoritativeBalance = 0,
  exchangeReconciliationStatus =
    "UNKNOWN",
  exchangeMismatchDetected = false,
  lastExchangeSyncPacket = null,
} = {}) {
  const authoritySnapshot =
    createPersistenceSnapshot({
      authoritativePosition,
      authoritativeBalance,
      exchangeReconciliationStatus,
      exchangeMismatchDetected,
      lastExchangeSyncPacket,
    });

  return saveToStorage({
    key: EXCHANGE_AUTHORITY_KEY,
    payload: authoritySnapshot,
  });
}

export function restoreExchangeAuthority() {
  const restoredAuthority =
    loadFromStorage(
      EXCHANGE_AUTHORITY_KEY
    );

  if (!restoredAuthority.success) {
    return restoredAuthority;
  }

  const validation =
    validatePersistedState(
      restoredAuthority.payload
    );

  if (!validation.valid) {
    return {
      success: false,
      reason: validation.reason,
      payload: null,
    };
  }

  return {
    success: true,
    payload:
      restoredAuthority.payload,
    validation,
  };
}

export function clearExchangeAuthority() {
  return removeFromStorage(
    EXCHANGE_AUTHORITY_KEY
  );
}

export function persistReconciliationState({
  exchangeReconciliationStatus =
    "UNKNOWN",
  exchangeMismatchDetected = false,
  reconciliationFailures = 0,
  recoveryCount = 0,
  lastRecoveryReason = null,
  lastRecoveryTriggered = false,
} = {}) {
  const reconciliationSnapshot =
    createPersistenceSnapshot({
      exchangeReconciliationStatus,
      exchangeMismatchDetected,
      reconciliationFailures,
      recoveryCount,
      lastRecoveryReason,
      lastRecoveryTriggered,
    });

  return saveToStorage({
    key: RECONCILIATION_STATE_KEY,
    payload: reconciliationSnapshot,
  });
}

export function restoreReconciliationState() {
  const restoredState =
    loadFromStorage(
      RECONCILIATION_STATE_KEY
    );

  if (!restoredState.success) {
    return restoredState;
  }

  const validation =
    validatePersistedState(
      restoredState.payload
    );

  if (!validation.valid) {
    return {
      success: false,
      reason: validation.reason,
      payload: null,
    };
  }

  return {
    success: true,
    payload:
      restoredState.payload,
    validation,
  };
}

export function clearReconciliationState() {
  return removeFromStorage(
    RECONCILIATION_STATE_KEY
  );
}

export function persistTelemetrySnapshot({
  exchangeTelemetry = null,
  lastExchangeSyncPacket = null,
  exchangeReconciliationStatus =
    "UNKNOWN",
  exchangeMismatchDetected = false,
} = {}) {
  const telemetrySnapshot =
    createPersistenceSnapshot({
      exchangeTelemetry,
      lastExchangeSyncPacket,
      exchangeReconciliationStatus,
      exchangeMismatchDetected,
    });

  return saveToStorage({
    key: TELEMETRY_SNAPSHOT_KEY,
    payload: telemetrySnapshot,
  });
}

export function restoreTelemetrySnapshot() {
  const restoredSnapshot =
    loadFromStorage(
      TELEMETRY_SNAPSHOT_KEY
    );

  if (!restoredSnapshot.success) {
    return restoredSnapshot;
  }

  const validation =
    validatePersistedState(
      restoredSnapshot.payload
    );

  if (!validation.valid) {
    return {
      success: false,
      reason: validation.reason,
      payload: null,
    };
  }

  return {
    success: true,
    payload:
      restoredSnapshot.payload,
    validation,
  };
}

export function clearTelemetrySnapshot() {
  return removeFromStorage(
    TELEMETRY_SNAPSHOT_KEY
  );
}

export function clearAllPersistedExecutionState() {
  const executionStateResult =
    clearExecutionState();

  const authorityResult =
    clearExchangeAuthority();

  const reconciliationResult =
    clearReconciliationState();

  const telemetryResult =
    clearTelemetrySnapshot();

  return {
    success:
      executionStateResult.success &&
      authorityResult.success &&
      reconciliationResult.success &&
      telemetryResult.success,

    executionStateResult,

    authorityResult,

    reconciliationResult,

    telemetryResult,
  };
}
