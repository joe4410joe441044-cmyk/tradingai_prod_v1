export default function executionGateEngine({

    derivedIntel = {},

    executionData = {},

    riskData = {},

    strategyData = {},

}) {

    // =========================
    // INPUT EXTRACTION
    // =========================

    const {

        spreadExplosion = false,

        executionAnomaly = false,

        spoofDanger = false,

        noTradeZone = false,

        unstableMarket = false,

        emergencyExit = false,

        marketDanger = "LOW",

        confidenceScore = 0,

        marketPhase = "RANGING",

        signal = "WAIT",

        direction = "NONE",

        microstructureSignals = [],

    } = derivedIntel;

    const {

        cooldown = false,

        liquidityGrab = false,

        breakoutLong = false,

        breakoutShort = false,

    } = strategyData;

    const {

        latency = 0,

        wsStatus = "CONNECTED",

        engineStatus = "READY",

        orderStatus = "IDLE",

    } = executionData;

    const {

        killSwitch = false,

        riskLevel = "LOW",

        currentDD = 0,

        dailyLoss = 0,

        lossStreak = 0,

    } = riskData;

    // =========================
    // ROUTER COGNITION STATE
    // =========================

    let restrictionReason = "NONE";

    let survivability = 100;

    let routingQuality = "OPTIMAL";

    let routerBelief = "STABLE";

    let executionBelief = "NEUTRAL";

    let marketBelief = "BALANCED";

    let riskBelief = "STABLE";

    // =========================
    // RESTRICTION SYNTHESIS
    // =========================

    if (emergencyExit) {

        survivability -= 80;

        restrictionReason =
            "EMERGENCY_EXIT";

        routerBelief =
            "CRITICAL";

    }

    if (killSwitch) {

        survivability -= 80;

        restrictionReason =
            "KILL_SWITCH";

        riskBelief =
            "LOCKDOWN";

    }

    if (noTradeZone) {

        survivability -= 40;

        restrictionReason =
            "NO_TRADE_ZONE";

    }

    if (spoofDanger) {

        survivability -= 35;

        restrictionReason =
            "SPOOF_DANGER";

        marketBelief =
            "MANIPULATED";

    }

    if (executionAnomaly) {

        survivability -= 40;

        restrictionReason =
            "EXECUTION_ANOMALY";

        executionBelief =
            "UNSTABLE";

    }

    if (spreadExplosion) {

        survivability -= 30;

        restrictionReason =
            "SPREAD_EXPLOSION";

        marketBelief =
            "VOLATILE";

    }

    if (cooldown) {

        survivability -= 15;

        restrictionReason =
            "COOLDOWN_ACTIVE";

    }

    if (unstableMarket) {

        survivability -= 25;

        restrictionReason =
            "UNSTABLE_MARKET";

        marketBelief =
            "CHAOTIC";

    }

    if (latency >= 250) {

        survivability -= 35;

        restrictionReason =
            "LATENCY_SPIKE";

        routingQuality =
            "DEGRADED";

    }

    if (wsStatus !== "CONNECTED") {

        survivability -= 50;

        restrictionReason =
            "WS_DISCONNECTED";

        routingQuality =
            "OFFLINE";

    }

    if (engineStatus !== "READY") {

        survivability -= 40;

        restrictionReason =
            "ENGINE_NOT_READY";

        executionBelief =
            "UNAVAILABLE";

    }

    if (marketDanger === "HIGH") {

        survivability -= 45;

        restrictionReason =
            "HIGH_MARKET_DANGER";

        marketBelief =
            "HOSTILE";

    }

    if (currentDD >= 10) {

        survivability -= 50;

        restrictionReason =
            "MAX_DRAWDOWN_EXCEEDED";

        riskBelief =
            "CRITICAL";

    }

    if (dailyLoss >= 5) {

        survivability -= 45;

        restrictionReason =
            "DAILY_LOSS_LIMIT";

        riskBelief =
            "RESTRICTED";

    }

    if (lossStreak >= 5) {

        survivability -= 40;

        restrictionReason =
            "LOSS_STREAK_LIMIT";

        riskBelief =
            "UNSTABLE";

    }

    // =========================
    // CONFIDENCE SYNTHESIS
    // =========================

    const confidence = Math.max(

        0,

        Math.min(

            100,

            Math.round(

                confidenceScore

            )

        )

    );

    // =========================
    // SURVIVABILITY NORMALIZATION
    // =========================

    survivability = Math.max(

        0,

        Math.min(

            100,

            Math.round(

                survivability

            )

        )

    );

    // =========================
    // MARKET REGIME
    // =========================

    const marketRegime =

        marketDanger === "HIGH"
            ? "HOSTILE"

            : unstableMarket
            ? "UNSTABLE"

            : spreadExplosion
            ? "VOLATILE"

            : marketPhase;

    // =========================
    // ROUTE SYNTHESIS
    // =========================

    const route =

        survivability <= 20
            ? "RESTRICTED"

            : confidence >= 80 &&
              breakoutLong
            ? "MOMENTUM_LONG"

            : confidence >= 80 &&
              breakoutShort
            ? "MOMENTUM_SHORT"

            : liquidityGrab
            ? "LIQUIDITY_RESPONSE"

            : "OBSERVE";

    // =========================
    // ROUTER BELIEF
    // =========================

    if (

        survivability >= 80 &&
        confidence >= 75

    ) {

        routerBelief =
            "HIGH_CONVICTION";

    }

    else if (

        survivability >= 60 &&
        confidence >= 50

    ) {

        routerBelief =
            "STABLE";

    }

    else if (

        survivability >= 40

    ) {

        routerBelief =
            "CAUTIOUS";

    }

    else {

        routerBelief =
            "SURVIVAL";

    }

    // =========================
    // FINAL COGNITION STATE
    // =========================

    return {

        execution: {

            route,

            confidence,

            survivability,

            restrictionReason,

        },

        router: {

            status:
                survivability >= 40
                    ? "ACTIVE"
                    : "RESTRICTED",

            belief:
                routerBelief,

            routingQuality,

            lastRouteUpdate:
                Date.now(),

        },

        cognition: {

            routerBelief,

            marketBelief,

            executionBelief,

            riskBelief,

        },

        market: {

            marketRegime,

            marketPhase,

            microstructureSignals,

        },

        signal,

        direction,

        orderStatus,

        riskLevel,

        latency,

        wsStatus,

        engineStatus,

    };

}