export default function ExecutionPanel({

  handleStart,

  handleStop,

  botData,

  executionData,

  aiData,

}) {

  // =========================
  // SAFE HELPERS
  // =========================

  const safeNumber = (
    value
  ) => {

    if (
      value === null ||
      value === undefined
    ) {

      return null;

    }

    const n =
      Number(value);

    return Number.isFinite(n)
      ? n
      : null;

  };

  const safeRound = (
    value
  ) => {

    const n =
      Number(value);

    return Number.isFinite(n)
      ? Math.round(n)
      : "-";

  };

  const safeText = (
    value,
    fallback = "-"
  ) => {

    return (
      value !== null &&
      value !== undefined &&
      value !== ""
    )

      ? value

      : fallback;

  };

  const safeBool = (
    value,
    fallback = false
  ) => {

    return typeof value ===
      "boolean"

      ? value

      : fallback;

  };

  // =========================
  // BOT DATA
  // =========================

  const data =
    botData || {};

  // =========================
  // EXECUTION DATA
  // =========================

  const exec =
    executionData || {};

  const execution = {

    mode:
      safeText(
        exec.executionMode
      ),

    engine:
      safeText(
        exec.engineStatus
      ),

    ws:
      safeText(
        exec.wsStatus
      ),

    status:
      safeText(
        exec.orderStatus
      ),

    latency:
      safeNumber(
        exec.latency
      ),

    position:
      safeText(
        data.position
      ),

  };

  const executionRoute =
    safeText(
      exec.executionRoute
    );

  const executionAllowed =
    safeBool(
      exec.executionAllowed
    );

  const routerReason =
    safeText(
      exec.routerReason,
      "NONE"
    );

  const executionPriority =
    safeText(
      exec.executionPriority
    );

  const executionMode =
    safeText(
      exec.executionMode
    );

  const survivabilityScore =
    safeNumber(
      exec.survivabilityScore
    );

  const bridgeStatus =
    safeText(
      exec.bridgeStatus
    );

  const queueDepth =
    safeNumber(
      exec.queueDepth
    );

  const executionLock =
    safeBool(
      exec.executionLock
    );

  const cooldownRemaining =
    safeNumber(
      exec.cooldownRemaining
    );

  const activePosition =
    exec.activePosition ||
    null;

  const executionAccepted =
    safeBool(
      exec.executionAccepted
    );

  const executionRejected =
    safeBool(
      exec.executionRejected
    );

  const lastExecution =
    exec.lastExecution ||
    null;

  const reconciliationStatus =
    safeText(
      exec.reconciliationStatus
    );

  const positionIntegrity =
    safeNumber(
      exec.positionIntegrity
    );

  const executionConsistency =
    safeBool(
      exec.executionConsistency
    );

  const positionMismatch =
    safeBool(
      exec.positionMismatch
    );

  const recoveryTriggered =
    safeBool(
      exec.recoveryTriggered
    );

  const recoveryReason =
    safeText(
      exec.recoveryReason,
      "NONE"
    );

  const integrityStatus =
    safeText(
      exec.integrityStatus,
      "UNKNOWN"
    );

  const consistencyStatus =
    safeText(
      exec.consistencyStatus,
      "UNKNOWN"
    );

  const mismatchStatus =
    safeText(
      exec.mismatchStatus,
      "UNKNOWN"
    );

  const reconciliationFailures =
    safeNumber(
      exec.reconciliationFailures
    );

  const recoveryCount =
    safeNumber(
      exec.recoveryCount
    );

  const exchangeConnected =
    safeBool(
      exec.exchangeConnected
    );

  const exchangeStatus =
    safeText(
      exec.exchangeStatus,
      "UNKNOWN"
    );

  const lastExchangeVerification =
    exec.lastExchangeVerification ||
    null;

  const authoritativePosition =
    exec.authoritativePosition ||
    null;

  const authoritativeBalance =
    safeNumber(
      exec.authoritativeBalance
    );

  const exchangeMismatchDetected =
    safeBool(
      exec.exchangeMismatchDetected
    );

  const exchangeReconciliationStatus =
    safeText(
      exec.exchangeReconciliationStatus,
      "UNKNOWN"
    );

  const reconciliationLatency =
    safeNumber(
      exec.reconciliationLatency
    );

  const lastExchangeSyncPacket =
    exec.lastExchangeSyncPacket ||
    null;

  const lastMismatchReport =
    exec.lastMismatchReport ||
    null;

  const exchangePositionVerified =
    safeBool(
      exec.exchangePositionVerified
    );

  const exchangeBalanceVerified =
    safeBool(
      exec.exchangeBalanceVerified
    );

  const restoreValidationStatus =
    safeText(
      exec.restoreValidationStatus,
      "UNKNOWN"
    );

  const restoreValidationReason =
    safeText(
      exec.restoreValidationReason,
      "NONE"
    );

  const lastPersistenceRestore =
    safeText(
      exec.lastPersistenceRestore
    );

  const persistenceRecovered =
    safeBool(
      exec.persistenceRecovered
    );

  const streamDisconnected =
    safeBool(
      exec.streamDisconnected
    );

  const streamStale =
    safeBool(
      exec.streamStale
    );

  const reconnectInProgress =
    safeBool(
      exec.reconnectInProgress
    );

  const reconnectCount =
    safeNumber(
      exec.reconnectCount
    );

  const reconnectFailures =
    safeNumber(
      exec.reconnectFailures
    );

  const lastReconnectAt =
    safeText(
      exec.lastReconnectAt
    );

  const lastReconnectReason =
    safeText(
      exec.lastReconnectReason,
      "NONE"
    );

  const reconnectLatency =
    safeNumber(
      exec.reconnectLatency
    );

  const reconnectRecovered =
    safeBool(
      exec.reconnectRecovered
    );

  const executionSafetyState =
    safeText(
      exec.executionSafetyState,
      "UNKNOWN"
    );

  const runtimeSynchronizationState =
    safeText(
      exec.runtimeSynchronizationState,
      "UNKNOWN"
    );

  const authoritativeRuntimeState =
    safeText(
      exec.authoritativeRuntimeState,
      "UNKNOWN"
    );

  const lastAuthoritativeSync =
    safeText(
      exec.lastAuthoritativeSync
    );

  const authorityDrift =
    safeNumber(
      exec.authorityDrift
    );

  const synchronizationHealth =
    safeText(
      exec.synchronizationHealth,
      "UNKNOWN"
    );

  const stateDivergence =
    safeText(
      exec.stateDivergence,
      "UNKNOWN"
    );

  const executionAuthorityScore =
    safeNumber(
      exec.executionAuthorityScore
    );

  // =========================
  // AI DATA
  // =========================

  const ai =
    aiData || {};

  const aiDecision =
    safeText(
      ai.aiDecision
    );

  const finalAction =
    safeText(
      ai.finalAction
    );

  const executionProfile =
    safeText(
      ai.executionProfile
    );

  const aiConviction =
    safeText(
      ai.aiConviction
    );

  const survivalMode =
    safeText(
      ai.survivalMode
    );

  const executionConfidence =
    safeNumber(
      ai.executionConfidence
    );

  // =========================
  // UI
  // =========================

  return (

    <div className="execution-panel">

      <div className="panel-header">

        <h3>
          🔘 Execution Center
        </h3>

      </div>

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            MODE
          </span>

          <span className="value online">
            🟢 {execution.mode}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            ENGINE
          </span>

          <span className="value online">
            ⚡ {execution.engine}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            WS STATUS
          </span>

          <span
            className={
              execution.ws ===
              "CONNECTED"

                ? "value running"

                : "value stopped"
            }
          >

            {
              execution.ws ===
              "CONNECTED"

                ? "🟢 CONNECTED"

                : "🔴 DISCONNECTED"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            ORDER
          </span>

          <span className="value warning">
            {execution.status}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            LATENCY
          </span>

          <span className="value">

            {
              execution.latency !==
              null

                ? execution.latency

                : "-"
            } ms

          </span>

        </div>

      </div>

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            POSITION
          </span>

          <span
            className={
              execution.position ===
              "BUY"

                ? "value long"

                : execution.position ===
                  "SELL"

                ? "value short"

                : "value"
            }
          >

            {execution.position?.side || "NONE"}

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            PRICE
          </span>

          <span className="value">

            {
              safeNumber(
                data.price
              ) !== null

                ? data.price

                : "-"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            ENTRY
          </span>

          <span className="value">

            {
              safeNumber(
                data.entryPrice
              ) !== null

                ? data.entryPrice

                : "-"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            PNL
          </span>

          <span
            className={
              safeNumber(
                data.pnl
              ) !== null &&

              Number(data.pnl) >= 0

                ? "value running"

                : "value stopped"
            }
          >

            {
              safeNumber(
                data.pnl
              ) !== null

                ? data.pnl

                : "-"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            BALANCE
          </span>

          <span className="value">

            {
              safeNumber(
                data.balance
              ) !== null

                ? data.balance

                : "-"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            EQUITY
          </span>

          <span className="value">

            {
              safeNumber(
                data.equity
              ) !== null

                ? data.equity

                : "-"
            }

          </span>

        </div>

      </div>

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            AI DECISION
          </span>

          <span className="value online">
            {aiDecision}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            FINAL ACTION
          </span>

          <span
            className={
              finalAction ===
              "BUY"

                ? "value long"

                : finalAction ===
                  "SELL"

                ? "value short"

                : "value"
            }
          >

            {finalAction}

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            EXEC PROFILE
          </span>

          <span className="value warning">
            {executionProfile}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            CONVICTION
          </span>

          <span className="value">
            {aiConviction}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            SURVIVAL MODE
          </span>

          <span className="value warning">
            {survivalMode}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            EXEC CONF
          </span>

          <span className="value online">
            {
              safeRound(
                executionConfidence
              )
            }
          </span>

        </div>

      </div>

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            EXEC ROUTE
          </span>

          <span className="value online">
            {executionRoute}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            EXEC ALLOWED
          </span>

          <span
            className={
              executionAllowed

                ? "value running"

                : "value stopped"
            }
          >

            {
              executionAllowed

                ? "PASS"

                : "BLOCK"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            ROUTER REASON
          </span>

          <span className="value warning">
            {routerReason}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            PRIORITY
          </span>

          <span className="value">
            {executionPriority}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            EXEC MODE
          </span>

          <span className="value online">
            {executionMode}
          </span>

        </div>

        <div className="status-row">

          <span className="label">
            SURVIVABILITY
          </span>

          <span className="value warning">

            {
              safeRound(
                survivabilityScore
              )
            }

          </span>

        </div>

      </div>

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            AUTHORITY
          </span>

          <span
            className={
              authoritativeRuntimeState ===
              "AUTHORITATIVE"

                ? "value running"

                : "value warning"
            }
          >

            {
              authoritativeRuntimeState
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            LAST AUTH SYNC
          </span>

          <span className="value online">

            {
              lastAuthoritativeSync
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            AUTH DRIFT
          </span>

          <span
            className={
              authorityDrift !==
              null &&

              authorityDrift <= 10

                ? "value running"

                : authorityDrift !==
                    null &&
                  authorityDrift <= 40

                ? "value warning"

                : "value stopped"
            }
          >

            {
              authorityDrift !==
              null

                ? authorityDrift

                : "-"
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            SYNC HEALTH
          </span>

          <span
            className={
              synchronizationHealth ===
              "HEALTHY"

                ? "value running"

                : synchronizationHealth ===
                  "DEGRADED"

                ? "value warning"

                : "value stopped"
            }
          >

            {
              synchronizationHealth
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            STATE DIVERGENCE
          </span>

          <span
            className={
              stateDivergence ===
              "SYNCED"

                ? "value running"

                : "value warning"
            }
          >

            {
              stateDivergence
            }

          </span>

        </div>

        <div className="status-row">

          <span className="label">
            AUTH SCORE
          </span>

          <span
            className={
              executionAuthorityScore !==
              null &&

              executionAuthorityScore >=
              90

                ? "value running"

                : executionAuthorityScore !==
                    null &&
                  executionAuthorityScore >=
                    60

                ? "value warning"

                : "value stopped"
            }
          >

            {
              safeRound(
                executionAuthorityScore
              )
            }

          </span>

        </div>

      </div>

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            CONTROL
          </span>

          <span className="value warning">
            LIVE CONTROL
          </span>

        </div>

        <div className="execution-buttons">

          <button
            className="start-btn"
            onClick={handleStart}
          >
            ▶ START
          </button>

          <button
            className="stop-btn"
            onClick={handleStop}
          >
            ■ STOP
          </button>

        </div>

      </div>

    </div>

  );

}