import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (name) =>
    readFile(new URL(`./${name}`, import.meta.url), "utf8");

test("Summary renders Runtime, Risk, Exposure, and Capital cards", async () => {
    const content = await source("MoneyManagementSummaryCards.jsx");
    for (const card of [
        "RuntimeSummaryCard",
        "RiskSummaryCard",
        "ExposureSummaryCard",
        "CapitalSummaryCard",
    ]) {
        assert.match(content, new RegExp(`function ${card}`));
    }
    for (const title of ["Runtime", "Risk", "Exposure", "Capital"]) {
        assert.match(content, new RegExp(`title="${title}"`));
    }
});

test("Main cards render Risk State, Performance, Statistics, and Projection", async () => {
    const [main, risk, metrics] = await Promise.all([
        source("MoneyManagementMainSection.jsx"),
        source("MoneyManagementRiskStateCard.jsx"),
        source("MoneyManagementMetricsCards.jsx"),
    ]);
    for (const component of [
        "MoneyManagementRiskStateCard",
        "PerformanceCard",
        "StatisticsCard",
        "ProjectionCard",
    ]) {
        assert.match(`${main} ${risk} ${metrics}`, new RegExp(component));
    }
    assert.match(main, /MoneyManagementConfigurationCard/);
    assert.match(main, /MoneyManagementRecoveryCard/);
    assert.doesNotMatch(
        `${main} ${risk} ${metrics}`,
        /canvas|<svg|<table|<form|Monte Carlo|Risk of Ruin/iu,
    );
});

test("Risk card keeps reason categories separate with semantic lists", async () => {
    const [risk, primitives] = await Promise.all([
        source("MoneyManagementRiskStateCard.jsx"),
        source("MoneyManagementPrimitives.jsx"),
    ]);
    for (const title of [
        "Warning Reasons",
        "Hold Reasons",
        "Block Reasons",
        "Diagnostic Reasons",
    ]) {
        assert.match(risk, new RegExp(title));
    }
    assert.match(primitives, /<ul>/);
    assert.match(primitives, /<li/);
    assert.match(primitives, /<dl/);
    assert.match(primitives, /<dt>/);
    assert.match(primitives, /<dd/);
});

test("display components do not calculate or coerce Backend values", async () => {
    const contents = await Promise.all([
        source("MoneyManagementSummaryCards.jsx"),
        source("MoneyManagementRiskStateCard.jsx"),
        source("MoneyManagementMetricsCards.jsx"),
        source("MoneyManagementPrimitives.jsx"),
    ]);
    assert.doesNotMatch(
        contents.join("\n"),
        /Number\(|parseFloat\(|Math\.round|\*\s*100/iu,
    );
});

test("responsive status styles reuse existing variables and wrap reasons", async () => {
    const styles = await readFile(
        new URL("../../styles/money-management.css", import.meta.url),
        "utf8",
    );
    for (const expected of [
        "--status-color-green",
        "--status-color-yellow",
        "--status-color-red",
        "--mi-text-muted",
        "overflow-wrap: anywhere",
        "@media (max-width: 1100px)",
    ]) {
        assert.match(styles, new RegExp(expected.replace(/[()]/g, "\\$&")));
    }
    assert.doesNotMatch(styles, /#[0-9a-f]{3,8}/iu);
});
