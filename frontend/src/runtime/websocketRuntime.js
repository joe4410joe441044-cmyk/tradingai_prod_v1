// frontend/src/runtime/websocketRuntime.js

import {
    telemetryStore,
    updateMarketTelemetry,
    updateRuntimeTelemetry,
} from "../store/telemetryStore.js";

window.telemetryStore =
    telemetryStore;


/*
====================================
WEBSOCKET RUNTIME
====================================
*/

let ws = null;

let reconnectTimeout = null;

let reconnectAttempts = 0;

let reconnectInProgress = false;

let runtimeStopped = true;

const intentionallyClosedSockets = new WeakSet();

let heartbeatInterval = null;

let staleCheckInterval = null;

let lastPacketTimestamp = 0;


/*
====================================
CONFIG
====================================
*/

const RUNTIME_ENV = import.meta.env || {};

const WS_URL = RUNTIME_ENV.VITE_WS_URL || `${
    window.location.protocol === "https:" ? "wss" : "ws"
}://${window.location.host}/ws`;

const HEARTBEAT_INTERVAL =
    5000;

const STALE_TIMEOUT =
    10000;

const MAX_BACKOFF =
    60000;


/*
====================================
CONNECTION STATE
====================================
*/

export const ConnectionState = {

    DISCONNECTED:
        "DISCONNECTED",

    CONNECTING:
        "CONNECTING",

    LIVE:
        "LIVE",

    DEGRADED:
        "DEGRADED",

    RECONNECTING:
        "RECONNECTING",

};

/*
====================================
UPDATE RUNTIME STATE
====================================
*/

function updateRuntimeState(
    state
) {

    updateRuntimeTelemetry({
        connectionState:
            state,

        wsStatus:
            state,

        websocketConnected:
            state === ConnectionState.LIVE,

        reconnectAttempts,

        lastPacketTimestamp,
        streamDisconnected: state === ConnectionState.DISCONNECTED,
        streamStale: state !== ConnectionState.LIVE,
    });

    /*
    EXECUTION RUNTIME MIRROR
    */

    telemetryStore.executionRuntime = {

        ...telemetryStore.executionRuntime,

        websocketHealthy:
            (
                state ===
                ConnectionState.LIVE
            ),

        cognitionRuntimeActive:
            (
                state !==
                ConnectionState.DISCONNECTED
            ),

        runtimeHealthy:
            (
                state ===
                ConnectionState.LIVE
            ),

    };

    console.log(
        "[WS STATE]",
        state
    );

}


/*
====================================
START RUNTIME
====================================
*/

export function startWebSocketRuntime() {

    runtimeStopped = false;

    /*
    Prevent duplicate runtime
    */

    if (
        ws &&
        (
            ws.readyState ===
            WebSocket.OPEN ||

            ws.readyState ===
            WebSocket.CONNECTING
        )
    ) {

        console.log(
            "[WS] Runtime Already Active"
        );

        return;

    }

    connectWebSocket();

}


/*
====================================
CONNECT
====================================
*/

function connectWebSocket() {

    updateRuntimeState(
        ConnectionState.CONNECTING
    );

    ws = new WebSocket(
        WS_URL
    );

    /*
    ====================================
    OPEN
    ====================================
    */

    ws.onopen = () => {

        console.log(
            "[WS] Connected"
        );

        reconnectAttempts = 0;

        reconnectInProgress =
            false;

        lastPacketTimestamp =
            Date.now();

        updateRuntimeState(
            ConnectionState.LIVE
        );

        startHeartbeatWatchdog();

        startStaleSocketWatchdog();

    };

    /*
    ====================================
    CLOSE
    ====================================
    */

    ws.onclose = (event) => {

        const closedSocket = event.currentTarget;
        const intentionallyClosed = intentionallyClosedSockets.has(closedSocket);
        if (intentionallyClosed) {
            intentionallyClosedSockets.delete(closedSocket);
        }
        if (closedSocket !== ws) {
            return;
        }
        ws = null;

        console.log(
            "[WS] Disconnected"
        );

        cleanupWatchdogs();

        updateRuntimeState(
            ConnectionState.DISCONNECTED
        );

        if (!runtimeStopped && !intentionallyClosed) {
            scheduleReconnect();
        }

    };

    /*
    ====================================
    ERROR
    ====================================
    */

    ws.onerror = (error) => {

        console.error(
            "[WS] Error",
            error
        );

        updateRuntimeState(
            ConnectionState.DEGRADED
        );

    };

    /*
    ====================================
    MESSAGE
    ====================================
    */

    ws.onmessage = (event) => {

        lastPacketTimestamp =
            Date.now();

        updateRuntimeTelemetry({
            lastPacketTimestamp,

            lastMessageTimestamp:
                lastPacketTimestamp,
            streamDisconnected: false,
            streamStale: false,
        });

        let message = null;

        /*
        ====================================
        MALFORMED PACKET PROTECTION
        ====================================
        */

        try {

            message = JSON.parse(
                event.data
            );

        } catch (error) {

            console.error(
                "[WS] Malformed Packet",
                error
            );

            updateRuntimeTelemetry({
                malformedPackets:
                    (
                        telemetryStore
                            .runtime
                            ?.malformedPackets || 0
                    ) + 1,
            });

            telemetryStore.executionRuntime = {

                ...telemetryStore.executionRuntime,

                packetIntegrity: 0,

                runtimeDegraded: true,

                suppressionReason:
                    "MALFORMED_PACKET",

            };

            return;

        }

        /*
        ====================================
        RAW PACKET VALIDATION
        ====================================
        */

        console.log(
            "[WS RAW PACKET]",
            message
        );

        const formalMarket = message?.market;
        if (formalMarket && typeof formalMarket === "object" && !Array.isArray(formalMarket)) {
            updateMarketTelemetry({
                exchange: formalMarket.exchange,
                marketType: formalMarket.marketType,
                exchangeSymbol: formalMarket.exchangeSymbol,
                timestamp: formalMarket.timestamp,
                sequence: formalMarket.sequence,
                price: formalMarket.price,
                bestBid: formalMarket.bestBid,
                bestAsk: formalMarket.bestAsk,
                spread: formalMarket.spread,
                orderBook: formalMarket.orderBook,
                dataQuality: formalMarket.dataQuality,
                lastUpdate: lastPacketTimestamp,
            });
        }

                /*
        ====================================
        BOT RESULT PAYLOAD
        ====================================
        */

        if (
            message &&
            typeof message === "object" &&
            "price" in message &&
            !formalMarket
        ) {
            if ("status" in message) {
                updateRuntimeTelemetry({
                    botStatus: message,
                    botStatusLastUpdate: lastPacketTimestamp,
                });
            }

            const marketUpdate = {
                price: message.price,
                bestBid: message.bestBid ?? message.best_bid,
                bestAsk: message.bestAsk ?? message.best_ask,
                exchange: message.exchange,
                exchangeSymbol: message.symbol,
                symbol: message.symbol,
                marketType: message.marketType,
                lastUpdate: lastPacketTimestamp,
            };

            if ("balance" in message) {
                marketUpdate.balance = message.balance;
            }

            if ("equity" in message) {
                marketUpdate.equity = message.equity;
            }

            if ("pnl" in message) {
                marketUpdate.pnl = message.pnl;
            }

            if ("availableBalance" in message) {
                marketUpdate.availableBalance = message.availableBalance;
            }

            if ("available_balance" in message) {
                marketUpdate.available_balance = message.available_balance;
            }

            if ("position_side" in message || "position" in message) {
                marketUpdate.position =
                    message.position_side
                    ?? message.position;
            }

            updateMarketTelemetry(marketUpdate);
        }

        /*
        ====================================
        GOVERNANCE UPDATE
        ====================================
        */

        if (
            message.type ===
            "governance_update"
        ) {

            telemetryStore.governance = {

                ...telemetryStore.governance,

                ...message.data,

                lastUpdate:
                    lastPacketTimestamp,

            };

        }

        /*
        ====================================
        RUNTIME UPDATE
        ====================================
        */

        if (
            message.type ===
            "runtime_update"
        ) {

            updateRuntimeTelemetry({
                ...message.data,
            });

        }

        /*
        ====================================
        EXECUTION RUNTIME UPDATE
        ====================================
        */

        if (
            message.type ===
            "execution_runtime"
        ) {

            telemetryStore.executionRuntime = {

                ...telemetryStore.executionRuntime,

                ...message.data,

                lastUpdate:
                    lastPacketTimestamp,

            };

            console.log(
                "[EXECUTION RUNTIME]",
                telemetryStore
                    .executionRuntime
            );

        }

        /*
        ====================================
        COGNITION UPDATE
        ====================================
        */

        if (
            message.type ===
            "cognition_update"
        ) {

            telemetryStore.cognition = {

                ...telemetryStore.cognition,

                ...message.data,

                lastUpdate:
                    lastPacketTimestamp,

            };

        }

        /*
        ====================================
        MARKET UPDATE
        ====================================
        */

        if (
            message.type ===
            "market_update"
        ) {

            updateMarketTelemetry({
                ...message.data,

                lastUpdate:
                    lastPacketTimestamp,
            });

        }

        /*
        ====================================
        EXECUTION UPDATE
        ====================================
        */

        if (
            message.type ===
            "execution_update"
        ) {

            telemetryStore.execution = {

                ...telemetryStore.execution,

                ...message.data,

                lastUpdate:
                    lastPacketTimestamp,

            };

        }

    };

}


/*
====================================
RECONNECT LOGIC
====================================
*/

function scheduleReconnect() {

    if (runtimeStopped) {
        return;
    }

    /*
    Duplicate reconnect suppression
    */

    if (
        reconnectInProgress
    ) {

        console.log(
            "[WS] Reconnect Already Running"
        );

        return;

    }

    reconnectInProgress = true;

    reconnectAttempts += 1;

    updateRuntimeState(
        ConnectionState.RECONNECTING
    );

    /*
    Exponential backoff
    */

    const backoff = Math.min(

        1000 *
        Math.pow(
            2,
            reconnectAttempts
        ),

        MAX_BACKOFF

    );

    console.log(
        `[WS] Reconnect Scheduled (${backoff}ms)`
    );

    reconnectTimeout =
        setTimeout(() => {

            if (runtimeStopped) {
                reconnectInProgress = false;
                return;
            }

            reconnectInProgress =
                false;

            connectWebSocket();

        }, backoff);

}


/*
====================================
HEARTBEAT WATCHDOG
====================================
*/

function startHeartbeatWatchdog() {

    clearInterval(
        heartbeatInterval
    );

    heartbeatInterval =
        setInterval(() => {

            if (
                !ws ||
                ws.readyState !==
                WebSocket.OPEN
            ) {

                return;

            }

            try {

                ws.send(
                    JSON.stringify({

                        type: "ping",

                        timestamp:
                            Date.now(),

                    })
                );

            } catch (error) {

                console.error(
                    "[WS] Heartbeat Failed",
                    error
                );

                updateRuntimeState(
                    ConnectionState.DEGRADED
                );

            }

        }, HEARTBEAT_INTERVAL);

}


/*
====================================
STALE SOCKET WATCHDOG
====================================
*/

function startStaleSocketWatchdog() {

    clearInterval(
        staleCheckInterval
    );

    staleCheckInterval =
        setInterval(() => {

            const now =
                Date.now();

            const staleDuration =
                now -
                lastPacketTimestamp;

            updateRuntimeTelemetry({
                staleDuration,
            });

            /*
            STALE DETECTION
            */

            if (
                staleDuration >
                STALE_TIMEOUT
            ) {

                console.warn(
                    "[WS] Stale Socket Detected"
                );

                telemetryStore.executionRuntime = {

                    ...telemetryStore.executionRuntime,

                    runtimeDegraded: true,

                    suppressionReason:
                        "STALE_SOCKET",

                    websocketHealthy:
                        false,

                };

                updateRuntimeState(
                    ConnectionState.DEGRADED
                );

                if (
                    ws
                ) {

                    ws.close();

                }

            }

        }, 2000);

}


/*
====================================
CLEANUP
====================================
*/

function cleanupWatchdogs() {

    clearInterval(
        heartbeatInterval
    );

    clearInterval(
        staleCheckInterval
    );

    clearTimeout(
        reconnectTimeout
    );

}


/*
====================================
STOP RUNTIME
====================================
*/

export function stopWebSocketRuntime() {

    runtimeStopped = true;

    cleanupWatchdogs();

    reconnectInProgress =
        false;

    reconnectAttempts = 0;

    if (
        ws
    ) {

        intentionallyClosedSockets.add(ws);
        ws.close();
        ws = null;

    }

    telemetryStore.executionRuntime = {

        ...telemetryStore.executionRuntime,

        websocketHealthy:
            false,

        cognitionRuntimeActive:
            false,

        runtimeHealthy:
            false,

        suppressionReason:
            "RUNTIME_STOPPED",

    };

    updateRuntimeState(
        ConnectionState.DISCONNECTED
    );

}


window.telemetryStore =
    telemetryStore;
