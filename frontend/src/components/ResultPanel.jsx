import React from "react";

/* =========================================================
   CENTER TERMINAL PNL MONITOR
========================================================= */

export default function ResultPanel({

    balance = 0,

    equity = 0,

    pnl = 0,

    dayPnl = null,

    drawdown = null,

    slippage = null,

    margin = null,

    position = "NONE",

    marketRegime = "NEUTRAL",

    routingQuality = "UNKNOWN",

    marketHostility = 0,

}) {

    const roi =
        equity > 0
            ? (
                (
                    pnl /
                    equity
                ) * 100
            ).toFixed(2)
            : "0.00";

    return (

        <div className="terminal-monitor-section">

            {/* =============================================
               SECTION HEADER
            ============================================= */}

            <div className="terminal-section-header">
                1 | PNL
            </div>

            {/* =============================================
               TELEMETRY GRID
            ============================================= */}

            <div className="result-telemetry-grid">

                {/* =============================================
                   BALANCE
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        BAL / 残高
                    </div>

                    <div className="telemetry-value terminal-green">

                        {
                            Number(
                                balance || 0
                            ).toLocaleString(
                                undefined,
                                {
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                }
                            )
                        }

                    </div>

                </div>

                {/* =============================================
                   EQUITY
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        EQ / 有効資産
                    </div>

                    <div className="telemetry-value terminal-green">

                        {
                            Number(
                                equity || 0
                            ).toLocaleString(
                                undefined,
                                {
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                }
                            )
                        }

                    </div>

                </div>

                {/* =============================================
                   PNL
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        PNL / 損益
                    </div>

                    <div
                        className={
                            pnl >= 0
                                ? "telemetry-value terminal-green"
                                : "telemetry-value terminal-red"
                        }
                    >

                        {
                            pnl >= 0
                                ? "+"
                                : ""
                        }

                        {
                            Number(
                                pnl || 0
                            ).toFixed(2)
                        }

                    </div>

                </div>

                {/* =============================================
                   DAY
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        DAY / 日次
                    </div>

                    <div className="telemetry-value">

                        {
                            dayPnl !== null &&
                            dayPnl !== undefined
                                ? Number(dayPnl).toFixed(2)
                                : "NO DATA"
                        }

                    </div>

                </div>

                {/* =============================================
                   ROI
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        ROI / 利益率
                    </div>

                    <div
                        className={
                            Number(roi) >= 0
                                ? "telemetry-value terminal-green"
                                : "telemetry-value terminal-red"
                        }
                    >

                        {
                            Number(roi) >= 0
                                ? "+"
                                : ""
                        }

                        {roi}%

                    </div>

                </div>

                {/* =============================================
                   DRAWDOWN
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        DD / 最大損失
                    </div>

                    <div className="telemetry-value">

                        {
                            drawdown !== null &&
                            drawdown !== undefined
                                ? `${Number(drawdown).toFixed(2)}%`
                                : "NO DATA"
                        }

                    </div>

                </div>

                {/* =============================================
                   POSITION
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        POS
                    </div>

                    <div className="telemetry-value">

                        {position}

                    </div>

                </div>

                {/* =============================================
                   MARGIN
                ============================================= */}

                <div className="telemetry-cell">

                    <div className="telemetry-label">
                        MGN / 使用証拠金
                    </div>

                    <div className="telemetry-value">

                        {
                            margin !== null &&
                            margin !== undefined
                                ? Number(margin).toFixed(2)
                                : "NO DATA"
                        }

                    </div>

                </div>

            </div>

            {/* =============================================
               ROUTING / QUALITY
            ============================================= */}

            <div className="terminal-monitor-section">

                <div className="terminal-section-header">
                    3 | ROUTING
                </div>

                <div className="result-telemetry-grid">

                    <div className="telemetry-cell">

                        <div className="telemetry-label">
                            ROUTE / 経路品質
                        </div>

                        <div className="telemetry-value terminal-yellow">

                            {routingQuality}

                        </div>

                    </div>

                    <div className="telemetry-cell">

                        <div className="telemetry-label">
                            LAT / 遅延
                        </div>

                        <div className="telemetry-value terminal-yellow">
                            UNK
                        </div>

                    </div>

                    <div className="telemetry-cell">

                        <div className="telemetry-label">
                            SLIP / 滑り
                        </div>

                        <div className="telemetry-value">

                            {
                                slippage !== null &&
                                slippage !== undefined
                                    ? `${Number(slippage).toFixed(2)}%`
                                    : "NO DATA"
                            }

                        </div>

                    </div>

                    <div className="telemetry-cell">

                        <div className="telemetry-label">
                            MICRO / 微細構造
                        </div>

                        <div className="telemetry-value">

                            {marketRegime}

                        </div>

                    </div>

                    <div className="telemetry-cell">

                        <div className="telemetry-label">
                            HOSTILE / 市場敵対度
                        </div>

                        <div className="telemetry-value terminal-green">

                            {marketHostility}

                        </div>

                    </div>

                </div>

            </div>

        </div>

    );

}