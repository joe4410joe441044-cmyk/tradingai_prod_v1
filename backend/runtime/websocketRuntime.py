# backend/runtime/websocketRuntime.py

import asyncio
import json
import time
import random
import websockets

from backend.utils.log_buffer import logger, ws_debug

from runtime.packetIntegrity import (
    process_packet_integrity,
    get_packet_integrity_telemetry,
)


"""
====================================
CONFIG
====================================
"""

KUCOIN_WS_URL = (
    "wss://ws-api.kucoin.com"
)

HEARTBEAT_INTERVAL = 5

STALE_TIMEOUT = 10

MAX_BACKOFF = 60


"""
====================================
CONNECTION STATE
====================================
"""

class ConnectionState:

    DISCONNECTED = "DISCONNECTED"

    CONNECTING = "CONNECTING"

    AUTHENTICATING = "AUTHENTICATING"

    SUBSCRIBING = "SUBSCRIBING"

    LIVE = "LIVE"

    DEGRADED = "DEGRADED"

    RECONNECTING = "RECONNECTING"

    FAILED = "FAILED"


"""
====================================
RUNTIME HEALTH
====================================
"""

class RuntimeHealth:

    HEALTHY = "HEALTHY"

    DEGRADED = "DEGRADED"

    UNSAFE = "UNSAFE"

    CRITICAL = "CRITICAL"


"""
====================================
WEBSOCKET RUNTIME
====================================
"""

class WebSocketRuntime:

    def __init__(self):

        self.ws = None

        self.running = False

        self.connection_state = (
            ConnectionState.DISCONNECTED
        )

        self.runtime_health = (
            RuntimeHealth.HEALTHY
        )

        self.last_packet_timestamp = 0

        self.reconnect_attempts = 0

        self.reconnect_in_progress = False

        self.reconnect_lock = (
            asyncio.Lock()
        )

        self.heartbeat_task = None

        self.stale_watchdog_task = None

        self.receiver_task = None

        self.survivability_score = 1.0

        self.malformed_packets = 0

        self.packet_count = 0

        self.stale_events = 0

        self.reconnect_count = 0

        self.last_heartbeat = 0

        # ====================================
        # RUNTIME STATE
        # ====================================

        self.runtime_state = {

            "packetIntegrity": 1.0,

            "runtimeDegraded": False,

            "executionAllowed": True,

            "lastIntegrityFailure": None,

            "packetIntegrityTelemetry": {},
        }


    """
    ====================================
    STATE UPDATE
    ====================================
    """

    def update_connection_state(
        self,
        state
    ):
        previous_state = self.connection_state
        self.connection_state = state

        if state != previous_state:
            if state in {
                ConnectionState.DISCONNECTED,
                ConnectionState.DEGRADED,
                ConnectionState.RECONNECTING,
                ConnectionState.FAILED,
            }:
                logger.warning("WS state=%s", state)
            else:
                logger.info("WS state=%s", state)


    def update_runtime_health(
        self,
        health
    ):
        previous_health = self.runtime_health
        self.runtime_health = health

        if health != previous_health:
            if health == RuntimeHealth.HEALTHY:
                logger.info("Runtime health=%s", health)
            else:
                logger.warning("Runtime health=%s", health)


    """
    ====================================
    START RUNTIME
    ====================================
    """

    async def start(self):

        if self.running:

            logger.warning("WebSocket runtime already running")

            return

        self.running = True

        await self.connect()


    """
    ====================================
    CONNECT
    ====================================
    """

    async def connect(self):

        self.update_connection_state(
            ConnectionState.CONNECTING
        )

        try:

            self.ws = await websockets.connect(
                KUCOIN_WS_URL,
                ping_interval=None,
            )

            self.last_packet_timestamp = (
                time.time()
            )

            self.reconnect_attempts = 0

            self.reconnect_in_progress = False

            self.update_connection_state(
                ConnectionState.LIVE
            )

            self.update_runtime_health(
                RuntimeHealth.HEALTHY
            )

            logger.info("WS CONNECTED")

            await self.subscribe()

            self.heartbeat_task = (
                asyncio.create_task(
                    self.heartbeat_watchdog()
                )
            )

            self.stale_watchdog_task = (
                asyncio.create_task(
                    self.stale_socket_watchdog()
                )
            )

            self.receiver_task = (
                asyncio.create_task(
                    self.receive_loop()
                )
            )

        except Exception as error:

            logger.error("WS CONNECT ERROR: %s", error)

            self.update_runtime_health(
                RuntimeHealth.DEGRADED
            )

            await self.schedule_reconnect()


    """
    ====================================
    SUBSCRIBE
    ====================================
    """

    async def subscribe(self):

        self.update_connection_state(
            ConnectionState.SUBSCRIBING
        )

        subscribe_message = {

            "id": str(
                int(time.time() * 1000)
            ),

            "type": "subscribe",

            "topic": "/market/ticker:XRP-USDT",

            "privateChannel": False,

            "response": True,

        }

        await self.ws.send(
            json.dumps(
                subscribe_message
            )
        )

        self.update_connection_state(
            ConnectionState.LIVE
        )

        logger.info("WS subscription sent")


    """
    ====================================
    RECEIVE LOOP
    ====================================
    """

    async def receive_loop(self):

        try:

            async for raw_message in self.ws:

                self.last_packet_timestamp = (
                    time.time()
                )

                self.packet_count += 1

                try:

                    message = json.loads(
                        raw_message
                    )

                except Exception:

                    self.malformed_packets += 1

                    ws_debug("Malformed WebSocket packet rejected")

                    continue

                # ====================================
                # PACKET INTEGRITY LAYER
                # ====================================

                integrity_result = (
                    process_packet_integrity(
                        message
                    )
                )

                self.runtime_state[
                    "packetIntegrity"
                ] = (
                    integrity_result[
                        "integrityScore"
                    ]
                )

                self.runtime_state[
                    "packetIntegrityTelemetry"
                ] = (
                    get_packet_integrity_telemetry()
                )

                if integrity_result[
                    "degraded"
                ]:

                    self.runtime_state[
                        "runtimeDegraded"
                    ] = True

                if (
                    integrity_result[
                        "integrityScore"
                    ] < 0.5
                ):

                    self.runtime_state[
                        "executionAllowed"
                    ] = False

                # ====================================
                # REJECT INVALID PACKETS
                # ====================================

                if not integrity_result[
                    "valid"
                ]:

                    self.runtime_state[
                        "lastIntegrityFailure"
                    ] = (
                        integrity_result[
                            "reason"
                        ]
                    )

                    ws_debug(
                        "WebSocket packet rejected reason=%s",
                        integrity_result["reason"],
                    )

                    continue

                # ====================================
                # NORMALIZED PACKET ONLY
                # ====================================

                message = (
                    integrity_result[
                        "normalized"
                    ]
                )

                # ====================================
                # HANDLE MESSAGE
                # ====================================

                await self.handle_message(
                    message
                )

        except Exception as error:

            logger.error("WS RECEIVE ERROR: %s", error)

            self.update_runtime_health(
                RuntimeHealth.DEGRADED
            )

            await self.schedule_reconnect()


    """
    ====================================
    HANDLE MESSAGE
    ====================================
    """

    async def handle_message(
        self,
        message
    ):

        ws_debug("WebSocket message=%s", message)

        # ====================================
        # SURVIVABILITY UPDATE
        # ====================================

        self.calculate_survivability()


    """
    ====================================
    HEARTBEAT WATCHDOG
    ====================================
    """

    async def heartbeat_watchdog(self):

        while self.running:

            try:

                if self.ws:

                    ping_message = {

                        "id": str(
                            int(
                                time.time() * 1000
                            )
                        ),

                        "type": "ping",
                    }

                    await self.ws.send(
                        json.dumps(
                            ping_message
                        )
                    )

                    self.last_heartbeat = (
                        time.time()
                    )

            except Exception as error:

                logger.error("WS HEARTBEAT ERROR: %s", error)

                self.update_runtime_health(
                    RuntimeHealth.DEGRADED
                )

            await asyncio.sleep(
                HEARTBEAT_INTERVAL
            )


    """
    ====================================
    STALE SOCKET WATCHDOG
    ====================================
    """

    async def stale_socket_watchdog(
        self
    ):

        while self.running:

            now = time.time()

            stale_duration = (
                now -
                self.last_packet_timestamp
            )

            if (
                stale_duration >
                STALE_TIMEOUT
            ):

                self.stale_events += 1

                logger.warning("WS stale socket detected")

                self.update_runtime_health(
                    RuntimeHealth.DEGRADED
                )

                await self.force_reconnect()

            await asyncio.sleep(2)


    """
    ====================================
    FORCE RECONNECT
    ====================================
    """

    async def force_reconnect(self):

        try:

            if self.ws:

                await self.ws.close()

        except Exception as error:

            logger.error("WS FORCE RECONNECT ERROR: %s", error)

        await self.schedule_reconnect()


    """
    ====================================
    RECONNECT LOGIC
    ====================================
    """

    async def schedule_reconnect(
        self
    ):

        async with self.reconnect_lock:

            if self.reconnect_in_progress:

                ws_debug("WebSocket reconnect already running")

                return

            self.reconnect_in_progress = True

            self.reconnect_count += 1

            self.reconnect_attempts += 1

            self.update_connection_state(
                ConnectionState.RECONNECTING
            )

            self.update_runtime_health(
                RuntimeHealth.DEGRADED
            )

            backoff = min(
                2 ** self.reconnect_attempts,
                MAX_BACKOFF
            )

            jitter = random.uniform(
                0,
                1
            )

            reconnect_delay = (
                backoff + jitter
            )

            logger.warning(
                "WS RECONNECT in %.2fs",
                reconnect_delay,
            )

            await asyncio.sleep(
                reconnect_delay
            )

            self.reconnect_in_progress = False

            await self.connect()


    """
    ====================================
    SURVIVABILITY SCORE
    ====================================
    """

    def calculate_survivability(
        self
    ):

        score = 1.0

        score -= (
            self.reconnect_count * 0.05
        )

        score -= (
            self.stale_events * 0.05
        )

        score -= (
            self.malformed_packets * 0.01
        )

        # ====================================
        # PACKET INTEGRITY PENALTY
        # ====================================

        integrity_score = (
            self.runtime_state.get(
                "packetIntegrity",
                1.0
            )
        )

        if integrity_score < 1.0:

            score -= (
                (1.0 - integrity_score)
                * 0.25
            )

        score = max(
            0.0,
            min(score, 1.0)
        )

        self.survivability_score = (
            score
        )

        """
        HEALTH STATE
        """

        if score >= 0.8:

            self.update_runtime_health(
                RuntimeHealth.HEALTHY
            )

        elif score >= 0.5:

            self.update_runtime_health(
                RuntimeHealth.DEGRADED
            )

        elif score >= 0.3:

            self.update_runtime_health(
                RuntimeHealth.UNSAFE
            )

        else:

            self.update_runtime_health(
                RuntimeHealth.CRITICAL
            )


    """
    ====================================
    TELEMETRY PACKET
    ====================================
    """

    def build_runtime_packet(
        self
    ):

        return {

            "connectionState":
                self.connection_state,

            "runtimeHealth":
                self.runtime_health,

            "survivability":
                round(
                    self.survivability_score,
                    3
                ),

            "packetIntegrity":
                self.runtime_state[
                    "packetIntegrity"
                ],

            "runtimeDegraded":
                self.runtime_state[
                    "runtimeDegraded"
                ],

            "executionAllowed":
                self.runtime_state[
                    "executionAllowed"
                ],

            "lastIntegrityFailure":
                self.runtime_state[
                    "lastIntegrityFailure"
                ],

            "packetIntegrityTelemetry":
                self.runtime_state[
                    "packetIntegrityTelemetry"
                ],

            "reconnectCount":
                self.reconnect_count,

            "malformedPackets":
                self.malformed_packets,

            "staleEvents":
                self.stale_events,

            "packetCount":
                self.packet_count,

            "lastPacketTimestamp":
                self.last_packet_timestamp,
        }


    """
    ====================================
    STOP RUNTIME
    ====================================
    """

    async def stop(self):

        self.running = False

        self.update_connection_state(
            ConnectionState.DISCONNECTED
        )

        try:

            if self.ws:

                await self.ws.close()

        except Exception as error:

            logger.error("WS STOP ERROR: %s", error)

        logger.info("WebSocket runtime stopped")
