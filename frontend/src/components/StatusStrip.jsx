import React from "react";
export default function StatusStrip({ runtimeHealth }) {

    const botStatus = runtimeHealth.running ? "RUNNING" : "STOPPED";
    const wsStatus = runtimeHealth.browserWebSocket.status;
    const engineStatus = runtimeHealth.runtimeEngine.status;
    const executionState = runtimeHealth.executionEngine.status;
    const pipelineStatus = runtimeHealth.pipelineStatus;
    const loopCount = runtimeHealth.loopCount;
    const session = runtimeHealth.session;
    const version = runtimeHealth.version;
    const latency = runtimeHealth.latencyMs == null
        ? "--"
        : `${Number(runtimeHealth.latencyMs).toFixed(2)} ms`;


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
            {/* ENGINE */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    RUNTIME ENGINE
                </span>

                <span
                    className={
                        `status-value ${
                            engineStatus === "ACTIVE"
                                ? "online"
                                : "warning"
                        }`
                    }
                >

                    {
                        engineStatus
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
            {/* EXECUTION */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    EXEC / 実行
                </span>

                <span
                    className={
                        `status-value ${
                            ["READY", "EXECUTED", "ENABLED_IDLE_BY_AI_HOLD"].includes(
                                executionState,
                            )
                                ? "online"
                                : "warning"
                        }`
                    }
                >

                    {
                        executionState
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* PIPELINE */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    PIPELINE
                </span>

                <span className={
                    `status-value ${
                        pipelineStatus === "OK"
                            ? "online"
                            : "warning"
                    }`
                }>
                    {pipelineStatus}
                </span>

            </div>

            {/* ============================================= */}
            {/* STAGES */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    STAGES
                </span>

                <span className={
                    `status-value ${loopCount > 0 ? "online" : "warning"}`
                }>
                    {loopCount}
                </span>

            </div>

            {/* ============================================= */}
            {/* SESSION */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    SESSION
                </span>

                <span className="status-value online">
                    {session}
                </span>

            </div>

            {/* ============================================= */}
            {/* VERSION */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    VERSION
                </span>

                <span className="status-value">
                    {version}
                </span>

            </div>

        </div>

    );

}
