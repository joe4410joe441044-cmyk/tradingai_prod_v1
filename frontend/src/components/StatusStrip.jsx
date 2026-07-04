import React from "react";
export default function StatusStrip({

    botRunning = false,

    wsConnected = false,

    engineStatus = "BLOCKED",

    latency = "--",

    executionState = "DISABLED",

    pipelineStatus = "WAIT",

    loopCount = 0,

    session = "LOCAL",

    version = "V2",
}) {


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
                            botRunning
                                ? "online"
                                : "danger"
                        }`
                    }
                >

                    {
                        botRunning
                            ? "稼働中"
                            : "停止中"
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* WS */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    WS / 接続
                </span>

                <span
                    className={
                        `status-value ${
                            wsConnected
                                ? "online"
                                : "danger"
                        }`
                    }
                >

                    {
                        wsConnected
                            ? "接続中"
                            : "切断"
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* ENGINE */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    ENGINE / エンジン
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
                        engineStatus === "ACTIVE"
                            ? "稼働"
                            : engineStatus
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
                            executionState === "ENABLED"
                                ? "online"
                                : "warning"
                        }`
                    }
                >

                    {
                        executionState === "ENABLED"
                            ? "有効"
                            : executionState === "BLOCKED"
                                ? "ブロック"
                                : "無効"
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
                        pipelineStatus === "WAIT"
                            ? "warning"
                            : "online"
                    }`
                }>
                    {pipelineStatus}
                </span>

            </div>

            {/* ============================================= */}
            {/* LOOPS */}
            {/* ============================================= */}

            <div className="status-item">

                <span className="status-label">
                    LOOPS
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
