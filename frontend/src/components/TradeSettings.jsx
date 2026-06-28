// frontend/src/components/TradeSettings.jsx

import React from "react";

export default function TradeSettings({

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

                    TRADE SETTINGS（取引設定）

                </div>

            </div>

            {/* =============================================
               MODE
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    MODE（モード）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.mode
                            || "PAPER"
                        }
                        onChange={(e) =>
                            handle(
                                "mode",
                                e.target.value
                            )
                        }
                    >

                        <option value="PAPER">
                            PAPER（模擬）
                        </option>

                        <option value="SAFE">
                            SAFE（安全）
                        </option>

                        <option value="LIVE">
                            LIVE（本番）
                        </option>

                    </select>

                </div>

            </div>

            {/* =============================================
               EXCHANGE
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    EXCHANGE（取引所）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.exchange
                            || "BINANCE"
                        }
                        onChange={(e) =>
                            handle(
                                "exchange",
                                e.target.value
                            )
                        }
                    >

                        <option value="BINANCE">
                            BINANCE
                        </option>

                        <option value="BYBIT">
                            BYBIT
                        </option>

                        <option value="KUCOIN">
                            KUCOIN
                        </option>

                    </select>

                </div>

            </div>

            {/* =============================================
               SYMBOL
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    SYMBOL（銘柄）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.symbol
                            || "XRPUSDT"
                        }
                        onChange={(e) =>
                            handle(
                                "symbol",
                                e.target.value
                            )
                        }
                    >

                        <option value="XRPUSDT">
                            XRPUSDT
                        </option>

                        <option value="BTCUSDT">
                            BTCUSDT
                        </option>

                        <option value="ETHUSDT">
                            ETHUSDT
                        </option>

                    </select>

                </div>

            </div>

            {/* =============================================
               LEVERAGE
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    LEVERAGE（レバレッジ）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.leverage || 5
                        }
                        onChange={(e) =>
                            handle(
                                "leverage",
                                Number(
                                    e.target.value
                                )
                            )
                        }
                    >

                        <option value={1}>
                            1x
                        </option>

                        <option value={2}>
                            2x
                        </option>

                        <option value={3}>
                            3x
                        </option>

                        <option value={5}>
                            5x
                        </option>

                        <option value={10}>
                            10x
                        </option>

                    </select>

                </div>

            </div>

            {/* =============================================
               TIMEFRAME
            ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    TIMEFRAME（時間軸）

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.timeframe
                            || "1m"
                        }
                        onChange={(e) =>
                            handle(
                                "timeframe",
                                e.target.value
                            )
                        }
                    >

                        <option value="1m">
                            1m
                        </option>

                        <option value="5m">
                            5m
                        </option>

                        <option value="15m">
                            15m
                        </option>

                        <option value="1h">
                            1h
                        </option>

                    </select>

                </div>

            </div>

        </div>

    );

}