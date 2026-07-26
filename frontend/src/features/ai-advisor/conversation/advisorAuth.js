export const ADVISOR_AUTH_STATE = Object.freeze({
    AVAILABLE: "AVAILABLE",
    AUTHENTICATION_REQUIRED: "AUTHENTICATION_REQUIRED",
});

export class AdvisorAuthenticationUnavailableError extends Error {
    constructor() {
        super("Authentication is required before AI Advisor can send requests.");
        this.name = "AdvisorAuthenticationUnavailableError";
        this.code = "AUTHENTICATION_REQUIRED";
        this.retryable = false;
    }
}

const productionProvider = Object.freeze({
    state: ADVISOR_AUTH_STATE.AUTHENTICATION_REQUIRED,
    async getAuthorizationHeader() {
        throw new AdvisorAuthenticationUnavailableError();
    },
});

export function getProductionAdvisorAuthProvider() {
    return productionProvider;
}

export function isAdvisorAuthProviderAvailable(provider) {
    return provider?.state === ADVISOR_AUTH_STATE.AVAILABLE
        && typeof provider.getAuthorizationHeader === "function";
}
