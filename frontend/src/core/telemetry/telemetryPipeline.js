import {
  createExecutionJournalTelemetry,
} from "../execution/executionJournal";

const telemetryState = {
  initialized: false,

  createdAt: Date.now(),

  lastUpdatedAt: 0,

  executionTelemetry: {},

  reconnectTelemetry: {},

  exchangeTelemetry: {},

  reconciliationTelemetry: {},

  journalTelemetry: {},

  runtimeTelemetry: {},

  survivabilityTelemetry: {},

  telemetryVersion:
    "EXECUTION_AI_CORE_V1",

  telemetryHealth:
    "INITIALIZING",
};

export function createTelemetryPipeline() {
  telemetryState.initialized = true;

  telemetryState.telemetryHealth =
    "ACTIVE";

  telemetryState.lastUpdatedAt =
    Date.now();

  return {
    updateTelemetryPipeline,
    createUnifiedTelemetryPacket,
    getTelemetryState,
    resetTelemetryPipeline,
  };
}

export function updateTelemetryPipeline({
  executionTelemetry = {},
  reconnectTelemetry = {},
  exchangeTelemetry = {},
  reconciliationTelemetry = {},
  runtimeTelemetry = {},
  survivabilityTelemetry = {},
} = {}) {
  telemetryState.executionTelemetry =
    executionTelemetry;

  telemetryState.reconnectTelemetry =
    reconnectTelemetry;

  telemetryState.exchangeTelemetry =
    exchangeTelemetry;

  telemetryState.reconciliationTelemetry =
    reconciliationTelemetry;

  telemetryState.runtimeTelemetry =
    runtimeTelemetry;

  telemetryState.survivabilityTelemetry =
    survivabilityTelemetry;

  telemetryState.journalTelemetry =
    createExecutionJournalTelemetry();

  telemetryState.lastUpdatedAt =
    Date.now();

  telemetryState.telemetryHealth =
    "ACTIVE";

  return createUnifiedTelemetryPacket();
}

export function createUnifiedTelemetryPacket() {
  return {
    telemetryVersion:
      telemetryState.telemetryVersion,

    telemetryHealth:
      telemetryState.telemetryHealth,

    initialized:
      telemetryState.initialized,

    createdAt:
      telemetryState.createdAt,

    lastUpdatedAt:
      telemetryState.lastUpdatedAt,

    executionTelemetry:
      telemetryState.executionTelemetry,

    reconnectTelemetry:
      telemetryState.reconnectTelemetry,

    exchangeTelemetry:
      telemetryState.exchangeTelemetry,

    reconciliationTelemetry:
      telemetryState.reconciliationTelemetry,

    runtimeTelemetry:
      telemetryState.runtimeTelemetry,

    survivabilityTelemetry:
      telemetryState.survivabilityTelemetry,

    journalTelemetry:
      telemetryState.journalTelemetry,

    executionJournalSize:
      telemetryState.journalTelemetry
        ?.executionJournalSize || 0,

    lastJournalEntry:
      telemetryState.journalTelemetry
        ?.lastJournalEntry || null,

    journalPersistenceStatus:
      telemetryState.journalTelemetry
        ?.journalPersistenceStatus ||
      "UNKNOWN",

    journalRestoreStatus:
      telemetryState.journalTelemetry
        ?.journalRestoreStatus ||
      "UNKNOWN",

    lastPersistenceTimestamp:
      telemetryState.journalTelemetry
        ?.lastPersistenceTimestamp ||
      null,

    lastRestoreTimestamp:
      telemetryState.journalTelemetry
        ?.lastRestoreTimestamp ||
      null,

    crashRecoveryDetected:
      telemetryState.journalTelemetry
        ?.crashRecoveryDetected ||
      false,
  };
}

export function getTelemetryState() {
  return telemetryState;
}

export function resetTelemetryPipeline() {
  telemetryState.initialized = false;

  telemetryState.lastUpdatedAt = 0;

  telemetryState.executionTelemetry =
    {};

  telemetryState.reconnectTelemetry =
    {};

  telemetryState.exchangeTelemetry =
    {};

  telemetryState.reconciliationTelemetry =
    {};

  telemetryState.runtimeTelemetry =
    {};

  telemetryState.survivabilityTelemetry =
    {};

  telemetryState.journalTelemetry =
    {};

  telemetryState.telemetryHealth =
    "RESET";

  return telemetryState;
}