export const telemetryState = {

    /* =============================================
       GOVERNANCE RUNTIME
    ============================================= */

    governance: {

        mode: "PAPER",

        authority: "BACKEND",

        emergencyHalt: false,

        runtimeControl: "BACKEND_ONLY",

    },

    /* =============================================
       RUNTIME TELEMETRY
    ============================================= */

    runtime: {

        websocketConnected: false,

        apiConnected: false,

        websocketHealth: "--",

        latency: null,

        uptime: 0,

        wsStatus: "DISCONNECTED",

        streamDisconnected: true,

        streamStale: true,

        reconnectTriggered: false,

        reconnectInProgress: false,

        reconnectCount: 0,

        reconnectFailures: 0,

        reconnectLatency: 0,

        reconnectRecovered: false,

        runtimePhase: "--",

    },

    /* =============================================
       EXECUTION RUNTIME TELEMETRY
    ============================================= */

    executionRuntime: {

        executionAllowed: false,

        suppressionReason: "BOOTING",

        direction: "NONE",

        edge: 0,

        confidence: 0,

        risk: 0,

        runtimeHealthy: false,

        cooldownActive: false,

        emergencyHalt: false,

        pacingBlocked: false,

        exposureBlocked: false,

        governanceReason: "NONE",

        suppressionLayer: "NONE",

        runtimeRejectionReason: "NONE",

        websocketHealthy: false,

        cognitionRuntimeActive: false,

        packetIntegrity: "--",

        runtimeDegraded: true,

        survivability: "--",

    },

    /* =============================================
       MARKET TELEMETRY
    ============================================= */

    market: {

        price: 0,

        spread: 0,

        liquidity: "--",

        volatility: "--",

        spoofRisk: "--",

        marketRegime: "UNDEFINED",

        marketHostility: "--",

        position: "NONE",

        balance: 0,

        equity: 0,

        unrealizedPnL: 0,

    },

    /* =============================================
       MICROSTRUCTURE TELEMETRY
    ============================================= */

    microstructure: {

        imbalance: 0,

        spreadQuality: "UNKNOWN",

        liquidityShift: "UNKNOWN",

        tickMomentum: "--",

        volatilityPressure: 0,

        orderFlowBias: "--",

    },

    /* =============================================
       ROUTER COGNITION
    ============================================= */

    router: {

        status: "UNKNOWN",

        route: "UNKNOWN",

        belief: "--",

        routingQuality: "UNKNOWN",

        restrictionReason: "NONE",

        survivability: "--",

        confidence: 0,

        lastRouteUpdate: null,

    },

    /* =============================================
       COGNITION TELEMETRY
    ============================================= */

    cognition: {

        cognitionStability: "--",

        routerBelief: "--",

        marketBelief: "--",

        executionBelief: "--",

        riskBelief: "UNKNOWN",

    },

    /* =============================================
       RISK TELEMETRY
    ============================================= */

    risk: {

        riskProfile: "UNKNOWN",

        survivability: "--",

        restrictionReason: "NONE",

        cooldown: false,

        noTrade: false,

    },

};

/* =================================================
   GOVERNANCE TELEMETRY UPDATE
================================================= */

export const updateGovernanceTelemetry = (

    payload

) => {

    telemetryState.governance = {

        ...telemetryState.governance,

        ...payload,

    };

};

/* =================================================
   RUNTIME TELEMETRY UPDATE
================================================= */

export const updateRuntimeTelemetry = (

    payload

) => {

    telemetryState.runtime = {

        ...telemetryState.runtime,

        ...payload,

    };

};

/* =================================================
   EXECUTION RUNTIME TELEMETRY UPDATE
================================================= */

export const updateExecutionRuntimeTelemetry = (

    payload

) => {

    telemetryState.executionRuntime = {

        ...telemetryState.executionRuntime,

        ...payload,

    };

};

/* =================================================
   MARKET TELEMETRY UPDATE
================================================= */

export const updateMarketTelemetry = (

    payload

) => {

    telemetryState.market = {

        ...telemetryState.market,

        ...payload,

    };

};

/* =================================================
   MICROSTRUCTURE TELEMETRY UPDATE
================================================= */

export const updateMicrostructureTelemetry = (

    payload

) => {

    telemetryState.microstructure = {

        ...telemetryState.microstructure,

        ...payload,

    };

};

/* =================================================
   ROUTER TELEMETRY UPDATE
================================================= */

export const updateRouterTelemetry = (

    payload

) => {

    telemetryState.router = {

        ...telemetryState.router,

        ...payload,

    };

};

/* =================================================
   COGNITION TELEMETRY UPDATE
================================================= */

export const updateCognitionTelemetry = (

    payload

) => {

    telemetryState.cognition = {

        ...telemetryState.cognition,

        ...payload,

    };

};

/* =================================================
   RISK TELEMETRY UPDATE
================================================= */

export const updateRiskTelemetry = (

    payload

) => {

    telemetryState.risk = {

        ...telemetryState.risk,

        ...payload,

    };

};

/* =================================================
   EMERGENCY HALT
================================================= */

export const activateEmergencyHalt = () => {

    telemetryState.runtime.runtimePhase =
        "HALTED";

    telemetryState.runtime.reconnectInProgress =
        false;

    telemetryState.governance.emergencyHalt =
        true;

    telemetryState.executionRuntime.emergencyHalt =
        true;

    telemetryState.executionRuntime.executionAllowed =
        false;

    telemetryState.executionRuntime.suppressionReason =
        "EMERGENCY_HALT";

    telemetryState.executionRuntime.governanceReason =
        "MANUAL_GOVERNANCE_STOP";

    telemetryState.router.status =
        "RESTRICTED";

    telemetryState.router.route =
        "SURVIVAL";

    telemetryState.router.belief =
        "DEFENSIVE";

    telemetryState.router.restrictionReason =
        "MANUAL_GOVERNANCE_STOP";

    telemetryState.risk.riskProfile =
        "SURVIVAL";

    telemetryState.risk.survivability =
        0;

    telemetryState.cognition.riskBelief =
        "SURVIVAL";

};

/* =================================================
   GOVERNANCE RESET
================================================= */

export const resetGovernanceState = () => {

    telemetryState.runtime.runtimePhase =
        "OBSERVING";

    telemetryState.governance.emergencyHalt =
        false;

    telemetryState.executionRuntime.emergencyHalt =
        false;

    telemetryState.executionRuntime.executionAllowed =
        false;

    telemetryState.executionRuntime.suppressionReason =
        "RESETTING";

    telemetryState.executionRuntime.governanceReason =
        "NONE";

    telemetryState.router.status =
        "OBSERVING";

    telemetryState.router.route =
        "OBSERVE";

    telemetryState.router.belief =
        "NEUTRAL";

    telemetryState.router.restrictionReason =
        "NONE";

    telemetryState.risk.riskProfile =
        "STABLE";

    telemetryState.risk.survivability =
        1;

    telemetryState.cognition.riskBelief =
        "STABLE";

};

/* =================================================
   TELEMETRY STORE EXPORT
================================================= */

export const telemetryStore =
    telemetryState;