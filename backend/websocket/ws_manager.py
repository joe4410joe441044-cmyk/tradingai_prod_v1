# backend/websocket/ws_manager.py

from fastapi import WebSocket

# ============================================================
# RUNTIME REGISTRY
# ============================================================

# IMPORTANT:
# ------------------------------------------------------------
# Do NOT import trading_runtime directly from main.py
#
# That can create circular imports.
#
# Use runtime registry instead.
# ============================================================

import backend.runtime.runtime_registry as registry

from backend.runtime.adapters.execution_signal_adapter import (
    ExecutionSignalAdapter
)

from backend.bot_manager.bot_manager import (
    get_bot_manager
)




class ConnectionManager:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):

        self.active_connections = []

    # ========================================================
    # CONNECT
    # ========================================================

    async def connect(
        self,
        websocket: WebSocket,
    ):

        await websocket.accept()

        self.active_connections.append(
            websocket
        )

    # ========================================================
    # DISCONNECT
    # ========================================================

    def disconnect(
        self,
        websocket: WebSocket,
    ):

        if websocket in self.active_connections:

            self.active_connections.remove(
                websocket
            )

    # ========================================================
    # BROADCAST
    # ========================================================

    async def broadcast(
        self,
        message: dict,
    ):

        disconnected = []

        for connection in self.active_connections:

            try:

                await connection.send_json(
                    message
                )

            except Exception:

                disconnected.append(
                    connection
                )

        # ----------------------------------------------------
        # Cleanup Dead Connections
        # ----------------------------------------------------

        for connection in disconnected:

            self.disconnect(connection)

    # ========================================================
    # EXECUTION RUNTIME PIPELINE
    # ========================================================

    async def process_microstructure_runtime(
        self,
        microstructure_state,
    ):

        try:

            # ------------------------------------------------
            # Runtime Registry Validation
            # ------------------------------------------------

            if (
                registry.trading_runtime
                is None
            ):

                return {

                    "valid": False,

                    "reason": (
                        "TRADING_RUNTIME_UNAVAILABLE"
                    ),
                }

            # ------------------------------------------------
            # Trading Runtime
            # ------------------------------------------------

            print(
                "[WS_MANAGER] runtime pipeline reached"
            )

            runtime_result = (

                registry.trading_runtime
                .process_runtime(
                    microstructure_state
                )
            )

            # ------------------------------------------------
            # Runtime -> Engine Wiring
            # ------------------------------------------------

            execution_event = (
                runtime_result
                .get("runtime", {})
                .get("execution")
            )

            signal = (
                ExecutionSignalAdapter.adapt(
                    execution_event
                )
            )

            if signal:

                bot_manager = get_bot_manager()

                if (
                    bot_manager
                    and bot_manager.engine
                ):

                    bot_manager.engine.submit_signal(
                        signal
                    )

            # ------------------------------------------------
            # Broadcast Runtime Telemetry
            # ------------------------------------------------

            await self.broadcast({

                "type": (
                    "execution_runtime"
                ),

                "data": runtime_result,
            })

            # ------------------------------------------------
            # Return Runtime Result
            # ------------------------------------------------

            return runtime_result

        except Exception as e:

            return {

                "valid": False,

                "reason": str(e),
            }


# ============================================================
# GLOBAL CONNECTION MANAGER
# ============================================================

manager = ConnectionManager()