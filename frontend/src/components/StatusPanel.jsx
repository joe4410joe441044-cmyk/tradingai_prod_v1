import {
    telemetryState,
} from "../store/telemetryStore";

/* =================================================
   STATUS PANEL
================================================= */

const StatusPanel = () => {

    /* =================================================
       TELEMETRY STORE
    ================================================= */

    const governance =
        telemetryState.governance || {};

    const runtime =
        telemetryState.runtime || {};

    const router =
        telemetryState.router || {};

    const cognition =
        telemetryState.cognition || {};

    const market =
        telemetryState.market || {};

    const microstructure =
        telemetryState.microstructure || {};

    const risk =
        telemetryState.risk || {};

    /* =================================================
       RUNTIME SNAPSHOT
    ================================================= */

    const mode =
        governance.mode || "PAPER";

    const runtimePhase =
        runtime.runtimePhase
        || "UNKNOWN";

    const wsConnected =
        runtime.websocketConnected === true;

    const apiConnected =
        runtime.apiConnected === true;

    const websocketHealth =
        runtime.websocketHealth ?? "--";

    const latency =
        runtime.latency ?? "-";

    const uptime =
        runtime.uptime ?? "-";

    const routerStatus =
        router.status || "UNKNOWN";

    const routerRoute =
        router.route || "UNKNOWN";

    const routerBelief =
        cognition.routerBelief
        || "NO DATA";

    const marketBelief =
        cognition.marketBelief
        || "NO DATA";

    const cognitionStability =
        cognition.cognitionStability
        ?? "--";

    const marketRegime =
        market.marketRegime
        || "NO DATA";

    const marketHostility =
        market.marketHostility
        ?? "--";

    const survivability =
        risk.survivability
        ?? "--";

    const restrictionReason =
        risk.restrictionReason
        || "NO DATA";

    const tickMomentum =
        microstructure.tickMomentum
        || "NO DATA";

    const orderFlowBias =
        microstructure.orderFlowBias
        || "NO DATA";

    /* =================================================
       PANEL
    ================================================= */

    return (
    <>

            <div className="compact-row">

                <span>
                    MODE
                </span>

                <span
                    className={
                        mode === "LIVE"
                            ? "danger"
                            : "neutral"
                    }
                >

                    {mode}

                </span>

            </div>

            <div className="compact-row">

                <span>
                    RUNTIME
                </span>

                <span
                className="neutral"
                >

                    {
                        runtimePhase
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    ROUTER
                </span>

                <span
                className="neutral"
                >

                    {
                        routerStatus
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    ROUTE
                </span>

                <span className="warning">

                    {
                        routerRoute
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    ROUTER BELIEF
                </span>

                <span>

                    {
                        routerBelief
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    MARKET BELIEF
                </span>

                <span>

                    {
                        marketBelief
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    MARKET REGIME
                </span>

                <span>

                    {
                        marketRegime
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    HOSTILITY
                </span>

                <span className={
                    typeof marketHostility === "number"
                    && marketHostility > 0.7
                        ? "danger"
                        : typeof marketHostility === "number"
                        && marketHostility > 0.4
                            ? "warning"
                            : "neutral"
                }>

                    {
                        marketHostility
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    SURVIVABILITY
                </span>

                <span className={
                    typeof survivability === "number"
                    && survivability < 0.4
                        ? "danger"
                        : typeof survivability === "number"
                        && survivability < 0.7
                            ? "warning"
                            : "neutral"
                }>

                    {
                        survivability
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    STABILITY
                </span>

                <span className={
                    typeof cognitionStability === "number"
                    && cognitionStability < 0.4
                        ? "danger"
                        : typeof cognitionStability === "number"
                        && cognitionStability < 0.7
                            ? "warning"
                            : "neutral"
                }>

                    {
                        cognitionStability
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    MOMENTUM
                </span>

                <span>

                    {
                        tickMomentum
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    ORDER FLOW
                </span>

                <span>

                    {
                        orderFlowBias
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    WS
                </span>

            <span
                className={

                    typeof wsConnected === "boolean"
                        ? wsConnected
                            ? "online"
                            : "warning"
                        : "neutral"

                }
            >

                {

                    typeof wsConnected === "boolean"
                        ? wsConnected
                            ? "CONNECTED"
                            : "DISCONNECTED"
                        : "--"

                }

            </span>

            </div>

            <div className="compact-row">

                <span>
                    API
                </span>

                <span
                    className={

                        typeof apiConnected === "boolean"
                            ? apiConnected
                                ? "online"
                                : "warning"
                            : "neutral"

                    }
                >

                    {

                        typeof apiConnected === "boolean"
                            ? apiConnected
                                ? "CONNECTED"
                                : "DISCONNECTED"
                            : "--"

                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    WS HEALTH
                </span>

                <span className={

                    typeof websocketHealth === "number"
                        ? websocketHealth < 40
                            ? "danger"
                            : websocketHealth < 70
                                ? "warning"
                                : "neutral"
                        : "neutral"

                }>

                    {

                        typeof websocketHealth === "number"
                            ? websocketHealth
                            : "--"

                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    LATENCY
                </span>

                <span className={

                    typeof latency === "number"
                        ? latency > 120
                            ? "danger"
                            : latency > 50
                                ? "warning"
                                : "neutral"
                        : "neutral"

                }>

                    {

                        typeof latency === "number"
                            ? latency
                            : "--"

                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    UPTIME
                </span>

                <span>

                    {
                        uptime
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    RESTRICTION
                </span>

                <span
                    className={
                        typeof restrictionReason === "string"
                            ? restrictionReason !== "NO DATA"
                                ? "danger"
                                : "neutral"
                            : "neutral"
                    }
                >
                    {
                        typeof restrictionReason === "string"
                            ? restrictionReason
                            : "--"
                    }
                </span>

            </div>

        </>

    );

};

export default StatusPanel;