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

test("regression: hook mounts without a temporal-dead-zone ReferenceError (black-screen fix)", async () => {
  // The auto-save effect references `saveConfiguration` in its dependency
  // array. If that effect is declared BEFORE `saveConfiguration`, reading the
  // const in its deps throws `ReferenceError: Cannot access 'saveConfiguration'
  // before initialization` during the render body, which unmounts the whole
  // React tree (black screen). renderToString runs the render body but not
  // effects, so a server render catches that ordering bug deterministically.
  const React = (await import("react")).default;
  const { renderToString } = await import("react-dom/server");
  const { useMoneyManagement } = await import("./useMoneyManagement.js");
  const Probe = () => {
    useMoneyManagement({ pollingIntervalMs: 999999, enabled: true });
    return React.createElement("div", null, "MM_MOUNTED");
  };
  let html;
  assert.doesNotThrow(() => {
    html = renderToString(React.createElement(Probe));
  });
  assert.match(html, /MM_MOUNTED/);
});
