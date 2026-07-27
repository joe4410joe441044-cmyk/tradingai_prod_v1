import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeMoneyManagementConfiguration,
  normalizeMoneyManagementStatus,
} from "../contracts/moneyManagementContracts.js";
import {
  validConfiguration,
  validStatus,
} from "../contracts/moneyManagementFixtures.js";
import {
  createInitialMoneyManagementState,
  MONEY_MANAGEMENT_ACTION,
  moneyManagementReducer,
} from "./moneyManagementReducer.js";

const status = () => normalizeMoneyManagementStatus(validStatus());
const configuration = (revision = 7) =>
  normalizeMoneyManagementConfiguration(
    validConfiguration({ revision }),
  );

function reduce(state, action) {
  return moneyManagementReducer(state, action);
}

test("initial and partial load state remain independently observable", () => {
  let state = createInitialMoneyManagementState();
  assert.equal(state.statusLoading, true);
  assert.equal(state.configurationLoading, true);
  assert.equal(state.status.executionEntryAllowed, false);
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
    pollingState: "RUNNING",
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 1,
    startedAt: 10,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
    requestId: 1,
    status: status(),
    receivedAt: 20,
  });
  assert.equal(state.statusLoading, false);
  assert.equal(state.configurationLoading, true);
  assert.equal(state.status.executionEntryAllowed, false);
  assert.equal(state.status.clientSafeReason, "CONFIGURATION_INVALID");
});

test("refresh failure preserves raw authority and fails safe display closed", () => {
  let state = createInitialMoneyManagementState();
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
    pollingState: "RUNNING",
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 1,
    startedAt: 1,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
    requestId: 1,
    status: status(),
    receivedAt: 2,
  });
  const raw = state.rawStatus;
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 2,
    startedAt: 3,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_FAILURE,
    requestId: 2,
    error: { code: "NETWORK_ERROR" },
    receivedAt: 4,
  });
  assert.equal(state.rawStatus, raw);
  assert.equal(state.status.executionEntryAllowed, false);
  assert.equal(state.clientStale, true);
  assert.equal(state.consecutiveFailures, 1);
});

test("older status response cannot overwrite a newer request", () => {
  let state = createInitialMoneyManagementState();
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 10,
    startedAt: 1,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 11,
    startedAt: 2,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
    requestId: 11,
    status: status(),
    receivedAt: 3,
  });
  const newest = state.rawStatus;
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
    requestId: 10,
    status: normalizeMoneyManagementStatus(
      validStatus({ riskState: "LOCKED" }),
    ),
    receivedAt: 4,
  });
  assert.equal(state.rawStatus, newest);
});

test("draft never overwrites authoritative configuration before success", () => {
  let state = createInitialMoneyManagementState();
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration(),
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { dailyWarningPercent: "0.75" },
  });
  assert.equal(state.configuration.dailyWarningPercent, "1.00");
  assert.equal(state.configurationDraft.dailyWarningPercent, "0.75");
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_START,
  });
  assert.equal(state.status.executionEntryAllowed, false);
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_FAILURE,
    error: { code: "SERVER_ERROR" },
  });
  assert.equal(state.configuration.dailyWarningPercent, "1.00");
  assert.equal(state.configurationDraft.dailyWarningPercent, "0.75");
});

test("revision conflict refreshes authority and preserves draft without retry", () => {
  let state = createInitialMoneyManagementState();
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
    pollingState: "RUNNING",
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 1,
    startedAt: 1,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
    requestId: 1,
    status: status(),
    receivedAt: 2,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration(7),
  });
  assert.equal(state.status.executionEntryAllowed, true);
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { dailyWarningPercent: "0.75" },
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_START,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_CONFLICT,
    error: { code: "REVISION_CONFLICT" },
    submittedRevision: 7,
    currentConfiguration: configuration(8),
  });
  assert.equal(state.configuration.revision, 8);
  assert.equal(state.configurationDraft.dailyWarningPercent, "0.75");
  assert.equal(state.status.executionEntryAllowed, false);
  assert.deepEqual(state.configurationConflict, {
    active: true,
    submittedRevision: 7,
    currentRevision: 8,
    draftPreserved: true,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { dailyWarningPercent: "0.80" },
  });
  assert.equal(state.status.executionEntryAllowed, true);
});

test("recovery, stale, polling stop, reset, and clear error are explicit", () => {
  let state = createInitialMoneyManagementState();
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration(),
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { dailyWarningPercent: "0.75" },
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_RESET,
  });
  assert.equal(state.configurationDraft.dailyWarningPercent, "1.00");
  state = reduce(state, { type: MONEY_MANAGEMENT_ACTION.RECOVERY_START });
  assert.equal(state.recoveryRunning, true);
  assert.equal(state.status.executionEntryAllowed, false);
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.RECOVERY_FAILURE,
    error: { code: "RECOVERY_CONFLICT" },
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CLEAR_ERROR,
    scope: "recovery",
  });
  assert.equal(state.recoveryError, null);
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CLIENT_STALE,
    stale: true,
  });
  assert.equal(state.status.executionEntryAllowed, false);
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
    pollingState: "STOPPED",
  });
  assert.equal(state.status.executionEntryAllowed, false);
});

test("manual refresh is fail closed and configuration refresh preserves only edited drafts", () => {
  let state = createInitialMoneyManagementState();
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
    pollingState: "RUNNING",
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration(7),
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
    requestId: 1,
    startedAt: 1,
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
    requestId: 1,
    status: status(),
    receivedAt: 2,
  });
  assert.equal(state.status.executionEntryAllowed, true);

  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.MANUAL_REFRESH_START,
  });
  assert.equal(state.status.executionEntryAllowed, false);
  assert.equal(state.status.clientSafeReason, "MANUAL_REFRESH_RUNNING");
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration(8),
  });
  assert.equal(state.configurationDraft.dailyWarningPercent, "1.00");
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.MANUAL_REFRESH_FINISH,
  });

  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { dailyWarningPercent: "0.75" },
  });
  state = reduce(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration(9),
  });
  assert.equal(state.configuration.revision, 9);
  assert.equal(state.configurationDraft.dailyWarningPercent, "0.75");
});
