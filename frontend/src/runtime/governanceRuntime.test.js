import assert from "node:assert/strict";
import test from "node:test";

import {
    classifyEmergencyResult,
    GovernanceApiError,
    retryEmergency,
    runEmergencyOrchestrator,
    setExecutionEnabled,
    unlockEmergency,
} from "./governanceRuntime.js";

const jsonResponse = ({
    ok = true,
    status = 200,
    body,
    jsonError = null,
} = {}) => ({
    ok,
    status,
    json: async () => {
        if (jsonError) {
            throw jsonError;
        }

        return body;
    },
});

const emergencyResponse = (
    overrides = {}
) => ({
    success: true,
    completed: true,
    partial: false,
    state_unknown: false,
    emergency_locked: true,
    auto_trade_disabled: true,
    execution_path: "paper",
    symbol: "XRPUSDT",
    cancel: null,
    flatten: {
        success: true,
        skipped: true,
    },
    position_remaining: false,
    retryable: false,
    error_code: null,
    ...overrides,
});

test("setExecutionEnabled returns confirmed success response", async () => {
    const requests = [];
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (
        url,
        options
    ) => {
        requests.push({
            url,
            options,
        });

        return jsonResponse({
            body: {
                success: true,
                execution_enabled: true,
            },
        });
    };

    try {
        const result = await setExecutionEnabled(true);

        assert.deepEqual(result, {
            success: true,
            execution_enabled: true,
        });
        assert.equal(requests.length, 1);
        assert.equal(requests[0].url, "/api/governance/execution");
        assert.equal(requests[0].options.method, "POST");
        assert.deepEqual(
            JSON.parse(requests[0].options.body),
            { enabled: true },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("setExecutionEnabled keeps 409 loop guard as failure metadata", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 409,
        body: {
            detail: {
                reason: "AUTO_TRADE_REQUIRES_LOOP_ON",
                execution_enabled: false,
            },
        },
    });

    try {
        await assert.rejects(
            () => setExecutionEnabled(true),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 409);
                assert.equal(error.code, "AUTO_TRADE_REQUIRES_LOOP_ON");
                assert.equal(
                    error.data.detail.execution_enabled,
                    false,
                );
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("setExecutionEnabled keeps 409 emergency lock guard as failure metadata", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 409,
        body: {
            detail: {
                reason: "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK",
                emergency_stop: true,
            },
        },
    });

    try {
        await assert.rejects(
            () => setExecutionEnabled(true),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 409);
                assert.equal(
                    error.code,
                    "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK",
                );
                assert.equal(error.data.detail.emergency_stop, true);
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("setExecutionEnabled treats HTTP 500 as failure", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 500,
        body: {
            detail: "server failed",
        },
    });

    try {
        await assert.rejects(
            () => setExecutionEnabled(false),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 500);
                assert.equal(error.code, "server failed");
                assert.equal(error.message, "server failed");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("setExecutionEnabled distinguishes network failure", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => {
        throw new TypeError("failed to fetch");
    };

    try {
        await assert.rejects(
            () => setExecutionEnabled(true),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, null);
                assert.equal(error.code, "NETWORK_ERROR");
                assert.equal(
                    error.message,
                    "Unable to reach the server.",
                );
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("setExecutionEnabled treats malformed success JSON as failure", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: true,
        status: 200,
        jsonError: new SyntaxError("bad json"),
    });

    try {
        await assert.rejects(
            () => setExecutionEnabled(true),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 200);
                assert.equal(error.code, "MALFORMED_RESPONSE");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("setExecutionEnabled supports confirmed OFF success", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        body: {
            success: true,
            execution_enabled: false,
        },
    });

    try {
        const result = await setExecutionEnabled(false);

        assert.deepEqual(result, {
            success: true,
            execution_enabled: false,
        });
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("runEmergencyOrchestrator posts without body and returns verified response", async () => {
    const requests = [];
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (
        url,
        options
    ) => {
        requests.push({
            url,
            options,
        });

        return jsonResponse({
            body: emergencyResponse(),
        });
    };

    try {
        const result = await runEmergencyOrchestrator();

        assert.equal(requests.length, 1);
        assert.equal(
            requests[0].url,
            "/api/governance/emergency-orchestrate",
        );
        assert.equal(requests[0].options.method, "POST");
        assert.equal(
            Object.prototype.hasOwnProperty.call(
                requests[0].options,
                "body",
            ),
            false,
        );
        assert.equal(result.completed, true);
        assert.equal(result.emergency_locked, true);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("runEmergencyOrchestrator keeps 409 metadata as failure", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 409,
        body: {
            detail: {
                reason: "EMERGENCY_ALREADY_RUNNING",
            },
        },
    });

    try {
        await assert.rejects(
            () => runEmergencyOrchestrator(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 409);
                assert.equal(error.code, "EMERGENCY_ALREADY_RUNNING");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("runEmergencyOrchestrator treats HTTP 500 as failure", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 500,
        body: {
            detail: "orchestrator failed",
        },
    });

    try {
        await assert.rejects(
            () => runEmergencyOrchestrator(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 500);
                assert.equal(error.code, "orchestrator failed");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("runEmergencyOrchestrator distinguishes network failure", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => {
        throw new TypeError("failed to fetch");
    };

    try {
        await assert.rejects(
            () => runEmergencyOrchestrator(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, null);
                assert.equal(error.code, "NETWORK_ERROR");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("runEmergencyOrchestrator rejects malformed success JSON", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: true,
        status: 200,
        jsonError: new SyntaxError("bad json"),
    });

    try {
        await assert.rejects(
            () => runEmergencyOrchestrator(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 200);
                assert.equal(error.code, "MALFORMED_RESPONSE");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("runEmergencyOrchestrator rejects malformed success schema", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: true,
        status: 200,
        body: {
            success: true,
        },
    });

    try {
        await assert.rejects(
            () => runEmergencyOrchestrator(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 200);
                assert.equal(error.code, "MALFORMED_RESPONSE");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("retryEmergency posts without body and returns verified response", async () => {
    const requests = [];
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (
        url,
        options
    ) => {
        requests.push({
            url,
            options,
        });

        return jsonResponse({
            body: emergencyResponse(),
        });
    };

    try {
        const result = await retryEmergency();

        assert.equal(requests.length, 1);
        assert.equal(
            requests[0].url,
            "/api/governance/emergency/retry",
        );
        assert.equal(requests[0].options.method, "POST");
        assert.equal(
            Object.prototype.hasOwnProperty.call(
                requests[0].options,
                "body",
            ),
            false,
        );
        assert.equal(result.completed, true);
        assert.equal(result.emergency_locked, true);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("retryEmergency keeps 409 reason metadata", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 409,
        body: {
            detail: {
                reason: "NOT_ACTION_REQUIRED",
            },
        },
    });

    try {
        await assert.rejects(
            () => retryEmergency(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 409);
                assert.equal(error.code, "NOT_ACTION_REQUIRED");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("retryEmergency rejects malformed success schema", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: true,
        status: 200,
        body: {
            success: true,
        },
    });

    try {
        await assert.rejects(
            () => retryEmergency(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 200);
                assert.equal(error.code, "MALFORMED_RESPONSE");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("unlockEmergency posts without body and returns confirmed unlock", async () => {
    const requests = [];
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (
        url,
        options
    ) => {
        requests.push({
            url,
            options,
        });

        return jsonResponse({
            body: {
                success: true,
                unlocked: true,
                emergency_stop: false,
                emergency_state: "READY",
            },
        });
    };

    try {
        const result = await unlockEmergency();

        assert.equal(requests.length, 1);
        assert.equal(
            requests[0].url,
            "/api/governance/emergency/unlock",
        );
        assert.equal(requests[0].options.method, "POST");
        assert.equal(
            Object.prototype.hasOwnProperty.call(
                requests[0].options,
                "body",
            ),
            false,
        );
        assert.equal(result.success, true);
        assert.equal(result.unlocked, true);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("unlockEmergency keeps 409 reason metadata", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => jsonResponse({
        ok: false,
        status: 409,
        body: {
            detail: {
                reason: "POSITION_REMAINING",
            },
        },
    });

    try {
        await assert.rejects(
            () => unlockEmergency(),
            (error) => {
                assert.ok(error instanceof GovernanceApiError);
                assert.equal(error.status, 409);
                assert.equal(error.code, "POSITION_REMAINING");
                return true;
            },
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test("classifyEmergencyResult prioritizes dangerous flags", () => {
    assert.equal(
        classifyEmergencyResult(
            emergencyResponse({
                completed: true,
                partial: true,
                state_unknown: true,
                position_remaining: true,
            }),
        ).key,
        "state_unknown",
    );
    assert.equal(
        classifyEmergencyResult(
            emergencyResponse({
                completed: false,
                partial: true,
                position_remaining: true,
            }),
        ).key,
        "position_remaining",
    );
    assert.equal(
        classifyEmergencyResult(
            emergencyResponse({
                completed: false,
                partial: true,
                position_remaining: false,
            }),
        ).key,
        "partial",
    );
    assert.equal(
        classifyEmergencyResult(emergencyResponse()).key,
        "completed",
    );
    assert.equal(
        classifyEmergencyResult(
            emergencyResponse({
                success: true,
                completed: false,
                partial: false,
                position_remaining: false,
            }),
        ).key,
        "failed",
    );
});
