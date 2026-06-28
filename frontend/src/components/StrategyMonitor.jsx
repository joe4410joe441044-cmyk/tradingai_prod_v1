export default function StrategyMonitor({

    strategyData = {},

}) {

    const safeFixed = (
        value,
        digits = 2
    ) => {

        return (
            value !== null &&
            value !== undefined &&
            Number.isFinite(
                Number(value)
            )
        )

            ? Number(value).toFixed(
                  digits
              )

            : "-";

    };
        const {

        executionAllowed = false,

        executionState = "--",

        executionProfile = "--",

        runtimeStatus = "--",

        governanceRisk = "--",

        governanceHealth = "--",

        route = "--",

        routeReason = "--",

        marketCondition = "--",

        spread = null,

        tightSpread = false,

        acceptableSpread = false,

        spreadExpansion = false,

        latency = null,

        latencyHealthy = false,

        executionPressure = "--",

        executionSafety = "--",

        marketMakingWindow = false,

        emergencyExit = false,

        price = null,

        } = strategyData;

        return (


        <>

            <div className="panel-title">

                EXECUTION GOVERNANCE

            </div>

            <div className="telemetry-grid">

                <div className="telemetry-item">

                    RUNTIME :

                    <span className="info">

                        GOVERNANCE

                    </span>

                </div>

                <div className="telemetry-item">

                    EXECUTION :

                    <span
                        className={
                            executionAllowed
                                ? "online"
                                : "danger"
                        }
                    >

                        {
                            executionAllowed
                                ? "AUTHORIZED"
                                : "BLOCKED"
                        }

                    </span>

                </div>

            </div>

            <div className="monitor-section">

                <div className="section-title">
                    EXECUTION STATUS
                </div>

                <div className="execution-grid">

                    <div className="monitor-item">

                        <span>
                            STATE
                        </span>

                        <strong>

                            {executionState}

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            PROFILE
                        </span>

                        <strong>

                            {executionProfile}

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            ROUTE
                        </span>

                        <strong>

                            {route}

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            REASON
                        </span>

                        <strong>

                            {routeReason}

                        </strong>

                    </div>

                </div>

            </div>
            <div className="monitor-section">

                <div className="section-title">
                    GOVERNANCE HEALTH
                </div>

            <div className="brain-grid">

                <div className="monitor-item">

                    <span>
                        STATUS
                    </span>

                    <strong className="neutral">

                        {runtimeStatus || "--"}

                    </strong>

                </div>

                    <div className="monitor-item">

                        <span>
                            HEALTH
                        </span>

                        <strong>

                            {
                                governanceHealth
                            }

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            RISK
                        </span>

                        <strong className="neutral">

                            {governanceRisk}

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            SAFETY
                        </span>

                        <strong>

                            {
                                executionSafety
                            }

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            PRESSURE
                        </span>

                        <strong>

                            {
                                executionPressure
                            }

                        </strong>

                    </div>

                </div>

            </div>
            <div className="monitor-section">

                <div className="section-title">
                    MARKET CONDITIONS
                </div>

            <div className="safety-grid">

                <div className="monitor-item">

                    <span>
                        CONDITION
                    </span>

                    <strong>

                        {
                            marketCondition
                        }

                    </strong>

                </div>

                <div className="monitor-item">

                    <span>
                        MM WINDOW
                    </span>

                    <strong className="neutral">

                        {
                            typeof marketMakingWindow === "boolean"
                                ? (marketMakingWindow ? "YES" : "NO")
                                : "--"
                        }

                    </strong>

                </div>

            </div>

            </div>
            <div className="monitor-section">

                <div className="section-title">
                    EXECUTION TELEMETRY
                </div>

                <div className="environment-grid">

                    <div className="monitor-item">

                        <span>
                            LATENCY
                        </span>

                        <strong>

                            {safeFixed(
                                latency,
                                0
                            )}

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            SPREAD
                        </span>

                        <strong>

                            {safeFixed(
                                spread,
                                4
                            )}

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            TIGHT
                        </span>

                        <strong>

                            {
                                tightSpread
                                    ? "YES"
                                    : "NO"
                            }

                        </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            ACCEPTABLE
                        </span>

                        <strong>

                            {
                                acceptableSpread
                                    ? "YES"
                                    : "NO"
                            }

                        </strong>

                    </div>

                    <div className="monitor-item">

                    <span>
                        EXPANSION
                    </span>

                    <strong className="neutral">

                        {

                            typeof spreadExpansion === "boolean"
                                ? (spreadExpansion ? "YES" : "NO")
                                : "--"

                        }

                    </strong>

                    </div>

                    <div className="monitor-item">

                    <span>
                        LATENCY HEALTH
                    </span>

                    <strong className="neutral">

                        {

                            typeof latencyHealthy === "boolean"
                                ? (latencyHealthy ? "YES" : "NO")
                                : "--"

                        }

                    </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            FAILSAFE
                        </span>

                    <strong className="neutral">

                        {

                            typeof emergencyExit === "boolean"
                                ? (emergencyExit ? "ON" : "OFF")
                                : "--"

                        }

                    </strong>

                    </div>

                    <div className="monitor-item">

                        <span>
                            PRICE
                        </span>

                        <strong>

                            {safeFixed(
                                price,
                                4
                            )}

                        </strong>

                    </div>

                </div>

            </div>

        </>

    );

}
