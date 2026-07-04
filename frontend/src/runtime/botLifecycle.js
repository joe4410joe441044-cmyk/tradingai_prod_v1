export async function requestBotStop({
    endpoint = "/api/bot/stop",
    fetcher = fetch,
} = {}) {
    const response = await fetcher(endpoint, { method: "POST" });

    if (!response.ok) {
        throw new Error(await response.text());
    }

    return response.json();
}
