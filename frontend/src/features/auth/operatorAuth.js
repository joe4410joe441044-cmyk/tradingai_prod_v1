export const OPERATOR_AUTH_STATE = Object.freeze({
    AUTHENTICATED: "AUTHENTICATED",
    UNAUTHENTICATED: "UNAUTHENTICATED",
    SESSION_EXPIRED: "SESSION_EXPIRED",
    CHECKING: "CHECKING",
});

export const AUTH_STATUS_PATH = "/api/auth/status";
export const AUTH_LOGIN_PATH = "/api/auth/login";
export const AUTH_LOGOUT_PATH = "/api/auth/logout";
export const CSRF_TOKEN_COOKIE = "tradingai_csrf";
export const CSRF_TOKEN_HEADER = "X-TradingAI-CSRF";
export const SESSION_COOKIE = "tradingai_session";

export class OperatorAuthError extends Error {
    constructor(message, code = "AUTH_ERROR") {
        super(message);
        this.name = "OperatorAuthError";
        this.code = code;
    }
}

export function readCsrfToken() {
    if (typeof document === "undefined") return null;
    const match = document.cookie.match(
        new RegExp(`(?:^|;\\s*)${CSRF_TOKEN_COOKIE}=([^;]*)`),
    );
    return match ? decodeURIComponent(match[1]) : null;
}

let operatorAuthStatus = null;
const operatorAuthStatusListeners = new Set();

export function getOperatorAuthStatus() {
    return operatorAuthStatus;
}

export function setOperatorAuthStatus(status) {
    operatorAuthStatus = status;
    for (const listener of operatorAuthStatusListeners) {
        listener(status);
    }
}

export function subscribeOperatorAuthStatus(listener) {
    operatorAuthStatusListeners.add(listener);
    return () => operatorAuthStatusListeners.delete(listener);
}

export function createOperatorAuthClient({
    fetchImpl = globalThis.fetch,
} = {}) {
    return Object.freeze({
        async getStatus({ signal } = {}) {
            const response = await fetchImpl(AUTH_STATUS_PATH, {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                signal,
            });
            if (!response.ok) {
                return OPERATOR_AUTH_STATE.UNAUTHENTICATED;
            }
            const body = await response.json();
            return body.status || OPERATOR_AUTH_STATE.UNAUTHENTICATED;
        },

        async login(credential, { signal } = {}) {
            const response = await fetchImpl(AUTH_LOGIN_PATH, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ credential }),
                signal,
            });
            const body = await response.json();
            if (!response.ok || body.status !== "AUTHENTICATED") {
                throw new OperatorAuthError(
                    "Authentication failed. Please check your credentials.",
                    "INVALID_CREDENTIAL",
                );
            }
            return body;
        },

        async logout({ signal } = {}) {
            const csrfToken = readCsrfToken();
            const headers = {
                Accept: "application/json",
            };
            if (csrfToken) {
                headers[CSRF_TOKEN_HEADER] = csrfToken;
            }
            const response = await fetchImpl(AUTH_LOGOUT_PATH, {
                method: "POST",
                credentials: "same-origin",
                headers,
                signal,
            });
            const body = await response.json();
            return body;
        },
    });
}
