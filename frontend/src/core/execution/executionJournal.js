const executionJournalState = {
  executionJournalSize: 0,

  lastJournalEntry: null,

  journalPersistenceStatus:
    "INITIALIZED",

  journalRestoreStatus:
    "INITIALIZED",

  lastPersistenceTimestamp:
    null,

  lastRestoreTimestamp:
    null,

  crashRecoveryDetected:
    false,

  createdAt:
    Date.now(),
};

export function createExecutionJournalTelemetry() {
  return {
    executionJournalSize:
      executionJournalState.executionJournalSize,

    lastJournalEntry:
      executionJournalState.lastJournalEntry,

    journalPersistenceStatus:
      executionJournalState.journalPersistenceStatus,

    journalRestoreStatus:
      executionJournalState.journalRestoreStatus,

    lastPersistenceTimestamp:
      executionJournalState.lastPersistenceTimestamp,

    lastRestoreTimestamp:
      executionJournalState.lastRestoreTimestamp,

    crashRecoveryDetected:
      executionJournalState.crashRecoveryDetected,

    createdAt:
      executionJournalState.createdAt,
  };
}

export function appendExecutionJournalEntry(
  entry = {}
) {
  executionJournalState.executionJournalSize += 1;

  executionJournalState.lastJournalEntry = {
    ...entry,

    timestamp:
      Date.now(),
  };

  executionJournalState.lastPersistenceTimestamp =
    Date.now();

  executionJournalState.journalPersistenceStatus =
    "UPDATED";

  return executionJournalState.lastJournalEntry;
}

export function restoreExecutionJournal() {
  executionJournalState.lastRestoreTimestamp =
    Date.now();

  executionJournalState.journalRestoreStatus =
    "RESTORED";

  return executionJournalState;
}

export function resetExecutionJournal() {
  executionJournalState.executionJournalSize = 0;

  executionJournalState.lastJournalEntry =
    null;

  executionJournalState.journalPersistenceStatus =
    "RESET";

  return executionJournalState;
}
