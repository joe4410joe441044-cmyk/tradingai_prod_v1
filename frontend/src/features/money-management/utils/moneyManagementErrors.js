export const MONEY_MANAGEMENT_ERROR_CODE = Object.freeze({
  ABORTED: "ABORTED",
  TIMEOUT: "TIMEOUT",
  NETWORK_ERROR: "NETWORK_ERROR",
  UNAUTHORIZED: "UNAUTHORIZED",
  FORBIDDEN: "FORBIDDEN",
  NOT_FOUND: "NOT_FOUND",
  VALIDATION_ERROR: "VALIDATION_ERROR",
  REVISION_CONFLICT: "REVISION_CONFLICT",
  RECOVERY_CONFLICT: "RECOVERY_CONFLICT",
  RATE_LIMITED: "RATE_LIMITED",
  SERVER_ERROR: "SERVER_ERROR",
  INVALID_RESPONSE: "INVALID_RESPONSE",
  UNKNOWN_ERROR: "UNKNOWN_ERROR",
});

const SAFE_MESSAGES = Object.freeze({
  ABORTED: "The request was cancelled.",
  TIMEOUT: "The request timed out.",
  NETWORK_ERROR: "The service could not be reached.",
  UNAUTHORIZED: "Authentication is required.",
  FORBIDDEN: "This operation is not permitted.",
  NOT_FOUND: "The Money Management endpoint is unavailable.",
  VALIDATION_ERROR: "The submitted configuration is invalid.",
  REVISION_CONFLICT: "The configuration changed on the server.",
  RECOVERY_CONFLICT: "A recovery operation is already running.",
  RATE_LIMITED: "Too many requests were sent.",
  SERVER_ERROR: "The Money Management service is unavailable.",
  INVALID_RESPONSE: "The service returned an invalid response.",
  UNKNOWN_ERROR: "The request could not be completed.",
});

const RETRYABLE = new Set([
  MONEY_MANAGEMENT_ERROR_CODE.TIMEOUT,
  MONEY_MANAGEMENT_ERROR_CODE.NETWORK_ERROR,
  MONEY_MANAGEMENT_ERROR_CODE.RATE_LIMITED,
  MONEY_MANAGEMENT_ERROR_CODE.SERVER_ERROR,
]);

export class MoneyManagementDataError extends Error {
  constructor({
    code,
    httpStatus = null,
    operation,
    details = null,
    occurredAt = new Date().toISOString(),
  }) {
    const safeCode = Object.values(MONEY_MANAGEMENT_ERROR_CODE).includes(code)
      ? code
      : MONEY_MANAGEMENT_ERROR_CODE.UNKNOWN_ERROR;
    super(SAFE_MESSAGES[safeCode]);
    this.name = "MoneyManagementDataError";
    this.code = safeCode;
    this.httpStatus = httpStatus;
    this.retryable = RETRYABLE.has(safeCode);
    this.operation = operation;
    this.details = details;
    this.occurredAt = occurredAt;
  }

  toJSON() {
    return {
      code: this.code,
      message: this.message,
      httpStatus: this.httpStatus,
      retryable: this.retryable,
      operation: this.operation,
      details: this.details,
      occurredAt: this.occurredAt,
    };
  }
}

function errorCodeForStatus(status, operation, backendCode) {
  if (status === 401) return MONEY_MANAGEMENT_ERROR_CODE.UNAUTHORIZED;
  if (status === 403) return MONEY_MANAGEMENT_ERROR_CODE.FORBIDDEN;
  if (status === 404) return MONEY_MANAGEMENT_ERROR_CODE.NOT_FOUND;
  if (status === 409) {
    if (
      operation === "UPDATE_CONFIGURATION" ||
      backendCode === "CONFIGURATION_REVISION_CONFLICT"
    ) {
      return MONEY_MANAGEMENT_ERROR_CODE.REVISION_CONFLICT;
    }
    return MONEY_MANAGEMENT_ERROR_CODE.RECOVERY_CONFLICT;
  }
  if (status === 400 || status === 415 || status === 422) {
    return MONEY_MANAGEMENT_ERROR_CODE.VALIDATION_ERROR;
  }
  if (status === 429) return MONEY_MANAGEMENT_ERROR_CODE.RATE_LIMITED;
  if (status >= 500) return MONEY_MANAGEMENT_ERROR_CODE.SERVER_ERROR;
  return MONEY_MANAGEMENT_ERROR_CODE.UNKNOWN_ERROR;
}

export function fromHttpError(status, operation, body = null) {
  const backendCode =
    body && typeof body === "object" && typeof body.code === "string"
      ? body.code
      : null;
  return new MoneyManagementDataError({
    code: errorCodeForStatus(status, operation, backendCode),
    httpStatus: status,
    operation,
    details: backendCode ? { backendCode } : null,
  });
}

export function invalidResponseError(operation, reason) {
  return new MoneyManagementDataError({
    code: MONEY_MANAGEMENT_ERROR_CODE.INVALID_RESPONSE,
    operation,
    details: typeof reason === "string" ? { reason } : null,
  });
}
