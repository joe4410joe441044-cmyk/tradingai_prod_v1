// frontend/src/components/SafetySettings.jsx

import React from "react";

export default function SafetySettings({

    values = {},

    onChange = () => {},

}) {

    const handle = (
        key,
        value
    ) => {

        onChange({
            [key]: value,
        });

    };

    return (

        <div className="terminal-panel">

            {/* =============================================
               HEADER
            ============================================= */}

            <div className="panel-header">

                <div className="panel-title">

                    SAFETY SETTINGS（安全設定）

                </div>

            </div>

            {/* =============================================
               KILL SWITCH
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    KILL SWITCH（緊急停止）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.killSwitch
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "killSwitch",
                                e.target.value === "ON"
                            )
                        }
                    >

                        <option value="OFF">
                            OFF（無効）
                        </option>

                        <option value="ON">
                            ON（有効）
                        </option>

                    </select>

                </div>

            </div>

            {/* =============================================
               AUTO FLATTEN
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    AUTO FLATTEN（自動全決済）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.autoFlatten
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "autoFlatten",
                                e.target.value === "ON"
                            )
                        }
                    >

                        <option value="ON">
                            ON（有効）
                        </option>

                        <option value="OFF">
                            OFF（無効）
                        </option>

                    </select>

                </div>

            </div>

            {/* =============================================
               EMERGENCY STOP
            ============================================= */}

            <div className="config-row emergency-stop-row">

                <button className="emergency-stop-button">

                    EMERGENCY STOP（緊急停止）

                </button>

            </div>

        </div>

    );

}