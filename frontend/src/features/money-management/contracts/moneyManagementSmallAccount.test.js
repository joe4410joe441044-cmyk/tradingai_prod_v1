import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  APPROVED_SMALL_ACCOUNT_PROFILE,
  buildMoneyManagementConfigurationPayload,
  configurationDraftFromAuthoritative,
  MONEY_MANAGEMENT_SMALL_ACCOUNT_FIELDS,
  normalizeMoneyManagementConfiguration,
  validateMoneyManagementConfigurationDraft,
} from "./moneyManagementContracts.js";
import { validConfiguration } from "./moneyManagementFixtures.js";
import {
  createMoneyManagementInteractionViewModel,
  MONEY_MANAGEMENT_CONFIGURATION_FIELDS,
} from "../view/moneyManagementInteractionViewModel.js";
import {
  createInitialMoneyManagementState,
  MONEY_MANAGEMENT_ACTION,
  moneyManagementReducer,
} from "../state/moneyManagementReducer.js";

const APPROVED_PROFILE = Object.freeze({
  smallAccountMinimumContractMode: true,
  smallAccountAllowedSymbol: "XRPUSDTM",
  smallAccountMaxContracts: "1",
  smallAccountMaxRiskPercent: "2.0",
  smallAccountMaxAbsoluteRiskUsdt: "0.158",
  smallAccountMaxLeverage: "3",
  smallAccountRequireIsolated: true,
  smallAccountRequireFlatBeforeEntry: true,
  smallAccountRequireNoPending: true,
  smallAccountRequireManualSelection: true,
});

const REQUIREMENT_FIELDS = [
  "smallAccountRequireIsolated",
  "smallAccountRequireFlatBeforeEntry",
  "smallAccountRequireNoPending",
  "smallAccountRequireManualSelection",
];

const EXISTING_MM_FIELDS = Object.freeze({
  enabled: true,
  dailyWarningPercent: "1.00",
  dailyBlockPercent: "1.50",
  weeklyWarningPercent: "2.00",
  weeklyBlockPercent: "3.00",
  monthlyWarningPercent: "3.50",
  monthlyBlockPercent: "4.00",
  maximumDrawdownPercent: "5.00",
  totalExposurePercent: "20.00",
  riskPerTradePercent: "0.50",
  maximumPositionNotional: "100.00",
  singleSymbolExposurePercent: "10.00",
  compoundingEnabled: false,
});

const safeStatus = Object.freeze({
  available: true,
  lifecycleState: "RUNNING",
  riskState: "NORMAL",
  projectionStatus: "ALLOW",
  executionEntryAllowed: true,
  revision: 5,
});

const configuration = (overrides = {}) =>
  normalizeMoneyManagementConfiguration(
    validConfiguration({ ...APPROVED_PROFILE, ...overrides }),
  );

const draft = (overrides = {}) => ({
  ...configurationDraftFromAuthoritative(configuration()),
  ...overrides,
});

test("A. default OFF is preserved and the stored profile may be empty", () => {
  const normalized = normalizeMoneyManagementConfiguration(validConfiguration());
  const base = configurationDraftFromAuthoritative(normalized);
  assert.equal(base.smallAccountMinimumContractMode, false);
  assert.equal(base.smallAccountAllowedSymbol, "XRPUSDTM");
  assert.equal(base.smallAccountMaxContracts, null);
  assert.equal(base.smallAccountMaxRiskPercent, null);
  assert.equal(base.smallAccountMaxAbsoluteRiskUsdt, null);
  assert.equal(base.smallAccountMaxLeverage, null);
  for (const field of REQUIREMENT_FIELDS) {
    assert.equal(base[field], true);
  }
  assert.equal(validateMoneyManagementConfigurationDraft(base, 7).valid, true);
});

test("B. approved profile survives GET normalization into the UI draft", () => {
  const base = configurationDraftFromAuthoritative(configuration());
  assert.deepEqual(
    {
      mode: base.smallAccountMinimumContractMode,
      symbol: base.smallAccountAllowedSymbol,
      contracts: base.smallAccountMaxContracts,
      risk: base.smallAccountMaxRiskPercent,
      absoluteRisk: base.smallAccountMaxAbsoluteRiskUsdt,
      leverage: base.smallAccountMaxLeverage,
      isolated: base.smallAccountRequireIsolated,
      flat: base.smallAccountRequireFlatBeforeEntry,
      noPending: base.smallAccountRequireNoPending,
      manual: base.smallAccountRequireManualSelection,
    },
    {
      mode: true,
      symbol: "XRPUSDTM",
      contracts: "1",
      risk: "2.0",
      absoluteRisk: "0.158",
      leverage: "3",
      isolated: true,
      flat: true,
      noPending: true,
      manual: true,
    },
  );
  for (const field of MONEY_MANAGEMENT_SMALL_ACCOUNT_FIELDS) {
    assert.ok(field in base, `${field} must survive into the draft`);
  }
  const model = createMoneyManagementInteractionViewModel({
    configuration: configuration(),
    configurationDraft: base,
    pollingState: "RUNNING",
    status: safeStatus,
  });
  assert.equal(model.configuration.dirty, false);
  assert.equal(
    (model.configuration.saveDisabledReason ?? "").includes("invalid"),
    false,
  );
});

test("configuration field model exposes typed small-account controls", () => {
  const byKey = Object.fromEntries(
    MONEY_MANAGEMENT_CONFIGURATION_FIELDS.map((field) => [field.key, field]),
  );
  assert.equal(byKey.smallAccountMinimumContractMode.type, "boolean");
  assert.equal(byKey.smallAccountAllowedSymbol.type, "symbol");
  assert.equal(byKey.smallAccountMaxContracts.type, "integer");
  assert.equal(byKey.smallAccountMaxRiskPercent.type, "decimal");
  assert.equal(byKey.smallAccountMaxAbsoluteRiskUsdt.type, "decimal");
  assert.equal(byKey.smallAccountMaxLeverage.type, "integer");
  for (const field of REQUIREMENT_FIELDS) {
    assert.equal(byKey[field].type, "boolean");
    assert.equal(byKey[field].section, "smallAccount");
  }
  assert.equal(APPROVED_SMALL_ACCOUNT_PROFILE.allowedSymbol, "XRPUSDTM");
});

test("C. OFF -> ON draft changes require an explicit Save (no auto-persist)", async () => {
  let state = createInitialMoneyManagementState();
  state = moneyManagementReducer(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration({ smallAccountMinimumContractMode: false }),
  });
  state = moneyManagementReducer(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { smallAccountMinimumContractMode: true },
  });
  assert.equal(state.configurationDraft.smallAccountMinimumContractMode, true);
  assert.equal(state.configuration.smallAccountMinimumContractMode, false);

  const hook = await readFile(
    new URL("../hooks/useMoneyManagement.js", import.meta.url),
    "utf8",
  );
  assert.match(hook, /MONEY_MANAGEMENT_SMALL_ACCOUNT_FIELDS/);
  const dirtyIndex = hook.indexOf("const smallAccountDirty");
  const shortCircuit = hook.indexOf(
    "if (smallAccountDirty) return undefined;",
    dirtyIndex,
  );
  const autoSaveTimer = hook.indexOf("setTimeout(", dirtyIndex);
  assert.ok(dirtyIndex >= 0, "auto-save must detect small-account edits");
  assert.ok(
    shortCircuit > dirtyIndex && autoSaveTimer > shortCircuit,
    "small-account edits must short-circuit the auto-save timer",
  );
});

test("D. full-object Save serializes small-account + existing MM + expectedRevision", () => {
  const payload = buildMoneyManagementConfigurationPayload(draft(), 7);
  for (const [key, value] of Object.entries(APPROVED_PROFILE)) {
    assert.equal(payload[key], value, `${key} must be serialized`);
  }
  for (const [key, value] of Object.entries(EXISTING_MM_FIELDS)) {
    assert.equal(payload[key], value, `${key} must be preserved on save`);
  }
  assert.equal(payload.expectedRevision, 7);
});

test("E. expectedRevision is taken from the authoritative revision", () => {
  const authoritative = configuration({ revision: 42 });
  const payload = buildMoneyManagementConfigurationPayload(
    configurationDraftFromAuthoritative(authoritative),
    authoritative.revision,
  );
  assert.equal(payload.expectedRevision, 42);
});

test("F. a stale revision is carried verbatim, never hardcoded", () => {
  const payload = buildMoneyManagementConfigurationPayload(draft(), 41);
  assert.equal(payload.expectedRevision, 41);

  let state = createInitialMoneyManagementState();
  state = moneyManagementReducer(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_REQUEST_SUCCESS,
    configuration: configuration({ revision: 7 }),
  });
  state = moneyManagementReducer(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_DRAFT_UPDATE,
    patch: { smallAccountMinimumContractMode: false },
  });
  state = moneyManagementReducer(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_UPDATE_START,
  });
  state = moneyManagementReducer(state, {
    type: MONEY_MANAGEMENT_ACTION.CONFIGURATION_CONFLICT,
    error: { code: "REVISION_CONFLICT" },
    submittedRevision: 7,
    currentConfiguration: configuration({ revision: 8 }),
  });
  assert.equal(state.configuration.revision, 8);
  assert.equal(state.configurationDraft.smallAccountMinimumContractMode, false);
  assert.equal(state.configuration.smallAccountMinimumContractMode, true);
  assert.equal(state.configurationConflict.draftPreserved, true);
});

for (const [field, value] of [
  ["smallAccountMaxContracts", "2"],
  ["smallAccountMaxRiskPercent", "2.1"],
  ["smallAccountMaxAbsoluteRiskUsdt", "0.159"],
  ["smallAccountMaxLeverage", "4"],
]) {
  test(`G-J. unsafe ${field}=${value} is rejected while mode is ON`, () => {
    const result = validateMoneyManagementConfigurationDraft(
      draft({ [field]: value }),
      7,
    );
    assert.equal(result.valid, false);
    assert.ok(result.errors[field], `${field} must report an error`);
  });
}

test("K. a non-XRPUSDTM symbol is rejected while mode is ON", () => {
  const result = validateMoneyManagementConfigurationDraft(
    draft({ smallAccountAllowedSymbol: "BTCUSDTM" }),
    7,
  );
  assert.equal(result.valid, false);
  assert.equal(result.errors.smallAccountAllowedSymbol, "UNSUPPORTED_SYMBOL");
});

test("L. each required safety boolean rejects false while mode is ON", () => {
  for (const field of REQUIREMENT_FIELDS) {
    const result = validateMoneyManagementConfigurationDraft(
      draft({ [field]: false }),
      7,
    );
    assert.equal(result.valid, false);
    assert.equal(result.errors[field], "SMALL_ACCOUNT_REQUIREMENT");
  }
});

test("M. turning mode OFF preserves the stored approved profile", () => {
  const off = draft({ smallAccountMinimumContractMode: false });
  assert.equal(validateMoneyManagementConfigurationDraft(off, 7).valid, true);
  const payload = buildMoneyManagementConfigurationPayload(off, 7);
  assert.equal(payload.smallAccountMinimumContractMode, false);
  assert.equal(payload.smallAccountAllowedSymbol, "XRPUSDTM");
  assert.equal(payload.smallAccountMaxContracts, "1");
  assert.equal(payload.smallAccountMaxRiskPercent, "2.0");
  assert.equal(payload.smallAccountMaxAbsoluteRiskUsdt, "0.158");
  assert.equal(payload.smallAccountMaxLeverage, "3");
  for (const field of REQUIREMENT_FIELDS) {
    assert.equal(payload[field], true);
  }
});

test("N. saving small-account config preserves existing Money Management values", () => {
  const payload = buildMoneyManagementConfigurationPayload(draft(), 7);
  for (const [key, value] of Object.entries(EXISTING_MM_FIELDS)) {
    assert.equal(payload[key], value);
  }
});

test("O. saving an unrelated MM field preserves the small-account values", () => {
  const unrelated = draft({
    smallAccountMinimumContractMode: false,
    dailyWarningPercent: "1.25",
  });
  const payload = buildMoneyManagementConfigurationPayload(unrelated, 7);
  assert.equal(payload.dailyWarningPercent, "1.25");
  assert.equal(payload.smallAccountAllowedSymbol, "XRPUSDTM");
  assert.equal(payload.smallAccountMaxContracts, "1");
  assert.equal(payload.smallAccountMaxRiskPercent, "2.0");
  assert.equal(payload.smallAccountMaxAbsoluteRiskUsdt, "0.158");
  assert.equal(payload.smallAccountMaxLeverage, "3");
});

test("P. frontend config save exposes no bot/order side effects", async () => {
  const api = await readFile(
    new URL("../api/moneyManagementApi.js", import.meta.url),
    "utf8",
  );
  for (const forbidden of [
    "START_BOT",
    "START_RUNTIME",
    '"ARM"',
    "submitOrder",
    "createOrder",
    "placeOrder",
  ]) {
    assert.equal(
      api.includes(forbidden),
      false,
      `moneyManagementApi.js must not reference ${forbidden}`,
    );
  }
  const hook = await readFile(
    new URL("../hooks/useMoneyManagement.js", import.meta.url),
    "utf8",
  );
  for (const forbidden of [
    "START_RUNTIME",
    "submitOrder",
    "createOrder",
    "placeOrder",
    "startBot",
    "armBot",
  ]) {
    assert.equal(
      hook.includes(forbidden),
      false,
      `useMoneyManagement.js must not reference ${forbidden}`,
    );
  }
});

test("card source renders the small-account section with string-preserving controls", async () => {
  const source = await readFile(
    new URL(
      "../../../components/money-management/MoneyManagementConfigurationCard.jsx",
      import.meta.url,
    ),
    "utf8",
  );
  assert.match(source, /SMALL_ACCOUNT_CONFIGURATION_SECTION_LABEL/);
  assert.match(source, /mm-configuration-section--small-account/);
  assert.match(source, /value=\{value \?\? ""\}/);
  assert.match(source, /checked=\{value === true\}/);
  assert.match(source, /aria-label=\{SMALL_ACCOUNT_CONFIGURATION_SECTION_LABEL\}/);
  assert.match(source, /field\.type === "integer"/);
  assert.match(source, /field\.type === "symbol"/);
  assert.doesNotMatch(source, /parseFloat|parseInt|valueAsNumber/);
});
