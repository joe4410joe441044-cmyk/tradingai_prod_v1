// frontend/src/components/FilterSettings.jsx

import React from "react";

export default function FilterSettings({

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

            <div className="panel-header">

                <div className="panel-title">

                    FILTER SETTINGS（フィルター設定）

                </div>

            </div>

            {/* =============================================
               SPREAD FILTER
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    SPREAD FILTER（スプレッド）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.spreadFilter
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "spreadFilter",
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
               VOLATILITY FILTER
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    VOLATILITY FILTER（ボラティリティ）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.volatilityFilter
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "volatilityFilter",
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
               LIQUIDITY FILTER
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    LIQUIDITY FILTER（流動性）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.liquidityFilter
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "liquidityFilter",
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
               SPOOF FILTER
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    SPOOF FILTER（スプーフ検知）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.spoofFilter
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "spoofFilter",
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
               MOMENTUM FILTER
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    MOMENTUM FILTER（モメンタム）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.momentumFilter
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "momentumFilter",
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

        </div>

    );

}