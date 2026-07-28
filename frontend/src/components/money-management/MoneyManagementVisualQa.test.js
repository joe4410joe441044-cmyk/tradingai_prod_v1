import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readSource = (path) =>
  readFile(new URL(path, import.meta.url), "utf8");

test("visual polish reuses the console design system", async () => {
  const styles = await readSource("../../styles/money-management.css");
  for (const token of [
    "--mi-surface",
    "--mi-surface-raised",
    "--mi-border",
    "--mi-border-soft",
    "--mi-text",
    "--mi-text-muted",
    "--mi-accent",
    "--mi-focus",
    "--mi-font-mono",
  ]) {
    assert.match(styles, new RegExp(token));
  }
  assert.doesNotMatch(styles, /#[0-9a-f]{3,8}/iu);
  assert.doesNotMatch(styles, /box-shadow/);
});

test("interactive controls expose focus, hover, disabled, and reduced-motion states", async () => {
  const styles = await readSource("../../styles/money-management.css");
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /:not\(:disabled\):hover/);
  assert.match(styles, /input:disabled/);
  assert.match(styles, /cursor: not-allowed/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("responsive rules protect cards, inputs, values, and header controls", async () => {
  const styles = await readSource("../../styles/money-management.css");
  assert.match(styles, /@media \(max-width: 1100px\)/);
  assert.match(styles, /@media \(max-width: 760px\)/);
  assert.match(styles, /overflow-wrap: anywhere/);
  assert.match(styles, /min-width: 0/);
  assert.match(styles, /min-height: 36px/);
  assert.match(styles, /grid-template-columns: minmax\(0, 1fr\)/);
});

test("polished controls retain accessible native semantics", async () => {
  const [configuration, recovery, refresh, header] = await Promise.all([
    readSource("./MoneyManagementConfigurationCard.jsx"),
    readSource("./MoneyManagementRecoveryCard.jsx"),
    readSource("./MoneyManagementManualRefreshControl.jsx"),
    readSource("./MoneyManagementHeader.jsx"),
  ]);
  assert.match(configuration, /htmlFor=\{inputId\}/);
  assert.match(configuration, /aria-invalid/);
  assert.match(configuration, /<dl className="mm-configuration-meta">/);
  assert.match(recovery, /aria-live="polite"/);
  assert.match(recovery, /role="group"/);
  assert.match(recovery, /aria-label="Confirm recovery evaluation"/);
  assert.match(refresh, /aria-busy/);
  assert.match(refresh, /role="alert"/);
  assert.match(header, /aria-label="Money Management status bar"/);
  assert.match(header, /<time className="mm-status-bar__time">/);
  assert.doesNotMatch(header, /mi-header__title|mi-header__subtitle/);
});

test("interactive Money Management cards use the existing form and action styles", async () => {
  const [styles, sizing, simulation, history] = await Promise.all([
    readSource("../../styles/money-management.css"),
    readSource("./MoneyManagementPositionSizingCard.jsx"),
    readSource("./MoneyManagementSimulationCard.jsx"),
    readSource("./MoneyManagementRuntimeHistoryCard.jsx"),
  ]);
  assert.match(styles, /\.mm-interaction-form/);
  assert.match(styles, /\.mm-configuration-field select/);
  assert.match(styles, /\.mm-runtime-timeline/);
  assert.match(styles, /\.mm-history-charts/);
  assert.match(sizing, /className="mm-interaction-form"/);
  assert.match(sizing, /className="mm-action-row"/);
  assert.match(sizing, /\["entryPrice", "Entry Price"\]/);
  assert.match(simulation, /className="mm-interaction-form"/);
  assert.match(history, /mm-history-filter/);
});
