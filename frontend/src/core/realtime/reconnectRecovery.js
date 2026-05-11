const STALE_THRESHOLD_MS = 5000;

const RECONNECT_TIMEOUT_MS = 15000;

const reconnectState = {

  streamDisconnected: false,

  streamStale: false,

  reconnectTriggered: false,

  reconnectInProgress: false,

  reconnectCount: 0,

  reconnectFailures: 0,

  lastReconnectAt: null,

  lastReconnectReason: null,

  lastPacketAt: null,

  reconnectLatency: 0,

  reconnectRecovered: false,

};

export function createReconnectRecovery() {

  return {

    updateRealtimePacketTimestamp,

    detectStreamDisconnect,

    detectStaleRealtimeFeed,

    triggerReconnectRecovery,

    recoverRealtimeConnection,

    recoverExchangeSession,

    performReconnectReconciliation,

    validateReconnectRecovery,

    createReconnectTelemetryPacket,

    getReconnectState,

  };

}

function updateRealtimePacketTimestamp() {

  reconnectState.lastPacketAt =
    Date.now();

  reconnectState.streamDisconnected =
    false;

  reconnectState.streamStale =
    false;

}

function detectStreamDisconnect({

  websocketConnected = true,

} = {}) {

  if (websocketConnected) {

    reconnectState.streamDisconnected =
      false;

    return {

      disconnected: false,

      reason: null,

    };

  }

  reconnectState.streamDisconnected =
    true;

  reconnectState.reconnectTriggered =
    true;

  reconnectState.lastReconnectReason =
    "STREAM_DISCONNECTED";

  return {

    disconnected: true,

    reason: "STREAM_DISCONNECTED",

  };

}

function detectStaleRealtimeFeed() {

  if (
    !reconnectState.lastPacketAt
  ) {

    return {

      stale: false,

      latency: 0,

    };

  }

  const latency =
    Date.now() -
    reconnectState.lastPacketAt;

  reconnectState.reconnectLatency =
    latency;

  if (
    latency <
    STALE_THRESHOLD_MS
  ) {

    reconnectState.streamStale =
      false;

    return {

      stale: false,

      latency,

    };

  }

  reconnectState.streamStale =
    true;

  reconnectState.reconnectTriggered =
    true;

  reconnectState.lastReconnectReason =
    "STALE_REALTIME_FEED";

  return {

    stale: true,

    latency,

    reason: "STALE_REALTIME_FEED",

  };

}

async function triggerReconnectRecovery({

  reconnectHandler,

  exchangeRecoveryHandler,

  reconciliationHandler,

} = {}) {

  if (
    reconnectState.reconnectInProgress
  ) {

    return {

      recovered: false,

      reason:
        "RECONNECT_ALREADY_RUNNING",

    };

  }

  reconnectState.reconnectInProgress =
    true;

  reconnectState.reconnectTriggered =
    true;

  reconnectState.reconnectRecovered =
    false;

  reconnectState.lastReconnectAt =
    Date.now();

  const reconnectStartedAt =
    Date.now();

  try {

    const realtimeRecovery =
      await recoverRealtimeConnection({

        reconnectHandler,

      });

    if (!realtimeRecovery.recovered) {

      reconnectState.reconnectFailures += 1;

      reconnectState.lastReconnectReason =
        realtimeRecovery.reason;

      reconnectState.reconnectInProgress =
        false;

      return realtimeRecovery;

    }

    const exchangeRecovery =
      await recoverExchangeSession({

        exchangeRecoveryHandler,

      });

    if (!exchangeRecovery.recovered) {

      reconnectState.reconnectFailures += 1;

      reconnectState.lastReconnectReason =
        exchangeRecovery.reason;

      reconnectState.reconnectInProgress =
        false;

      return exchangeRecovery;

    }

    const reconciliationRecovery =
      await performReconnectReconciliation({

        reconciliationHandler,

      });

    if (
      !reconciliationRecovery.recovered
    ) {

      reconnectState.reconnectFailures += 1;

      reconnectState.lastReconnectReason =
        reconciliationRecovery.reason;

      reconnectState.reconnectInProgress =
        false;

      return reconciliationRecovery;

    }

    reconnectState.reconnectCount += 1;

    reconnectState.reconnectRecovered =
      true;

    reconnectState.streamDisconnected =
      false;

    reconnectState.streamStale =
      false;

    reconnectState.reconnectTriggered =
      false;

    reconnectState.reconnectLatency =
      Date.now() -
      reconnectStartedAt;

    reconnectState.lastReconnectReason =
      "RECONNECT_RECOVERED";

    reconnectState.reconnectInProgress =
      false;

    return {

      recovered: true,

      reason: "RECONNECT_RECOVERED",

      reconnectLatency:
        reconnectState.reconnectLatency,

    };

  } catch (error) {

    reconnectState.reconnectFailures += 1;

    reconnectState.reconnectRecovered =
      false;

    reconnectState.reconnectInProgress =
      false;

    reconnectState.lastReconnectReason =
      "RECONNECT_EXCEPTION";

    return {

      recovered: false,

      reason: "RECONNECT_EXCEPTION",

      error,

    };

  }

}

async function recoverRealtimeConnection({

  reconnectHandler,

} = {}) {

  if (
    typeof reconnectHandler !==
    "function"
  ) {

    return {

      recovered: false,

      reason:
        "MISSING_RECONNECT_HANDLER",

    };

  }

  const timeoutPromise =
    new Promise((resolve) => {

      setTimeout(() => {

        resolve({

          recovered: false,

          reason:
            "REALTIME_RECONNECT_TIMEOUT",

        });

      }, RECONNECT_TIMEOUT_MS);

    });

  const reconnectPromise =
    reconnectHandler();

  const result =
    await Promise.race([
      reconnectPromise,
      timeoutPromise,
    ]);

  if (!result?.recovered) {

    return {

      recovered: false,

      reason:
        result?.reason ||
        "REALTIME_RECONNECT_FAILED",

    };

  }

  return {

    recovered: true,

    reason:
      "REALTIME_CONNECTION_RECOVERED",

  };

}

async function recoverExchangeSession({

  exchangeRecoveryHandler,

} = {}) {

  if (
    typeof exchangeRecoveryHandler !==
    "function"
  ) {

    return {

      recovered: false,

      reason:
        "MISSING_EXCHANGE_RECOVERY_HANDLER",

    };

  }

  try {

    const recoveryResult =
      await exchangeRecoveryHandler();

    if (!recoveryResult?.recovered) {

      return {

        recovered: false,

        reason:
          recoveryResult?.reason ||
          "EXCHANGE_SESSION_RECOVERY_FAILED",

      };

    }

    return {

      recovered: true,

      reason:
        "EXCHANGE_SESSION_RECOVERED",

    };

  } catch (error) {

    return {

      recovered: false,

      reason:
        "EXCHANGE_RECOVERY_EXCEPTION",

      error,

    };

  }

}

async function performReconnectReconciliation({

  reconciliationHandler,

} = {}) {

  if (
    typeof reconciliationHandler !==
    "function"
  ) {

    return {

      recovered: false,

      reason:
        "MISSING_RECONCILIATION_HANDLER",

    };

  }

  try {

    const reconciliationResult =
      await reconciliationHandler();

    if (
      !reconciliationResult?.recovered
    ) {

      return {

        recovered: false,

        reason:
          reconciliationResult?.reason ||
          "RECONNECT_RECONCILIATION_FAILED",

      };

    }

    return {

      recovered: true,

      reason:
        "RECONNECT_RECONCILIATION_RECOVERED",

    };

  } catch (error) {

    return {

      recovered: false,

      reason:
        "RECONNECT_RECONCILIATION_EXCEPTION",

      error,

    };

  }

}

function validateReconnectRecovery() {

  if (
    reconnectState.streamDisconnected
  ) {

    return {

      valid: false,

      reason:
        "STREAM_DISCONNECTED",

    };

  }

  if (
    reconnectState.streamStale
  ) {

    return {

      valid: false,

      reason:
        "STALE_REALTIME_FEED",

    };

  }

  if (
    reconnectState.reconnectInProgress
  ) {

    return {

      valid: false,

      reason:
        "RECONNECT_IN_PROGRESS",

    };

  }

  if (
    !reconnectState.reconnectRecovered &&
    reconnectState.reconnectTriggered
  ) {

    return {

      valid: false,

      reason:
        "RECONNECT_NOT_RECOVERED",

    };

  }

  return {

    valid: true,

    reason: null,

  };

}

function createReconnectTelemetryPacket() {

  return {

    streamDisconnected:
      reconnectState.streamDisconnected,

    streamStale:
      reconnectState.streamStale,

    reconnectTriggered:
      reconnectState.reconnectTriggered,

    reconnectInProgress:
      reconnectState.reconnectInProgress,

    reconnectCount:
      reconnectState.reconnectCount,

    reconnectFailures:
      reconnectState.reconnectFailures,

    lastReconnectAt:
      reconnectState.lastReconnectAt,

    lastReconnectReason:
      reconnectState.lastReconnectReason,

    lastPacketAt:
      reconnectState.lastPacketAt,

    reconnectLatency:
      reconnectState.reconnectLatency,

    reconnectRecovered:
      reconnectState.reconnectRecovered,

  };

}

function getReconnectState() {

  return reconnectState;

}