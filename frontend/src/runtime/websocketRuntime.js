// frontend/src/runtime/websocketRuntime.js

import {
    telemetryStore,
} from "../store/telemetryStore";

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

let heartbeatInterval = null;

let staleCheckInterval = null;

let lastPacketTimestamp = 0;


/*
====================================
CONFIG
====================================
*/

const WS_URL =
    "ws://35.194.104.74:8001/ws";

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

let connectionState =
    ConnectionState.DISCONNECTED;


/*
====================================
UPDATE RUNTIME STATE
====================================
*/

function updateRuntimeState(
    state
) {

    connectionState = state;

    telemetryStore.runtime = {

        ...telemetryStore.runtime,

        connectionState:
            state,

        reconnectAttempts,

        lastPacketTimestamp,

    };

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

    ws.onclose = () => {

        console.log(
            "[WS] Disconnected"
        );

        cleanupWatchdogs();

        updateRuntimeState(
            ConnectionState.DISCONNECTED
        );

        scheduleReconnect();

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

            telemetryStore.runtime = {

                ...telemetryStore.runtime,

                malformedPackets:
                    (
                        telemetryStore
                            .runtime
                            ?.malformedPackets || 0
                    ) + 1,

            };

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

                /*
        ====================================
        BOT RESULT PAYLOAD
        ====================================
        */

        if (
            message &&
            typeof message === "object" &&
            "price" in message
        ) {
            telemetryStore.market = {
                ...telemetryStore.market,

                price: message.price,
                balance: message.balance,
                equity: message.equity,
                pnl: message.pnl,

                position:
                    message.position_side
                    || "NONE",
            };
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

            telemetryStore.runtime = {

                ...telemetryStore.runtime,

                ...message.data,

            };

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

            telemetryStore.market = {

                ...telemetryStore.market,

                ...message.data,

            };

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

            telemetryStore.runtime = {

                ...telemetryStore.runtime,

                staleDuration,

            };

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

    cleanupWatchdogs();

    reconnectInProgress =
        false;

    reconnectAttempts = 0;

    if (
        ws
    ) {

        ws.close();

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