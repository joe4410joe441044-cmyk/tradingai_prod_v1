// frontend/src/components/ExecutionPanel.jsx

import React from "react";

export default function ExecutionPanel({


    balance = "--",

    equity = "--",

    leverage = "--",

    positionSide = "NONE",

    runtimePhase = "--",

    routerRoute = "--",

    routerBelief = "--",

    routingQuality = "UNKNOWN",

    cognitionStability = "--",

    marketRegime = "UNDEFINED",

    marketHostility = "--",

    survivability = "--",

    riskProfile = "UNKNOWN",

    restrictionReason = "NONE",

    websocketHealth = "--",

    reconnectInProgress = false,

    streamStale = false,

    latency = "--",

    executionAllowed = false,

    suppressionReason = "NONE",

    governanceReason = "NONE",

    runtimeRejectionReason = "NONE",

    packetIntegrity = "--",

    spreadCondition = "UNKNOWN",

    volatility = "--",

    liquidity = "--",

    microstructureBias = "--",

    latencyProfile = "--",

    cooldown = "--",

    maxSlippage = "--",


}) {

    return (

        <div className="terminal-monitor-section">

            {/* =============================================
               SECTION HEADER
            ============================================= */}

            <div className="terminal-section-header">
                2 | EXECUTION
            </div>

            {/* =============================================
               TERMINAL GRID
            ============================================= */}

            <div className="execution-terminal-grid">

                {/* =============================================
                   BOT
                ============================================= */}

                <div className="terminal-block">

                    <div className="terminal-block-title">
                        BOT
                    </div>

                    <div className="terminal-row">

                        <span>
                            STATUS
                        </span>

                        <span
                            className={
                                executionAllowed
                                    ? "terminal-green"
                                    : "terminal-red"
                            }
                        >

                            {executionAllowed
                                ? "ON"
                                : "OFF"}

                        </span>


                        <span

                        >

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            PHASE
                        </span>

                        <span>
                            {runtimePhase}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            ROUTE
                        </span>

                        <span>
                            {routerRoute}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            BELIEF
                        </span>

                        <span>
                            {routerBelief}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            QUALITY
                        </span>

                        <span>
                            {routingQuality}
                        </span>

                    </div>

                </div>
                {/* =============================================
                   EXEC
                ============================================= */}

                <div className="terminal-block">

                    <div className="terminal-block-title">
                        EXEC
                    </div>

                    <div className="terminal-row">

                        <span>
                            RISK
                        </span>

                        <span
                            className={
                                survivability < 0.4
                                    ? "terminal-red"

                                    : survivability < 0.7
                                    ? "terminal-yellow"

                                    : "terminal-green"
                            }
                        >

                            {riskProfile}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            RESTRICT
                        </span>

                        <span
                            className={
                                restrictionReason !== "NONE"
                                    ? "terminal-red"
                                    : "terminal-green"
                            }
                        >

                            {restrictionReason}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            REJECT
                        </span>

                        <span
                            className={
                                runtimeRejectionReason !== "NONE"
                                    ? "terminal-yellow"
                                    : "terminal-green"
                            }
                        >

                            {runtimeRejectionReason}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            SUPPRESS
                        </span>

                        <span
                            className={
                                suppressionReason !== "NONE"
                                    ? "terminal-yellow"
                                    : "terminal-green"
                            }
                        >

                            {suppressionReason}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            GOV
                        </span>

                        <span>
                            {governanceReason}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            SPRD
                        </span>

                        <span
                            className={
                                spreadCondition === "WIDE"
                                    ? "terminal-yellow"
                                    : "terminal-green"
                            }
                        >

                            {spreadCondition}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            SLIP
                        </span>

                        <span>
                            {maxSlippage}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            LAT
                        </span>

                        <span>
                            {latency}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            PROFILE
                        </span>

                        <span>
                            {latencyProfile}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            COOLDOWN
                        </span>

                        <span>
                            {cooldown}s
                        </span>

                    </div>

                </div>
                 {/* =============================================
                   MARKET
                ============================================= */}

                <div className="terminal-block">

                    <div className="terminal-block-title">
                        MARKET
                    </div>

                    <div className="terminal-row">

                        <span>
                            REGIME
                        </span>

                        <span>
                            {marketRegime}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            MICRO
                        </span>

                        <span>
                            {microstructureBias}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            HOSTILE
                        </span>

                        <span
                            className={
                                marketHostility > 0.7
                                    ? "terminal-red"

                                    : marketHostility > 0.4
                                    ? "terminal-yellow"

                                    : "terminal-green"
                            }
                        >

                            {marketHostility}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            VOL
                        </span>

                        <span>
                            {volatility}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            LIQ
                        </span>

                        <span>
                            {liquidity}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            WS
                        </span>

                        <span
                            className={
                                websocketHealth < 40
                                    ? "terminal-red"

                                    : websocketHealth < 70
                                    ? "terminal-yellow"

                                    : "terminal-green"
                            }
                        >

                            {websocketHealth}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            STREAM
                        </span>

                        <span
                            className={
                                streamStale
                                    ? "terminal-yellow"
                                    : "terminal-green"
                            }
                        >

                            {streamStale
                                ? "STALE"
                                : "CURRENT"}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            RECONNECT
                        </span>

                        <span
                            className={
                                reconnectInProgress
                                    ? "terminal-yellow"
                                    : "terminal-green"
                            }
                        >

                            {reconnectInProgress
                                ? "ON"
                                : "IDLE"}

                        </span>

                    </div>
                                        <div className="terminal-row">

                        <span>
                            STABILITY
                        </span>

                        <span
                            className={
                                cognitionStability < 0.4
                                    ? "terminal-red"

                                    : cognitionStability < 0.7
                                    ? "terminal-yellow"

                                    : "terminal-green"
                            }
                        >

                            {cognitionStability}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            PACKET
                        </span>

                        <span
                            className={
                                packetIntegrity < 0.7
                                    ? "terminal-yellow"
                                    : "terminal-green"
                            }
                        >

                            {packetIntegrity}

                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            BAL
                        </span>

                        <span>
                            {balance}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            EQ
                        </span>

                        <span>
                            {equity}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            POS
                        </span>

                        <span>
                            {positionSide}
                        </span>

                    </div>

                    <div className="terminal-row">

                        <span>
                            LEV
                        </span>

                        <span>
                            {leverage}x
                        </span>

                    </div>

                </div>

            </div>

        </div>

    );

}
