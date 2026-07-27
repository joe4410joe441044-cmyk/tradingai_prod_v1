import {
  configurationDraftFromAuthoritative,
  createSafeMoneyManagementStatus,
  validateMoneyManagementConfigurationDraft,
} from "../contracts/moneyManagementContracts.js";

export const MONEY_MANAGEMENT_ACTION = Object.freeze({
  STATUS_REQUEST_START: "STATUS_REQUEST_START",
  STATUS_REQUEST_SUCCESS: "STATUS_REQUEST_SUCCESS",
  STATUS_REQUEST_FAILURE: "STATUS_REQUEST_FAILURE",
  CONFIGURATION_REQUEST_START: "CONFIGURATION_REQUEST_START",
  CONFIGURATION_REQUEST_SUCCESS: "CONFIGURATION_REQUEST_SUCCESS",
  CONFIGURATION_REQUEST_FAILURE: "CONFIGURATION_REQUEST_FAILURE",
  CONFIGURATION_DRAFT_UPDATE: "CONFIGURATION_DRAFT_UPDATE",
  CONFIGURATION_DRAFT_RESET: "CONFIGURATION_DRAFT_RESET",
  CONFIGURATION_UPDATE_START: "CONFIGURATION_UPDATE_START",
  CONFIGURATION_UPDATE_SUCCESS: "CONFIGURATION_UPDATE_SUCCESS",
  CONFIGURATION_UPDATE_FAILURE: "CONFIGURATION_UPDATE_FAILURE",
  CONFIGURATION_CONFLICT: "CONFIGURATION_CONFLICT",
  RECOVERY_START: "RECOVERY_START",
  RECOVERY_SUCCESS: "RECOVERY_SUCCESS",
  RECOVERY_FAILURE: "RECOVERY_FAILURE",
  MANUAL_REFRESH_START: "MANUAL_REFRESH_START",
  MANUAL_REFRESH_FINISH: "MANUAL_REFRESH_FINISH",
  CLIENT_STALE: "CLIENT_STALE",
  POLLING_STATE: "POLLING_STATE",
  CLEAR_ERROR: "CLEAR_ERROR",
});

function project(state) {
  const draftValidation = validateMoneyManagementConfigurationDraft(
    state.configurationDraft,
    state.configuration?.revision,
  );
  return {
    ...state,
    status: createSafeMoneyManagementStatus(state.rawStatus, {
      clientStale: state.clientStale,
      requestFailed: Boolean(state.statusError),
      pollingState: state.pollingState,
      configurationUpdating: state.configurationUpdating,
      recoveryRunning: state.recoveryRunning,
      manualRefreshing: state.manualRefreshing,
      configurationConflict: Boolean(state.configurationConflict),
      configurationInvalid: !draftValidation.valid,
      configurationUnavailable: Boolean(state.configurationError),
    }),
  };
}

function hasDraftChanges(configuration, draft) {
  const authoritativeDraft =
    configurationDraftFromAuthoritative(configuration);
  if (!authoritativeDraft || !draft) return false;
  return Object.keys(authoritativeDraft).some(
    (key) => authoritativeDraft[key] !== draft[key],
  );
}

export function createInitialMoneyManagementState() {
  return project({
    status: null,
    rawStatus: null,
    configuration: null,
    configurationDraft: null,
    statusLoading: true,
    configurationLoading: true,
    configurationUpdating: false,
    recoveryRunning: false,
    manualRefreshing: false,
    refreshing: false,
    statusError: null,
    configurationError: null,
    updateError: null,
    recoveryError: null,
    configurationConflict: null,
    recoveryResult: null,
    activeStatusRequestId: 0,
    lastRequestStartedAt: null,
    lastSuccessfulFetchAt: null,
    lastResponseReceivedAt: null,
    consecutiveFailures: 0,
    clientStale: true,
    pollingState: "STOPPED",
  });
}

export function moneyManagementReducer(state, action) {
  switch (action.type) {
    case MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START:
      return project({
        ...state,
        activeStatusRequestId: action.requestId,
        lastRequestStartedAt: action.startedAt,
        statusLoading: state.rawStatus === null,
        refreshing: state.rawStatus !== null,
      });
    case MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS:
      if (action.requestId !== state.activeStatusRequestId) return state;
      return project({
        ...state,
        rawStatus: action.status,
        statusLoading: false,
        refreshing: false,
        statusError: null,
        lastSuccessfulFetchAt: action.receivedAt,
        lastResponseReceivedAt: action.receivedAt,
        consecutiveFailures: 0,
        clientStale: false,
      });
    case MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_FAILURE:
      if (action.requestId !== state.activeStatusRequestId) return state;
      return project({
        ...state,
        statusLoading: false,
        refreshing: false,
        statusError: action.error,
        lastResponseReceivedAt: action.receivedAt,
        consecutiveFailures: state.consecutiveFailures + 1,
        clientStale: true,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_START:
      return project({
        ...state,
        configurationLoading: true,
        configurationError: null,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS:
      return project({
        ...state,
        configuration: action.configuration,
        configurationDraft:
          hasDraftChanges(state.configuration, state.configurationDraft)
            ? state.configurationDraft
            : configurationDraftFromAuthoritative(action.configuration),
        configurationLoading: false,
        configurationError: null,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_FAILURE:
      return project({
        ...state,
        configurationLoading: false,
        configurationError: action.error,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE:
      return project({
        ...state,
        configurationDraft: Object.freeze({
          ...(state.configurationDraft ?? {}),
          ...action.patch,
        }),
        configurationConflict: null,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_RESET:
      return project({
        ...state,
        configurationDraft:
          configurationDraftFromAuthoritative(state.configuration),
        configurationConflict: null,
        updateError: null,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_START:
      return project({
        ...state,
        configurationUpdating: true,
        updateError: null,
        configurationConflict: null,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_SUCCESS:
      return project({
        ...state,
        configurationUpdating: false,
        configuration: action.configuration,
        configurationDraft:
          configurationDraftFromAuthoritative(action.configuration),
        rawStatus: action.status ?? state.rawStatus,
        updateError: null,
        configurationConflict: null,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_FAILURE:
      return project({
        ...state,
        configurationUpdating: false,
        updateError: action.error,
      });
    case MONEY_MANAGEMENT_ACTION.CONFIGURATION_CONFLICT:
      return project({
        ...state,
        configurationUpdating: false,
        configuration: action.currentConfiguration,
        updateError: action.error,
        configurationConflict: Object.freeze({
          active: true,
          submittedRevision: action.submittedRevision,
          currentRevision: action.currentConfiguration?.revision ?? null,
          draftPreserved: true,
        }),
      });
    case MONEY_MANAGEMENT_ACTION.RECOVERY_START:
      return project({
        ...state,
        recoveryRunning: true,
        recoveryError: null,
      });
    case MONEY_MANAGEMENT_ACTION.RECOVERY_SUCCESS:
      return project({
        ...state,
        recoveryRunning: false,
        recoveryResult: action.result,
        recoveryError: null,
      });
    case MONEY_MANAGEMENT_ACTION.RECOVERY_FAILURE:
      return project({
        ...state,
        recoveryRunning: false,
        recoveryError: action.error,
      });
    case MONEY_MANAGEMENT_ACTION.MANUAL_REFRESH_START:
      return project({
        ...state,
        manualRefreshing: true,
      });
    case MONEY_MANAGEMENT_ACTION.MANUAL_REFRESH_FINISH:
      return project({
        ...state,
        manualRefreshing: false,
      });
    case MONEY_MANAGEMENT_ACTION.CLIENT_STALE:
      return project({
        ...state,
        clientStale: action.stale,
      });
    case MONEY_MANAGEMENT_ACTION.POLLING_STATE:
      return project({
        ...state,
        pollingState: action.pollingState,
      });
    case MONEY_MANAGEMENT_ACTION.CLEAR_ERROR:
      return project({
        ...state,
        statusError:
          !action.scope || action.scope === "status"
            ? null
            : state.statusError,
        configurationError:
          !action.scope || action.scope === "configuration"
            ? null
            : state.configurationError,
        updateError:
          !action.scope || action.scope === "update"
            ? null
            : state.updateError,
        recoveryError:
          !action.scope || action.scope === "recovery"
            ? null
            : state.recoveryError,
      });
    default:
      return state;
  }
}
