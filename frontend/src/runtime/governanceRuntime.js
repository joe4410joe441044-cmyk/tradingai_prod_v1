// frontend/src/runtime/governanceRuntime.js

const API_BASE =
    "/api/governance";

/* =================================================
   MODE
================================================= */

export async function setMode(
    mode
) {

    const response = await fetch(

        `${API_BASE}/mode`,

        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json",
            },

            body: JSON.stringify({
                mode,
            }),
        }

    );

    return await response.json();

}

/* =================================================
   EXECUTION ENABLE
================================================= */

export async function setExecutionEnabled(
    enabled
) {

    const response = await fetch(

        `${API_BASE}/execution`,

        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json",
            },

            body: JSON.stringify({
                enabled,
            }),
        }

    );

    return await response.json();

}

/* =================================================
   RISK PROFILE
================================================= */

export async function setRiskProfile(
    profile
) {

    const response = await fetch(

        `${API_BASE}/risk-profile`,

        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json",
            },

            body: JSON.stringify({
                risk_profile:
                    profile,
            }),
        }

    );

    return await response.json();

}

/* =================================================
   EMERGENCY STOP
================================================= */

export async function triggerEmergencyStop() {

    const response = await fetch(

        `${API_BASE}/emergency-stop`,

        {
            method: "POST",
        }

    );

    return await response.json();

}

/* =================================================
   GOVERNANCE STATUS
================================================= */

export async function getGovernanceStatus() {

    const response = await fetch(

        `${API_BASE}/status`

    );

    return await response.json();

}