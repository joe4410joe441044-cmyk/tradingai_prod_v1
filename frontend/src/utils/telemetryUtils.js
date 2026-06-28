export function mapExecutionHealth(
    runtimeHealthy,
    runtimeDegraded
) {

    if (!runtimeHealthy) {

        return "CRITICAL";

    }

    if (runtimeDegraded) {

        return "DEGRADED";

    }

    return "HEALTHY";

}


/* =================================================
   LATENCY QUALITY
================================================= */

export const mapLatencyQuality = (

    latency

) => {

    if (
        latency === null
        || latency === undefined
        || latency === "-"
    ) {

        return "UNKNOWN";

    }

    if (latency < 30) {

        return "GOOD";

    }

    if (latency < 80) {

        return "NORMAL";

    }

    if (latency < 150) {

        return "WEAK";

    }

    return "UNSTABLE";

};

/* =================================================
   COGNITION STABILITY
================================================= */

export const mapCognitionStability = (

    latency

) => {

    if (
        latency === null
        || latency === undefined
        || latency === "-"
    ) {

        return "UNKNOWN";

    }

    if (latency < 50) {

        return "STABLE";

    }

    if (latency < 120) {

        return "DEGRADED";

    }

    return "CRITICAL";

};

/* =================================================
   SPREAD SAFETY
================================================= */

export const mapSpreadSafety = (

    spreadSafety

) => {

    if (
        spreadSafety === "SAFE"
    ) {

        return "SAFE";

    }

    if (
        spreadSafety === "WARNING"
    ) {

        return "WARNING";

    }

    return "DANGER";

};

/* =================================================
   ROUTING QUALITY
================================================= */

export const mapRoutingQuality = (

    routingQuality

) => {

    if (
        routingQuality === "GOOD"
    ) {

        return "GOOD";

    }

    if (
        routingQuality === "WEAK"
    ) {

        return "WEAK";

    }

    return "UNSTABLE";

};