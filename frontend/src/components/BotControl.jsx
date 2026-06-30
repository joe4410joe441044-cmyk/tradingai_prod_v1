import React, {
    useState,
} from "react";

import {
    updateExecutionRuntimeTelemetry,
} from "../store/telemetryStore";

import {
    setExecutionEnabled,
} from "../runtime/governanceRuntime";
import {
    API,
} from "../api";

export default function BotControl({

    config,

    executionEnabled,

    setExecutionEnabledState,

}){

    const [, forceUpdate] =
        useState(0);

    /* =======================================================
       STATUS
    ======================================================= */

    const executionStatus =
        executionEnabled
            ? "RUNNING（稼働中）"
            : "STOPPED（停止中）";

    /* =======================================================
       UI
    ======================================================= */

    return (

        <div className="terminal-panel">

            {/* =======================================================
               SECTION TITLE
            ======================================================= */}

            <div className="section-number-title">

                1. MAIN OPERATION（メイン操作）

            </div>

            {/* =======================================================
            START / STOP
            ======================================================= */}

            <div className="main-operation-buttons">

                <button
                    className="start-button-large"
                    onClick={async () => {

                        console.log(
                            "START BUTTON CLICKED"
                        );

                        console.log(
                            "START CONFIG",
                            config
                        );

                        try {

                            console.log(
                                "POST BODY",
                                config
                            );

                            const response =
                                await fetch(
                                    API.botStart(),
                                    {

                                        method: "POST",

                                        headers: {
                                            "Content-Type":
                                                "application/json",
                                        },

                                        body: JSON.stringify({

                                            ...config,

                                            mode:
                                                String(config.mode)
                                                    .toLowerCase(),

                                            risk_percent:
                                                config.risk_percent ?? 1,

                                            sl_percent:
                                                config.sl_percent ?? config.sl ?? 1,

                                            tp_percent:
                                                config.tp_percent ?? config.tp ?? 1,

                                        })

                                    }
                                );

                            if (
                                !response.ok
                            ) {

                                const text =
                                    await response.text();

                                console.error(
                                    "BOT START RESPONSE",
                                    text
                                );

                                throw new Error(
                                    text
                                );

                            }

                            const result =
                                await setExecutionEnabled(
                                    true
                                );

                            updateExecutionRuntimeTelemetry({

                                executionAllowed: true,

                                governanceReason:
                                    "MANUAL_START",

                                suppressionReason:
                                    "NONE",

                            });

                            console.log(
                                "START RESULT",
                                result
                            );

                            setExecutionEnabledState(
                                true
                            );

                            forceUpdate(
                                v => v + 1
                            );

                        } catch (error) {

                            console.error(
                                "START ERROR",
                                error
                            );

                        }

                    }}
                >

                    START（開始）

                </button>

                <button
                    className="stop-button-large"
                    onClick={async () => {

                        console.log(
                            "STOP BUTTON CLICKED"
                        );

                        try {

                            const result =
                                await setExecutionEnabled(
                                    false
                                );

                            updateExecutionRuntimeTelemetry({

                                executionAllowed: false,

                                governanceReason:
                                    "MANUAL_STOP",

                                suppressionReason:
                                    "EXECUTION_DISABLED",

                            });

                            console.log(
                                "STOP RESULT",
                                result
                            );

                            setExecutionEnabledState(
                                false
                            );

                        } catch (error) {

                            console.error(
                                "STOP ERROR",
                                error
                            );

                            forceUpdate(
                                v => v + 1
                            );

                        }

                    }}
                >

                    STOP（停止）

                </button>

            </div>

            {/* =======================================================
               EXECUTION STATUS
            ======================================================= */}

            <div className="execution-status-section">

                <div className="execution-status-label">

                    EXECUTION STATUS（実行状態）

                </div>

                <div
                    className={
                        executionEnabled
                            ? "execution-status-box running"
                            : "execution-status-box stopped"
                    }
                >

                    {executionStatus}

                </div>

            </div>

        </div>

    );

}
