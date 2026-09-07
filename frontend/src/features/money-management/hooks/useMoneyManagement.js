import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";

import {
  getMoneyManagementConfiguration,
  getMoneyManagementStatus,
  requestMoneyManagementRecovery,
  updateMoneyManagementConfiguration,
} from "../api/moneyManagementApi.js";
import {
  buildMoneyManagementConfigurationPayload,
  configurationDraftFromAuthoritative,
  MoneyManagementContractError,
  normalizeConfigurationUpdateResponse,
  normalizeMoneyManagementConfiguration,
  normalizeMoneyManagementStatus,
  normalizeRecoveryResponse,
  validateMoneyManagementConfigurationDraft,
} from "../contracts/moneyManagementContracts.js";
import {
  createInitialMoneyManagementState,
  MONEY_MANAGEMENT_ACTION,
  moneyManagementReducer,
} from "../state/moneyManagementReducer.js";
import {
  createMoneyManagementPollingController,
} from "../state/moneyManagementPolling.js";
import {
  MONEY_MANAGEMENT_ERROR_CODE,
  MoneyManagementDataError,
  invalidResponseError,
} from "../utils/moneyManagementErrors.js";

const DEFAULT_CLIENT = Object.freeze({
  getStatus: getMoneyManagementStatus,
  getConfiguration: getMoneyManagementConfiguration,
  updateConfiguration: updateMoneyManagementConfiguration,
  recover: requestMoneyManagementRecovery,
});

function normalizeError(error, operation) {
  if (error instanceof MoneyManagementDataError) return error;
  if (error instanceof MoneyManagementContractError) {
    return invalidResponseError(operation, error.reason);
  }
  return new MoneyManagementDataError({
    code: MONEY_MANAGEMENT_ERROR_CODE.UNKNOWN_ERROR,
    operation,
  });
}

export function useMoneyManagement({
  pollingIntervalMs = 3000,
  enabled = true,
  timeoutMs = 10000,
  client = DEFAULT_CLIENT,
} = {}) {
  const [state, dispatch] = useReducer(
    moneyManagementReducer,
    undefined,
    createInitialMoneyManagementState,
  );
  const pollingRef = useRef(null);
  const updateRunningRef = useRef(false);
  const recoveryRunningRef = useRef(false);
  const manualRefreshRunningRef = useRef(false);
  const configurationRequestSequenceRef = useRef(0);
  const configurationRequestControllerRef = useRef(null);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (!enabled) {
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
        pollingState: "STOPPED",
      });
      return undefined;
    }
    const polling = createMoneyManagementPollingController({
      pollingIntervalMs,
      fetchStatus: async ({ signal }) => {
        const raw = await client.getStatus({ signal, timeoutMs });
        return normalizeMoneyManagementStatus(raw);
      },
      onRequestStart: ({ requestId, startedAt }) => {
        dispatch({
          type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_START,
          requestId,
          startedAt,
        });
      },
      onSuccess: ({ requestId, result, receivedAt }) => {
        dispatch({
          type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_SUCCESS,
          requestId,
          status: result,
          receivedAt,
        });
      },
      onError: ({ requestId, error, receivedAt }) => {
        dispatch({
          type: MONEY_MANAGEMENT_ACTION.STATUS_REQUEST_FAILURE,
          requestId,
          error: normalizeError(error, "GET_STATUS"),
          receivedAt,
        });
      },
      onStale: (stale) => {
        dispatch({
          type: MONEY_MANAGEMENT_ACTION.CLIENT_STALE,
          stale,
        });
      },
      onPollingState: (pollingState) => {
        dispatch({
          type: MONEY_MANAGEMENT_ACTION.POLLING_STATE,
          pollingState,
        });
      },
    });
    pollingRef.current = polling;
    polling.start();
    return () => {
      polling.stop();
      if (pollingRef.current === polling) pollingRef.current = null;
    };
  }, [client, enabled, pollingIntervalMs, timeoutMs]);

  const refreshStatus = useCallback(
    (options = { supersede: true }) =>
      pollingRef.current?.refresh(options) ?? Promise.resolve(null),
    [],
  );

  const refreshConfiguration = useCallback(async () => {
    const requestId = ++configurationRequestSequenceRef.current;
    configurationRequestControllerRef.current?.abort();
    const controller = new AbortController();
    configurationRequestControllerRef.current = controller;
    dispatch({
      type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_START,
    });
    try {
      const raw = await client.getConfiguration({
        signal: controller.signal,
        timeoutMs,
      });
      if (
        controller.signal.aborted ||
        requestId !== configurationRequestSequenceRef.current
      ) {
        return null;
      }
      const configuration = normalizeMoneyManagementConfiguration(raw);
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
        configuration,
      });
      return configuration;
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== configurationRequestSequenceRef.current
      ) {
        return null;
      }
      const normalized = normalizeError(error, "GET_CONFIGURATION");
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_FAILURE,
        error: normalized,
      });
      return null;
    } finally {
      if (
        configurationRequestControllerRef.current === controller
      ) {
        configurationRequestControllerRef.current = null;
      }
    }
  }, [client, timeoutMs]);

  useEffect(() => {
    if (!enabled) return undefined;
    void refreshConfiguration();
    return () => {
      configurationRequestSequenceRef.current += 1;
      configurationRequestControllerRef.current?.abort();
      configurationRequestControllerRef.current = null;
    };
  }, [enabled, refreshConfiguration]);

  // Problem 1/9: auto-persist a valid MM edit so the operator does not have
  // to manually Save MM. An invalid draft is never silently persisted; it is
  // surfaced as an invalid state. Persistence / MM authority / fail-closed
  // behaviour are preserved (the authoritative config lives on the backend).
  useEffect(() => {
    if (!enabled) return undefined;
    const config = state.configuration;
    const draft = state.configurationDraft;
    if (!config || !draft) return undefined;
    if (
      state.configurationUpdating ||
      state.recoveryRunning ||
      state.manualRefreshing
    ) {
      return undefined;
    }
    const authoritative = configurationDraftFromAuthoritative(config);
    if (!authoritative) return undefined;
    const hasChanges = Object.keys(authoritative).some(
      (key) => authoritative[key] !== draft[key],
    );
    if (!hasChanges) return undefined;
    const validation = validateMoneyManagementConfigurationDraft(
      draft,
      config?.revision,
    );
    if (!validation.valid) return undefined;
    const timer = setTimeout(() => {
      void saveConfiguration();
    }, 600);
    return () => clearTimeout(timer);
  }, [
    enabled,
    saveConfiguration,
    state.configuration,
    state.configurationDraft,
    state.configurationUpdating,
    state.manualRefreshing,
    state.recoveryRunning,
  ]);

  const refresh = useCallback(async () => {
    if (
      manualRefreshRunningRef.current ||
      updateRunningRef.current ||
      recoveryRunningRef.current
    ) {
      return Object.freeze({ ok: false, inProgress: true });
    }
    manualRefreshRunningRef.current = true;
    dispatch({ type: MONEY_MANAGEMENT_ACTION.MANUAL_REFRESH_START });
    try {
      const [statusResult, configurationResult] = await Promise.all([
        refreshStatus({ supersede: true }),
        refreshConfiguration(),
      ]);
      return Object.freeze({
        ok: statusResult !== null && configurationResult !== null,
      });
    } finally {
      manualRefreshRunningRef.current = false;
      dispatch({ type: MONEY_MANAGEMENT_ACTION.MANUAL_REFRESH_FINISH });
    }
  }, [refreshConfiguration, refreshStatus]);

  const updateConfigurationDraft = useCallback((patch) => {
    if (!patch || typeof patch !== "object" || Array.isArray(patch)) return;
    dispatch({
      type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
      patch,
    });
  }, []);

  const resetConfigurationDraft = useCallback(() => {
    dispatch({
      type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_RESET,
    });
  }, []);

  const saveConfiguration = useCallback(async () => {
    if (
      updateRunningRef.current ||
      recoveryRunningRef.current ||
      manualRefreshRunningRef.current
    ) {
      return Object.freeze({ ok: false, inProgress: true });
    }
    const current = stateRef.current;
    let payload;
    try {
      payload = buildMoneyManagementConfigurationPayload(
        current.configurationDraft,
        current.configuration?.revision,
      );
    } catch (error) {
      const normalized = normalizeError(error, "UPDATE_CONFIGURATION");
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_FAILURE,
        error: normalized,
      });
      return Object.freeze({ ok: false, error: normalized });
    }
    updateRunningRef.current = true;
    dispatch({
      type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_START,
    });
    try {
      const raw = await client.updateConfiguration(payload, { timeoutMs });
      const result = normalizeConfigurationUpdateResponse(raw);
      await refreshStatus({ supersede: true });
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_SUCCESS,
        configuration: result.configuration,
      });
      return Object.freeze({ ok: true, result });
    } catch (error) {
      const normalized = normalizeError(error, "UPDATE_CONFIGURATION");
      if (
        normalized.code ===
        MONEY_MANAGEMENT_ERROR_CODE.REVISION_CONFLICT
      ) {
        const currentConfiguration = await refreshConfiguration();
        if (currentConfiguration) {
          dispatch({
            type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_CONFLICT,
            error: normalized,
            submittedRevision: payload.expectedRevision,
            currentConfiguration,
          });
          return Object.freeze({
            ok: false,
            conflict: true,
            error: normalized,
          });
        }
      }
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_FAILURE,
        error: normalized,
      });
      return Object.freeze({ ok: false, error: normalized });
    } finally {
      updateRunningRef.current = false;
    }
  }, [client, refreshConfiguration, refreshStatus, timeoutMs]);

  const recover = useCallback(async () => {
    if (
      recoveryRunningRef.current ||
      updateRunningRef.current ||
      manualRefreshRunningRef.current
    ) {
      return Object.freeze({ ok: false, inProgress: true });
    }
    recoveryRunningRef.current = true;
    dispatch({ type: MONEY_MANAGEMENT_ACTION.RECOVERY_START });
    try {
      const raw = await client.recover({ timeoutMs });
      const result = normalizeRecoveryResponse(raw);
      await refreshStatus({ supersede: true });
      await refreshConfiguration();
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.RECOVERY_SUCCESS,
        result,
      });
      return Object.freeze({ ok: true, result });
    } catch (error) {
      const normalized = normalizeError(error, "RECOVERY");
      if (
        normalized.code ===
        MONEY_MANAGEMENT_ERROR_CODE.RECOVERY_CONFLICT
      ) {
        await refreshStatus({ supersede: true });
      }
      dispatch({
        type: MONEY_MANAGEMENT_ACTION.RECOVERY_FAILURE,
        error: normalized,
      });
      return Object.freeze({ ok: false, error: normalized });
    } finally {
      recoveryRunningRef.current = false;
    }
  }, [client, refreshConfiguration, refreshStatus, timeoutMs]);

  const clearError = useCallback((scope) => {
    dispatch({
      type: MONEY_MANAGEMENT_ACTION.CLEAR_ERROR,
      scope,
    });
  }, []);

  const configurationDraftInvalid = Boolean(
    state.configurationDraft
    && state.configuration
    && !validateMoneyManagementConfigurationDraft(
      state.configurationDraft,
      state.configuration?.revision,
    ).valid
  );

  return useMemo(() => ({
    status: state.status,
    rawStatus: state.rawStatus,
    configuration: state.configuration,
    configurationDraft: state.configurationDraft,
    configurationDraftInvalid,
    isInitialLoading:
      state.statusLoading || state.configurationLoading,
    isRefreshing: state.refreshing,
    isManualRefreshing: state.manualRefreshing,
    isUpdatingConfiguration: state.configurationUpdating,
    isRecovering: state.recoveryRunning,
    isClientStale: state.clientStale,
    statusError: state.statusError,
    configurationError: state.configurationError,
    updateError: state.updateError,
    recoveryError: state.recoveryError,
    configurationConflict: state.configurationConflict,
    recoveryResult: state.recoveryResult,
    lastSuccessfulFetchAt: state.lastSuccessfulFetchAt,
    consecutiveFailures: state.consecutiveFailures,
    pollingState: state.pollingState,
    refresh,
    updateConfigurationDraft,
    resetConfigurationDraft,
    saveConfiguration,
    recover,
    clearError,
  }), [
    clearError,
    configurationDraftInvalid,
    recover,
    refresh,
    resetConfigurationDraft,
    saveConfiguration,
    state,
    updateConfigurationDraft,
  ]);
}
