import {
    useEffect,
    useMemo,
    useRef,
} from "react";

import "../../styles/dashboard.css";

/* =========================================================
   SAFE ARRAY
========================================================= */

const safeArray = (value) => {

    return Array.isArray(value)
        ? value
        : [];

};

/* =========================================================
   FORMAT TIME
========================================================= */

const formatTime = (value) => {

    if (!value) {

        return "--:--:--";

    }

    try {

        return new Date(value)
            .toLocaleTimeString();

    } catch {

        return "--:--:--";

    }

};

/* =========================================================
   SOURCE ENUM
========================================================= */

const normalizeSource = (
    type = ""
) => {

    const t =
        String(type)
            .toLowerCase();

    if (
        t.includes("router")
    ) {

        return "ROUTER";

    }

    if (
        t.includes("market")
    ) {

        return "MARKET";

    }

    if (
        t.includes("micro")
    ) {

        return "MICRO";

    }

    if (
        t.includes("runtime")
    ) {

        return "SYSTEM";

    }

    if (
        t.includes("risk")
    ) {

        return "ENGINE";

    }

    if (
        t.includes("execution")
    ) {

        return "EXEC";

    }

    if (
        t.includes("restriction")
    ) {

        return "ENGINE";

    }

    return "SYSTEM";

};

/* =========================================================
   LEVEL ENUM
========================================================= */

const normalizeLevel = (
    type = ""
) => {

    const t =
        String(type)
            .toLowerCase();

    if (
        t.includes("risk")
    ) {

        return "WARN";

    }

    if (
        t.includes("restriction")
    ) {

        return "WARN";

    }

    if (
        t.includes("error")
    ) {

        return "ERROR";

    }

    if (
        t.includes("failure")
    ) {

        return "ERROR";

    }

    return "INFO";

};

/* =========================================================
   STATE ENUM
========================================================= */

const normalizeState = (
    message = ""
) => {

    const m =
        String(message)
            .toLowerCase();

    if (
        m.includes("reconnect")
    ) {

        return "RECONNECT";

    }

    if (
        m.includes("stale")
    ) {

        return "STALE";

    }

    if (
        m.includes("blocked")
    ) {

        return "BLOCKED";

    }

    if (
        m.includes("degraded")
    ) {

        return "DEGRADED";

    }

    if (
        m.includes("failure")
    ) {

        return "FAILURE";

    }

    if (
        m.includes("disconnect")
    ) {

        return "DISCONNECTED";

    }

    return "UNKNOWN";

};

/* =========================================================
   CATEGORY CLASS
========================================================= */

const categoryClass = (
    level = ""
) => {

    const t =
        String(level)
            .toLowerCase();

    if (
        t.includes("error")
    ) {

        return "error";

    }

    if (
        t.includes("warn")
    ) {

        return "warning";

    }

    return "system";

};

/* =========================================================
   BUILD RUNTIME EVENTS
========================================================= */

const buildRuntimeEvents = ({

    signalLogs = [],
    tradeLogs = [],

    unifiedTelemetry = {},

    journalTelemetry = {},

}) => {

    const events = [];


    /* =====================================================
       MARKET
    ===================================================== */

    if (
        unifiedTelemetry?.market
            ?.marketHostility >
        0.7
    ) {

        events.push({

            timestamp:
                Date.now(),

            source:
                "MARKET",

            level:
                "WARN",

            state:
                "HOSTILE",

        });

    }

    /* =====================================================
       RUNTIME
    ===================================================== */

    if (
        unifiedTelemetry?.runtime
            ?.streamStale
    ) {

        events.push({

            timestamp:
                Date.now(),

            source:
                "SYSTEM",

            level:
                "WARN",

            state:
                "STALE",

        });

    }

    if (
        unifiedTelemetry?.runtime
            ?.reconnectInProgress
    ) {

        events.push({

            timestamp:
                Date.now(),

            source:
                "SYSTEM",

            level:
                "WARN",

            state:
                "RECONNECT",

        });

    }

    if (
        unifiedTelemetry?.runtime
            ?.websocketHealth < 50
    ) {

        events.push({

            timestamp:
                Date.now(),

            source:
                "SYSTEM",

            level:
                "WARN",

            state:
                "DEGRADED",

        });

    }

    /* =====================================================
       RISK
    ===================================================== */

    if (
        unifiedTelemetry?.risk
            ?.restrictionReason &&
        unifiedTelemetry?.risk
            ?.restrictionReason !==
        "NONE"
    ) {

        events.push({

            timestamp:
                Date.now(),

            source:
                "ENGINE",

            level:
                "WARN",

            state:
                "BLOCKED",

        });

    }

    /* =====================================================
       JOURNAL
    ===================================================== */

    if (
        journalTelemetry
            ?.crashRecoveryDetected
    ) {

        events.push({

            timestamp:
                Date.now(),

            source:
                "SYSTEM",

            level:
                "INFO",

            state:
                "RECOVERY",

        });

    }

    /* =====================================================
       SIGNAL LOGS
    ===================================================== */

    safeArray(signalLogs)
        .slice(-30)
        .forEach((entry) => {

            events.push({

                timestamp:
                    entry?.timestamp ??
                    Date.now(),

                source:
                    normalizeSource(
                        entry?.type
                    ),

                level:
                    normalizeLevel(
                        entry?.type
                    ),

                state:
                    normalizeState(
                        entry?.type,
                        entry?.message
                    ),

            });

        });
            /* =====================================================
       TRADE LOGS
    ===================================================== */

    safeArray(tradeLogs)
        .slice(-30)
        .forEach((entry) => {

            events.push({

                timestamp:
                    entry?.timestamp ??
                    Date.now(),

                source:
                    normalizeSource(
                        entry?.type
                    ),

                level:
                    normalizeLevel(
                        entry?.type
                    ),

                state:
                    normalizeState(
                        entry?.type,
                        entry?.message
                    ),

            });

        });

    return events
        .sort((a, b) => {

            return (
                Number(a.timestamp) -
                Number(b.timestamp)
            );

        })
        .slice(-120);

};

/* =========================================================
   LOGS PANEL
========================================================= */

export default function LogsPanel({

    signalLogs = [],
    tradeLogs = [],

    routerTelemetry = {},

    unifiedTelemetry = {},

    journalTelemetry = {},

    loading = false,

    error = false,

}) {

    const streamRef =
        useRef(null);

    const runtimeEvents =
        useMemo(() => {

            return buildRuntimeEvents({

                signalLogs,
                tradeLogs,

                routerTelemetry,

                unifiedTelemetry,

                journalTelemetry,

            });

        }, [

            signalLogs,
            tradeLogs,

            routerTelemetry,

            unifiedTelemetry,

            journalTelemetry,

        ]);

    /* =====================================================
       AUTO SCROLL
    ===================================================== */

    useEffect(() => {

        if (!streamRef.current) {

            return;

        }

        streamRef.current.scrollTop =
            streamRef.current.scrollHeight;

    }, [runtimeEvents]);

    /* =====================================================
       UI
    ===================================================== */

    return (

        <div className="panel-card logs-panel">

            {/* =============================================
               HEADER
            ============================================= */}

            <div className="panel-title">

                CENTER | EVENT STREAM

            </div>

            {/* =============================================
               STREAM
            ============================================= */}

            <div
                ref={streamRef}
                className="log-stream"
            >

                <div className="log-stream-line">

                    <div>
                        TIME
                    </div>

                    <div>
                        SOURCE
                    </div>

                    <div>
                        LEVEL
                    </div>

                    <div>
                        STATE
                    </div>

                </div>
                                {/* =============================================
                   LOADING
                ============================================= */}

                {loading && (

                    <div className="log-stream-line">

                        <div>
                            WAIT
                        </div>

                        <div>
                            SYSTEM
                        </div>

                        <div>
                            INFO
                        </div>

                    <div>
                        CONNECTING
                    </div>

                    </div>

                )}

                {/* =============================================
                   ERROR
                ============================================= */}

                {error && (

                    <div className="log-stream-line">

                        <div>
                            ERROR
                        </div>

                        <div>
                            SYSTEM
                        </div>

                        <div
                            className="terminal-red"
                        >
                            ERROR
                        </div>

                        <div>
                            FAILURE
                        </div>

                    </div>

                )}

                {/* =============================================
                   EVENTS
                ============================================= */}

                {runtimeEvents.map(

                    (event, index) => {

                        return (

                            <div
                                key={`${event.timestamp}-${index}`}
                                className="log-stream-line"
                            >

                                <div>

                                    {
                                        formatTime(
                                            event.timestamp
                                        )
                                    }

                                </div>

                                <div>

                                    {
                                        event.source
                                    }

                                </div>

                                <div
                                    className={
                                        categoryClass(
                                            event.level
                                        )
                                    }
                                >

                                    {
                                        event.level
                                    }

                                </div>

                                <div>

                                    {
                                        event.state
                                    }

                                </div>

                            </div>

                        );

                    }

                )}

                {runtimeEvents.length === 0 && !loading && (

                    <div className="log-stream-line">

                        <div>
                            --
                        </div>

                        <div>
                            SYSTEM
                        </div>

                        <div>
                            INFO
                        </div>

                        <div>
                            DISCONNECTED
                        </div>

                    </div>

                )}

            </div>

        </div>

    );

}