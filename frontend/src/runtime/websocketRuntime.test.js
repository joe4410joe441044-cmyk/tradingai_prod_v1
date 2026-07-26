import assert from "node:assert/strict";
import test from "node:test";

class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;

    static instances = [];

    constructor(url) {
        this.url = url;
        this.readyState = FakeWebSocket.CONNECTING;
        FakeWebSocket.instances.push(this);
    }

    close() {
        this.readyState = 3;
        queueMicrotask(() => this.onclose?.({ currentTarget: this }));
    }

    send() {}
}

globalThis.window = {
    location: { protocol: "http:", host: "localhost" },
};
globalThis.WebSocket = FakeWebSocket;

const {
    startWebSocketRuntime,
    stopWebSocketRuntime,
} = await import("./websocketRuntime.js");

test("intentional runtime stop closes the socket without scheduling reconnect", async () => {
    const originalSetTimeout = globalThis.setTimeout;
    let reconnectTimers = 0;
    globalThis.setTimeout = () => {
        reconnectTimers += 1;
        return 1;
    };

    try {
        startWebSocketRuntime();
        assert.equal(FakeWebSocket.instances.length, 1);

        stopWebSocketRuntime();
        await Promise.resolve();
        await Promise.resolve();

        assert.equal(reconnectTimers, 0);
        assert.equal(FakeWebSocket.instances.length, 1);
    } finally {
        globalThis.setTimeout = originalSetTimeout;
        stopWebSocketRuntime();
    }
});
