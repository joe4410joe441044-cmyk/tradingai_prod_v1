import React from "react";
import { formatLatency } from "../runtime/runtimeDisplay";
export default function StatusStrip({ runtimeHealth }) {

    const botStatus = runtimeHealth.running ? "RUNNING" : "STOPPED";
    const wsStatus = runtimeHealth.browserWebSocket.status;
    // The backend runtimeEngine field describes the strategy loop,
    // independently of the attached ExecutionEngine and bot lifecycle.
    const strategyLoopStatus = runtimeHealth.runtimeEngine.status;
    const latency = formatLatency(runtimeHealth.latencyMs);
    const mode = runtimeHealth.mode;


    /* =====================================================
       UI
    ===================================================== */

    return (

        <div className="status-strip">

            {/* ============================================= */}
            {/* BOT */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    BOT / ボット
                </span>

                <span
                    className={
                        `status-value ${
                            botStatus === "RUNNING"
                                ? "online"
                                : "warning"
                        }`
                    }
                >

                    {
                        botStatus
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* WS */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    BROWSER WS / 画面接続
                </span>

                <span
                    className={
                        `status-value ${
                            wsStatus === "LIVE"
                                ? "online"
                                : "danger"
                        }`
                    }
                >

                    {
                        wsStatus
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* STRATEGY LOOP */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    STRATEGY LOOP
                </span>

                <span
                    className={
                        `status-value ${
                            strategyLoopStatus === "ACTIVE"
                                ? "online"
                                : "warning"
                        }`
                    }
                >

                    {
                        strategyLoopStatus
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* LATENCY */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    LATENCY / 遅延
                </span>

                <span className="status-value online">

                    {latency}

                </span>

            </div>

            {/* ============================================= */}
            {/* MODE */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    MODE
                </span>

                <span className={
                    `status-value ${
                        mode === "LIVE"
                            ? "live"
                            : "paper"
                    }`
                }>

                    {
                        mode
                    }

                </span>

            </div>

        </div>

    );

}
