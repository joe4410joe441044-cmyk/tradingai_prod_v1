import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("hook exposes the MM-5C data interface without API details", async () => {
  const source = await readFile(
    new URL("./useMoneyManagement.js", import.meta.url),
    "utf8",
  );
  for (const publicName of [
    "status",
    "rawStatus",
    "configuration",
    "configurationDraft",
    "isInitialLoading",
    "isRefreshing",
    "isManualRefreshing",
    "isUpdatingConfiguration",
    "isRecovering",
    "isClientStale",
    "configurationConflict",
    "refresh",
    "updateConfigurationDraft",
    "resetConfigurationDraft",
    "saveConfiguration",
    "recover",
    "clearError",
  ]) {
    assert.match(source, new RegExp(`\\b${publicName}\\b`));
  }
  assert.doesNotMatch(source, /\/api\/money-management/);
});

test("configuration and recovery await controlled refreshes", async () => {
  const source = await readFile(
    new URL("./useMoneyManagement.js", import.meta.url),
    "utf8",
  );
  const updateStart = source.indexOf(
    "client.updateConfiguration(payload",
  );
  const recoveryStart = source.indexOf("client.recover({ timeoutMs })");
  const updateRefresh = source.indexOf(
    "await refreshStatus({ supersede: true })",
    updateStart,
  );
  const recoveryRefresh = source.indexOf(
    "await refreshStatus({ supersede: true })",
    recoveryStart,
  );
  assert.ok(updateStart >= 0 && updateRefresh > updateStart);
  assert.ok(recoveryStart >= 0 && recoveryRefresh > recoveryStart);
  assert.match(source, /await refreshConfiguration\(\)/);
  assert.match(source, /new AbortController\(\)/);
});

test("manual refresh gets status and configuration with cross-operation exclusion", async () => {
  const source = await readFile(
    new URL("./useMoneyManagement.js", import.meta.url),
    "utf8",
  );
  assert.match(source, /Promise\.all\(\[/);
  assert.match(source, /refreshStatus\(\{ supersede: true \}\)/);
  assert.match(source, /refreshConfiguration\(\)/);
  assert.match(source, /manualRefreshRunningRef/);
  assert.match(
    source,
    /updateRunningRef\.current \|\|\s+recoveryRunningRef\.current/,
  );
  assert.match(source, /configurationRequestSequenceRef/);
  assert.match(
    source,
    /configurationRequestControllerRef\.current\?\.abort\(\)/,
  );
  assert.match(
    source,
    /requestId !== configurationRequestSequenceRef\.current/,
  );
});
