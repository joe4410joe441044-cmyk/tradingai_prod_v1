import {
    CSRF_TOKEN_HEADER,
    readCsrfToken,
} from "../features/auth/operatorAuth.js";

export async function requestBotStop({
    endpoint = "/api/bot/stop",
    fetcher = fetch,
} = {}) {
    const headers = {};
    const csrfToken = readCsrfToken();
    if (csrfToken) {
        headers[CSRF_TOKEN_HEADER] = csrfToken;
    }
    const response = await fetcher(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers,
    });

    if (!response.ok) {
        throw new Error(await response.text());
    }

    return response.json();
}
