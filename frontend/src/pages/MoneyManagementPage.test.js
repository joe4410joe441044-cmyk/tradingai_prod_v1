import assert from "node:assert/strict";
import {
    mkdtemp,
    readFile,
    rm,
    writeFile,
} from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { MONEY_MANAGEMENT_CARD_TITLES } from "../components/money-management/moneyManagementLayout.js";

const readSource = async (path) =>
    readFile(new URL(path, import.meta.url), "utf8");
const textOf = (node) => {
    if (node == null || typeof node === "boolean") return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};

test("Money Management shell defines the complete 13-card layout", () => {
    assert.equal(MONEY_MANAGEMENT_CARD_TITLES.length, 13);
    assert.deepEqual(MONEY_MANAGEMENT_CARD_TITLES, [
        "Runtime",
        "Risk",
        "Exposure",
        "Capital",
        "Risk State",
        "Configuration",
        "Recovery",
        "Performance",
        "Statistics",
        "Projection",
        "Timeline",
        "History",
        "Future Chart",
    ]);
    assert.equal(new Set(MONEY_MANAGEMENT_CARD_TITLES).size, 13);
});

test("page composes Header, Summary, Main, Bottom, and the data hook", async () => {
    const source = await readSource("./MoneyManagementPage.jsx");
    for (const expected of [
        "MoneyManagementHeader",
        "MoneyManagementSummarySection",
        "MoneyManagementMainSection",
        "MoneyManagementBottomSection",
        "useMoneyManagement",
        "createMoneyManagementViewModel",
        "viewModel.banner",
    ]) {
        assert.match(source, new RegExp(expected));
    }
    assert.doesNotMatch(source, /console\.|canvas|<svg|<table|<form/iu);
});

test("page render keeps Header, Summary, Main, and Bottom order", async (context) => {
    let transformWithOxc;
    try {
        ({ transformWithOxc } = await import("vite"));
    } catch {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const sourceUrl = new URL("./MoneyManagementPage.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(sourceUrl, "utf8"),
        fileURLToPath(sourceUrl),
    );
    const moduleUrl = (source) =>
        `data:text/javascript,${encodeURIComponent(source)}`;
    const componentStub = (label) =>
        moduleUrl(`export default()=>({type:'section',props:{children:'${label}'}})`);
    const hookStub = moduleUrl(
        "export const useMoneyManagement=()=>({consecutiveFailures:0,isClientStale:false,isInitialLoading:false,pollingState:'RUNNING',status:{available:true},statusError:null});export const createMoneyManagementInteractionViewModel=()=>({refresh:{}})",
    );
    const viewModelStub = moduleUrl(
        "export const createMoneyManagementViewModel=()=>({banner:null,header:{},state:'READY'})",
    );
    let code = transformed.code;
    for (const [name, label] of [
        ["MoneyManagementHeader", "HEADER"],
        ["MoneyManagementSummarySection", "SUMMARY"],
        ["MoneyManagementMainSection", "MAIN"],
        ["MoneyManagementBottomSection", "BOTTOM"],
    ]) {
        code = code.replace(
            `from "../components/money-management/${name}";`,
            `from "${componentStub(label)}";`,
        );
    }
    code = code.replace(
        'from "../features/money-management";',
        `from "${hookStub}";`,
    ).replace(
        'from "../features/money-management/view/moneyManagementViewModel";',
        `from "${viewModelStub}";`,
    );
    const temporary = await mkdtemp(
        join(dirname(fileURLToPath(import.meta.url)), ".mm-page-test-"),
    );
    const output = join(temporary, "MoneyManagementPage.mjs");
    try {
        await writeFile(output, code);
        const module = await import(`${pathToFileURL(output).href}?render`);
        const text = textOf(module.default());
        assert.equal(
            text.replace(/\s+/gu, " ").trim(),
            "HEADER SUMMARY MAIN BOTTOM",
        );
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
});

test("CardShell supports one header, loading, content, and placeholder states", async () => {
    const source = await readSource(
        "../components/money-management/MoneyManagementCardShell.jsx",
    );
    assert.match(source, /mi-panel mm-card/);
    assert.match(source, /mi-panel__title/);
    assert.match(source, /mi-panel__content/);
    assert.match(source, /mm-card__body/);
    assert.equal(source.match(/Coming Soon/g)?.length, 1);
    assert.equal(source.match(/Loading/g)?.length, 1);
    assert.doesNotMatch(source, /button|input|select|textarea|canvas|svg/iu);
});

test("compact status bar and responsive layout retain console primitives", async () => {
    const [header, styles] = await Promise.all([
        readSource(
            "../components/money-management/MoneyManagementHeader.jsx",
        ),
        readSource("../styles/money-management.css"),
    ]);
    assert.match(header, /mm-status-bar/);
    assert.doesNotMatch(header, /Capital Protection/);
    assert.doesNotMatch(header, /mi-header__title|mi-header__subtitle/);
    for (const expected of [
        "MoneyManagementStatusBadge",
        "header.mode",
        "header.connection",
        "MoneyManagementManualRefreshControl",
        "header.updated",
        "refresh.disabledReason",
    ]) {
        assert.match(header, new RegExp(expected));
    }
    for (const reused of [
        "mi-page",
        "mi-panel",
        "mi-panel__title",
        "mi-panel__content",
    ]) {
        assert.match(
            `${await readSource("./MoneyManagementPage.jsx")} ${header} ${await readSource("../components/money-management/MoneyManagementCardShell.jsx")}`,
            new RegExp(reused),
        );
    }
    assert.match(styles, /repeat\(4, minmax\(0, 1fr\)\)/);
    assert.match(styles, /repeat\(2, minmax\(0, 1fr\)\)/);
    assert.match(styles, /@media \(max-width: 1100px\)/);
    assert.doesNotMatch(styles, /#[0-9a-f]{3,8}/iu);
});

test("App and primary navigation register the Money Management route", async () => {
    const [app, navigation] = await Promise.all([
        readSource("../App.jsx"),
        readSource("../components/AppNavigation.jsx"),
    ]);
    assert.match(app, /from "\.\/pages\/MoneyManagementPage"/);
    assert.match(app, /MONEY_MANAGEMENT_PATH = "\/money-management"/);
    assert.match(navigation, /MONEY MANAGEMENT/);
    assert.match(navigation, /MONEY_MANAGEMENT_PATH/);
});
