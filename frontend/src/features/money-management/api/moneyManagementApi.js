import { API } from "../../../api/index.js";

import {
  MONEY_MANAGEMENT_ERROR_CODE,
  MoneyManagementDataError,
  fromHttpError,
  invalidResponseError,
} from "../utils/moneyManagementErrors.js";

const DEFAULT_TIMEOUT_MS = 10000;

function safeBackendErrorBody(text) {
  if (typeof text !== "string" || text.length === 0 || text.length > 8192) {
    return null;
  }
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return typeof parsed.code === "string" ? { code: parsed.code } : null;
  } catch {
    return null;
  }
}

function createRequestSignal(callerSignal, timeoutMs) {
  const controller = new AbortController();
  let timedOut = false;
  let timeoutId = null;

  const abortFromCaller = () => controller.abort(callerSignal.reason);
  if (callerSignal) {
    if (callerSignal.aborted) {
      abortFromCaller();
    } else {
      callerSignal.addEventListener("abort", abortFromCaller, { once: true });
    }
  }
  if (timeoutMs !== null) {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      if (timeoutId !== null) clearTimeout(timeoutId);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    },
  };
}

async function requestJson(url, {
  operation,
  method = "GET",
  payload,
  signal,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new MoneyManagementDataError({
      code: MONEY_MANAGEMENT_ERROR_CODE.NETWORK_ERROR,
      operation,
    });
  }
  if (
    timeoutMs !== null &&
    (!Number.isInteger(timeoutMs) || timeoutMs <= 0)
  ) {
    throw new TypeError("timeoutMs must be a positive integer or null");
  }
  const requestSignal = createRequestSignal(signal, timeoutMs);
  try {
    const response = await fetchImpl(url, {
      method,
      headers: {
        Accept: "application/json",
        ...(payload === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal: requestSignal.signal,
      credentials: "same-origin",
    });
    const text = await response.text();
    if (!response.ok) {
      throw fromHttpError(
        response.status,
        operation,
        safeBackendErrorBody(text),
      );
    }
    if (text.length === 0) {
      throw invalidResponseError(operation, "empty response");
    }
    try {
      return JSON.parse(text);
    } catch {
      throw invalidResponseError(operation, "malformed JSON");
    }
  } catch (error) {
    if (error instanceof MoneyManagementDataError) {
      throw error;
    }
    if (requestSignal.timedOut()) {
      throw new MoneyManagementDataError({
        code: MONEY_MANAGEMENT_ERROR_CODE.TIMEOUT,
        operation,
      });
    }
    if (signal?.aborted || error?.name === "AbortError") {
      throw new MoneyManagementDataError({
        code: MONEY_MANAGEMENT_ERROR_CODE.ABORTED,
        operation,
      });
    }
    throw new MoneyManagementDataError({
      code: MONEY_MANAGEMENT_ERROR_CODE.NETWORK_ERROR,
      operation,
    });
  } finally {
    requestSignal.cleanup();
  }
}

export function getMoneyManagementStatus(options = {}) {
  return requestJson(API.moneyManagementStatus(), {
    ...options,
    operation: "GET_STATUS",
  });
}

export function getMoneyManagementConfiguration(options = {}) {
  return requestJson(API.moneyManagementConfiguration(), {
    ...options,
    operation: "GET_CONFIGURATION",
  });
}

export function updateMoneyManagementConfiguration(payload, options = {}) {
  return requestJson(API.moneyManagementConfiguration(), {
    ...options,
    operation: "UPDATE_CONFIGURATION",
    method: "PUT",
    payload,
  });
}

export function requestMoneyManagementRecovery(options = {}) {
  return requestJson(API.moneyManagementRecovery(), {
    ...options,
    operation: "RECOVERY",
    method: "POST",
  });
}

export function previewMoneyManagementPositionSize(payload, options = {}) {
  return requestJson(API.moneyManagementPositionSizePreview(), {
    ...options,
    operation: "PREVIEW_POSITION_SIZE",
    method: "POST",
    payload,
  });
}
