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
import {
    requestBotStop,
} from "../runtime/botLifecycle";

export default function BotControl({

    config,

    executionEnabled,

    botRunning,

    setExecutionEnabledState,

}){

    const [, forceUpdate] =
        useState(0);

    /* =======================================================
       STATUS
    ======================================================= */

    const executionAuthorityStatus =
        executionEnabled
            ? "ENABLED（注文許可）"
            : "DISABLED_BY_OPERATOR（注文停止）";

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
                    data-testid="bot-start-button"
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

                                            exchange:
                                                String(config.exchange || "kucoin")
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

                            const result = await response.json();

                            console.log(
                                "START RESULT",
                                result
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
                    data-testid="bot-stop-button"
                    onClick={async () => {

                        console.log(
                            "STOP BUTTON CLICKED"
                        );

                        try {

                            const result = await requestBotStop({
                                endpoint: API.botStop(),
                            });

                            console.log(
                                "STOP RESULT",
                                result
                            );

                            forceUpdate(v => v + 1);

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
               BOT STATUS
            ======================================================= */}

            <div className="execution-status-section">

                <div className="execution-status-label">

                    BOT STATE（ボット状態）

                </div>

                <div
                    className={
                        botRunning
                            ? "execution-status-box running"
                            : "execution-status-box stopped"
                    }
                >

                    {botRunning ? "RUNNING（稼働中）" : "STOPPED（停止中）"}

                </div>

            </div>

            <div className="execution-status-section">

                <div className="execution-status-label">
                    EXECUTION AUTHORITY（注文送信許可）
                </div>

                <div
                    className={
                        executionEnabled
                            ? "execution-status-box running"
                            : "execution-status-box stopped"
                    }
                >
                    {executionAuthorityStatus}
                </div>

                <button
                    className={executionEnabled
                        ? "stop-button-large"
                        : "start-button-large"
                    }
                    onClick={async () => {
                        try {
                            const enabled = !executionEnabled;
                            const result = await setExecutionEnabled(enabled);

                            updateExecutionRuntimeTelemetry({
                                executionAllowed: enabled,
                                governanceReason: enabled
                                    ? "MANUAL_EXECUTION_ENABLE"
                                    : "MANUAL_EXECUTION_DISABLE",
                                suppressionReason: enabled
                                    ? "NONE"
                                    : "EXECUTION_DISABLED",
                            });

                            console.log("EXECUTION AUTHORITY RESULT", result);
                            setExecutionEnabledState(enabled);
                        } catch (error) {
                            console.error("EXECUTION AUTHORITY ERROR", error);
                        }
                    }}
                    type="button"
                >
                    {executionEnabled
                        ? "DISABLE ORDERS（注文停止）"
                        : "ENABLE ORDERS（注文許可）"
                    }
                </button>

            </div>

        </div>

    );

}
