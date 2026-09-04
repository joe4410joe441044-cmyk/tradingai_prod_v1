import assert from "node:assert/strict";
import test from "node:test";

import { requestBotStop } from "./botLifecycle.js";

test("UI bot stop request posts to the bot lifecycle endpoint", async () => {
    const requests = [];
    const result = await requestBotStop({
        fetcher: async (url, options) => {
            requests.push({ url, options });
            return {
                ok: true,
                json: async () => ({ status: "stopped" }),
            };
        },
    });

    assert.deepEqual(requests, [{
        url: "/api/bot/stop",
        options: {
            method: "POST",
            credentials: "same-origin",
            headers: {},
        },
    }]);
    assert.deepEqual(result, { status: "stopped" });
});
