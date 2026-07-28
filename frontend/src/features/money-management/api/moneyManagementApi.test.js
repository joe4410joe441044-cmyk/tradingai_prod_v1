import assert from "node:assert/strict";
import test from "node:test";

import {
  getMoneyManagementConfiguration,
  getMoneyManagementStatus,
  previewMoneyManagementPositionSize,
  requestMoneyManagementRecovery,
  updateMoneyManagementConfiguration,
} from "./moneyManagementApi.js";
import {
  validConfiguration,
  validRecoveryResponse,
  validStatus,
  validUpdateResponse,
} from "../contracts/moneyManagementFixtures.js";

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () =>
      typeof body === "string" ? body : JSON.stringify(body),
  };
}

test("five API functions use the exact Money Management endpoints", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/position-size/preview")) {
      return response({ calculationAllowed: true });
    }
    if (url.endsWith("/status")) return response(validStatus());
    if (url.endsWith("/recovery")) return response(validRecoveryResponse());
    if (options.method === "PUT") return response(validUpdateResponse());
    return response(validConfiguration());
  };
  await getMoneyManagementStatus({ fetchImpl, timeoutMs: null });
  await getMoneyManagementConfiguration({ fetchImpl, timeoutMs: null });
  const payload = {
    enabled: true,
    dailyWarningPercent: "1.00",
    expectedRevision: 7,
  };
  await updateMoneyManagementConfiguration(payload, {
    fetchImpl,
    timeoutMs: null,
  });
  await requestMoneyManagementRecovery({ fetchImpl, timeoutMs: null });
  await previewMoneyManagementPositionSize(
    { entryPrice: "1.00" },
    { fetchImpl, timeoutMs: null },
  );
  assert.deepEqual(
    calls.map(({ url, options }) => [url, options.method]),
    [
      ["/api/money-management/status", "GET"],
      ["/api/money-management/configuration", "GET"],
      ["/api/money-management/configuration", "PUT"],
      ["/api/money-management/recovery", "POST"],
      ["/api/money-management/position-size/preview", "POST"],
    ],
  );
  assert.equal(
    JSON.parse(calls[2].options.body).dailyWarningPercent,
    "1.00",
  );
});

test("malformed and empty success responses are INVALID_RESPONSE", async () => {
  for (const body of ["{broken", ""]) {
    await assert.rejects(
      getMoneyManagementStatus({
        fetchImpl: async () => response(body),
        timeoutMs: null,
      }),
      { code: "INVALID_RESPONSE" },
    );
  }
});

test("HTTP status mapping is operation-aware and secret safe", async () => {
  const cases = [
    [401, getMoneyManagementStatus, "UNAUTHORIZED"],
    [403, getMoneyManagementStatus, "FORBIDDEN"],
    [404, getMoneyManagementStatus, "NOT_FOUND"],
    [400, updateMoneyManagementConfiguration, "VALIDATION_ERROR"],
    [415, updateMoneyManagementConfiguration, "VALIDATION_ERROR"],
    [422, updateMoneyManagementConfiguration, "VALIDATION_ERROR"],
    [429, getMoneyManagementStatus, "RATE_LIMITED"],
    [500, getMoneyManagementStatus, "SERVER_ERROR"],
  ];
  for (const [status, fn, code] of cases) {
    const invoke =
      fn === updateMoneyManagementConfiguration
        ? fn({}, {
            fetchImpl: async () =>
              response("<html>secret stack trace</html>", status),
            timeoutMs: null,
          })
        : fn({
            fetchImpl: async () =>
              response("<html>secret stack trace</html>", status),
            timeoutMs: null,
          });
    await assert.rejects(invoke, (error) => {
      assert.equal(error.code, code);
      assert.doesNotMatch(JSON.stringify(error), /secret|stack trace/);
      return true;
    });
  }
});

test("409 configuration and recovery conflicts remain distinct", async () => {
  await assert.rejects(
    updateMoneyManagementConfiguration({}, {
      fetchImpl: async () =>
        response({ code: "CONFIGURATION_REVISION_CONFLICT" }, 409),
      timeoutMs: null,
    }),
    { code: "REVISION_CONFLICT" },
  );
  await assert.rejects(
    requestMoneyManagementRecovery({
      fetchImpl: async () =>
        response({ code: "RECOVERY_ALREADY_RUNNING" }, 409),
      timeoutMs: null,
    }),
    { code: "RECOVERY_CONFLICT" },
  );
});

test("network, timeout, and caller abort are distinct", async () => {
  await assert.rejects(
    getMoneyManagementStatus({
      fetchImpl: async () => {
        throw new TypeError("offline");
      },
      timeoutMs: null,
    }),
    { code: "NETWORK_ERROR" },
  );
  const waitForAbort = (_url, { signal }) =>
    new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      }, { once: true });
      void resolve;
    });
  await assert.rejects(
    getMoneyManagementStatus({ fetchImpl: waitForAbort, timeoutMs: 5 }),
    { code: "TIMEOUT" },
  );
  const controller = new AbortController();
  const pending = getMoneyManagementStatus({
    fetchImpl: waitForAbort,
    signal: controller.signal,
    timeoutMs: null,
  });
  controller.abort();
  await assert.rejects(pending, { code: "ABORTED" });
});
