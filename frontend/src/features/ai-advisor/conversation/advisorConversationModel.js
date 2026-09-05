export const MAX_ADVISOR_PROMPT_BYTES = 12_000;

export const ADVISOR_MESSAGE_ROLE = Object.freeze({
    USER: "USER",
    ASSISTANT: "ASSISTANT",
    SYSTEM_NOTICE: "SYSTEM_NOTICE",
});

export const ADVISOR_MESSAGE_STATUS = Object.freeze({
    PENDING: "PENDING",
    SUCCEEDED: "SUCCEEDED",
    FAILED: "FAILED",
    CANCELLED: "CANCELLED",
    TIMED_OUT: "TIMED_OUT",
});

export const ADVISOR_FAILURE_MESSAGE = Object.freeze({
    AUTHENTICATION_REQUIRED: "Authentication is required before sending.",
    ACCESS_DENIED: "AI Advisor access is not allowed.",
    REQUEST_INVALID: "The request could not be accepted. Review the prompt and try again.",
    RATE_LIMITED: "Too many requests. Wait before trying again.",
    CONCURRENCY_LIMITED: "AI Advisor is busy. Try again after the current work finishes.",
    TIMED_OUT: "The request timed out. You may try again.",
    CANCELLED: "The request was cancelled.",
    ENDPOINT_UNAVAILABLE: "AI Advisor is currently unavailable.",
    NETWORK_DISABLED: "AI Advisor network access is disabled.",
    PROVIDER_UNAVAILABLE: "The advisor provider is currently unavailable.",
    INVALID_PROVIDER_RESPONSE: "The advisor returned an invalid response.",
    INTERNAL_FAILURE: "The advisor request failed safely.",
    UNKNOWN_SAFE_FAILURE: "The advisor request could not be completed.",
});

export const utf8ByteLength = (value) => new TextEncoder().encode(value).byteLength;

export function validateAdvisorPrompt(value) {
    if (typeof value !== "string" || value.trim().length === 0) {
        return Object.freeze({ valid: false, code: "EMPTY_PROMPT", byteLength: 0 });
    }
    const byteLength = utf8ByteLength(value);
    return Object.freeze({
        valid: byteLength <= MAX_ADVISOR_PROMPT_BYTES,
        code: byteLength <= MAX_ADVISOR_PROMPT_BYTES ? null : "PROMPT_TOO_LARGE",
        byteLength,
    });
}

export const initialAdvisorConversationState = Object.freeze({
    messages: Object.freeze([]),
    archivedExchanges: Object.freeze([]),
    activeRequestId: null,
});

const freezeMessage = (message) => Object.freeze({ ...message });
const freezeExchange = (exchange) => Object.freeze({
    ...exchange,
    userMessage: freezeMessage(exchange.userMessage),
    assistantMessage: freezeMessage(exchange.assistantMessage),
});
const nextState = (
    messages,
    activeRequestId,
    archivedExchanges = [],
) => Object.freeze({
    messages: Object.freeze(messages.map(freezeMessage)),
    archivedExchanges: Object.freeze(archivedExchanges.map(freezeExchange)),
    activeRequestId,
});

const TERMINAL_ASSISTANT_STATUSES = new Set([
    ADVISOR_MESSAGE_STATUS.SUCCEEDED,
    ADVISOR_MESSAGE_STATUS.FAILED,
    ADVISOR_MESSAGE_STATUS.CANCELLED,
    ADVISOR_MESSAGE_STATUS.TIMED_OUT,
]);

function archiveCurrentExchange(state) {
    const userMessage = state.messages.find((message) => (
        message.role === ADVISOR_MESSAGE_ROLE.USER
    ));
    const assistantMessage = state.messages.find((message) => (
        message.role === ADVISOR_MESSAGE_ROLE.ASSISTANT
        && message.requestId === userMessage?.requestId
    ));
    if (!userMessage
        || !assistantMessage
        || !TERMINAL_ASSISTANT_STATUSES.has(assistantMessage.status)) {
        return state.archivedExchanges;
    }
    if (state.archivedExchanges.some((exchange) => (
        exchange.requestId === userMessage.requestId
    ))) {
        return state.archivedExchanges;
    }
    return [{
        requestId: userMessage.requestId,
        createdAt: userMessage.createdAt,
        status: assistantMessage.status,
        userMessage,
        assistantMessage,
    }, ...state.archivedExchanges];
}

export function beginAdvisorRequest(state, {
    requestId,
    userMessageId,
    assistantMessageId,
    content,
    createdAt,
}) {
    if (state.activeRequestId !== null) return state;
    if (!requestId || state.messages.some((message) => (
        message.id === userMessageId
        || message.id === assistantMessageId
        || message.requestId === requestId
    )) || state.archivedExchanges.some((exchange) => (
        exchange.requestId === requestId
    ))) return state;
    const archivedExchanges = archiveCurrentExchange(state);
    return nextState([
        {
            id: userMessageId,
            role: ADVISOR_MESSAGE_ROLE.USER,
            content,
            createdAt,
            status: ADVISOR_MESSAGE_STATUS.SUCCEEDED,
            requestId,
            failureCode: null,
        },
        {
            id: assistantMessageId,
            role: ADVISOR_MESSAGE_ROLE.ASSISTANT,
            content: "",
            createdAt,
            status: ADVISOR_MESSAGE_STATUS.PENDING,
            requestId,
            failureCode: null,
        },
    ], requestId, archivedExchanges);
}

function settle(state, requestId, status, content, failureCode = null) {
    if (state.activeRequestId !== requestId) return state;
    const messages = state.messages.map((message) => (
        message.requestId === requestId
        && message.role === ADVISOR_MESSAGE_ROLE.ASSISTANT
        && message.status === ADVISOR_MESSAGE_STATUS.PENDING
            ? { ...message, status, content, failureCode }
            : message
    ));
    return nextState(messages, null, state.archivedExchanges);
}

export function completeAdvisorRequest(state, requestId, content, groundedResponse = null) {
    const settled = settle(
        state,
        requestId,
        ADVISOR_MESSAGE_STATUS.SUCCEEDED,
        content,
    );
    if (settled === state || groundedResponse === null) return settled;
    return nextState(
        settled.messages.map((message) => (
            message.requestId === requestId
            && message.role === ADVISOR_MESSAGE_ROLE.ASSISTANT
                ? { ...message, groundedResponse }
                : message
        )),
        null,
        settled.archivedExchanges,
    );
}

export function failAdvisorRequest(state, requestId, failureCode) {
    const status = failureCode === "TIMED_OUT"
        ? ADVISOR_MESSAGE_STATUS.TIMED_OUT
        : failureCode === "CANCELLED"
            ? ADVISOR_MESSAGE_STATUS.CANCELLED
            : ADVISOR_MESSAGE_STATUS.FAILED;
    return settle(
        state,
        requestId,
        status,
        ADVISOR_FAILURE_MESSAGE[failureCode]
            || ADVISOR_FAILURE_MESSAGE.UNKNOWN_SAFE_FAILURE,
        failureCode,
    );
}

export function clearAdvisorConversation(state) {
    return state.activeRequestId === null ? initialAdvisorConversationState : state;
}

export function hydrateConversationFromHistory(history) {
    const exchanges = groupServerExchanges(history);
    if (exchanges.length === 0) return initialAdvisorConversationState;
    const last = exchanges[exchanges.length - 1];
    const archived = exchanges.slice(0, -1).reverse();
    const threadMessages = [
        freezeMessage(last.userMessage),
        freezeMessage(last.assistantMessage),
    ];
    return nextState(threadMessages, null, archived);
}

const SERVER_ROLE_TO_FRONTEND = Object.freeze({
    USER: ADVISOR_MESSAGE_ROLE.USER,
    ADVISOR: ADVISOR_MESSAGE_ROLE.ASSISTANT,
});

function serverMessageToFrontend(message) {
    return {
        id: message.messageId,
        role: SERVER_ROLE_TO_FRONTEND[message.role] || message.role,
        content: message.content,
        createdAt: message.createdAt,
        requestId: message.requestId || null,
        status: ADVISOR_MESSAGE_STATUS.SUCCEEDED,
        failureCode: null,
    };
}

function groupServerExchanges(history) {
    const exchanges = [];
    let open = null;
    for (const message of history) {
        if (!message
            || typeof message.messageId !== "string"
            || typeof message.content !== "string") {
            continue;
        }
        const frontendMessage = serverMessageToFrontend(message);
        if (frontendMessage.role === ADVISOR_MESSAGE_ROLE.USER) {
            if (open) exchanges.push(open);
            open = {
                requestId: message.requestId || null,
                createdAt: message.createdAt,
                userMessage: frontendMessage,
                assistantMessage: null,
                status: ADVISOR_MESSAGE_STATUS.SUCCEEDED,
            };
        } else if (frontendMessage.role === ADVISOR_MESSAGE_ROLE.ASSISTANT && open) {
            open.assistantMessage = frontendMessage;
            exchanges.push(open);
            open = null;
        }
    }
    return exchanges.filter((exchange) => exchange.assistantMessage !== null);
}
