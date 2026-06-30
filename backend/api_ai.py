from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.utils.log_buffer import logger

app = FastAPI()

# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# TRADE CORE
# =========================

trade_core = None


def set_trade_core(core):

    global trade_core

    trade_core = core


# =========================
# AI STATUS
# =========================

@app.get("/api/ai/status")
def ai_status():

    global trade_core

    if not trade_core:

        return {
            "error": "no_trade_core"
        }

    return {

        "ai_score": getattr(
            trade_core,
            "ai_last_score",
            None
        ),

        "ai_decision": getattr(
            trade_core,
            "ai_last_decision",
            None
        ),

        "open_positions": len(
            getattr(
                trade_core,
                "positions",
                {}
            )
        ),
    }


# =========================
# AI LOGS
# =========================

@app.get("/api/ai/logs")
def ai_logs():

    global trade_core

    if not trade_core:

        return []

    ai_logger = getattr(
        trade_core,
        "ai_logger",
        None
    )

    if not ai_logger:

        return []

    return getattr(
        ai_logger,
        "logs",
        []
    )[-100:]


# =========================
# POSITIONS + EXECUTION
# =========================

@app.get("/api/positions")
def positions():

    global trade_core

    # =========================
    # NO TRADE CORE
    # =========================

    if not trade_core:

        return {

            "execution": {

                "bot_running": False,

                "ws_connected": False,

                "real_order_allowed": False,

                "position_active": False,

                "position_side": None,

                "cooldown_active": False,

                "execution_mode": "SIMULATION",

                "market_ready": False,
            },

            "positions": [],
        }

    # =========================
    # SAFE ACCESS
    # =========================

    positions_dict = getattr(
        trade_core,
        "positions",
        {}
    )

    config = getattr(
        trade_core,
        "config",
        {}
    )

    ws = getattr(
        trade_core,
        "ws",
        None
    )

    # =========================
    # POSITION SIDE
    # =========================

    position_side = None

    try:

        if positions_dict:

            first_position = next(
                iter(
                    positions_dict.values()
                )
            )

            position_side = getattr(
                first_position,
                "trade_type",
                None
            )

    except Exception:

        position_side = None

    # =========================
    # EXECUTION SNAPSHOT
    # =========================

    execution = {

        "bot_running": getattr(
            trade_core,
            "_running",
            False
        ),

        "ws_connected": (

            ws is not None

            and

            getattr(
                ws,
                "connected",
                False
            )

        ),

        "real_order_allowed": (

            not config.get(
                "dry_run",
                True
            )

        ),

        "position_active": (
            len(positions_dict) > 0
        ),

        "position_side": (
            position_side
        ),

        "cooldown_active": False,

        "execution_mode": (

            "SIMULATION"

            if config.get(
                "dry_run",
                True
            )

            else "LIVE"

        ),

        "market_ready": getattr(
            trade_core,
            "market_ready",
            False
        ),
    }

    # =========================
    # POSITION LIST
    # =========================

    positions_data = []

    try:

        for p in positions_dict.values():

            positions_data.append({

                "id": getattr(
                    p,
                    "id",
                    None
                ),

                "symbol": getattr(
                    p,
                    "symbol",
                    None
                ),

                "type": getattr(
                    p,
                    "trade_type",
                    None
                ),

                "entry": getattr(
                    p,
                    "entry_price",
                    None
                ),

                "sl": getattr(
                    p,
                    "sl",
                    None
                ),

                "tp": getattr(
                    p,
                    "tp",
                    None
                ),

                "status": getattr(
                    p,
                    "status",
                    None
                ),
            })

    except Exception as err:

        logger.error("POSITION BUILD ERROR: %s", err)

    # =========================
    # RESPONSE
    # =========================

    return {

        "execution": execution,

        "positions": positions_data,
    }
