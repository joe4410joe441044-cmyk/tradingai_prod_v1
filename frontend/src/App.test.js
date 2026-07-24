import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const loadApp = async () => {
    const source = new URL("./App.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".app-integration-test-"));
    const output = join(temporary, "App.mjs");
    const reactStub = moduleUrl("export const useEffect=(callback)=>callback();export const useState=(initializer)=>[typeof initializer==='function'?initializer():initializer,()=>{}]");
    const navigationStub = moduleUrl("export default()=>({type:'nav',props:{children:'NAVIGATION'}})");
    const dashboardStub = moduleUrl("export default()=>({type:'main',props:{children:'DASHBOARD PAGE'}})");
    const marketStub = moduleUrl("export default()=>({type:'main',props:{children:'MARKET INTELLIGENCE PAGE'}})");
    const dashboardMarketProviderStub = moduleUrl(
        "export const DashboardMarketContextProvider=({children})=>children",
    );
    const runtimeStub = moduleUrl("export const startWebSocketRuntime=()=>{}");
    const code = transformed.code.replace('from "react";', `from "${reactStub}";`)
        .replace('from "./components/AppNavigation";', `from "${navigationStub}";`)
        .replace('from "./pages/Dashboard";', `from "${dashboardStub}";`)
        .replace('from "./pages/MarketIntelligencePage";', `from "${marketStub}";`)
        .replace('from "./state/dashboard-market/DashboardMarketContext";', `from "${dashboardMarketProviderStub}";`)
        .replace('from "./runtime/websocketRuntime";', `from "${runtimeStub}";`)
        .replace('import "./App.css";', "");
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?path=${encodeURIComponent(globalThis.window.location.pathname)}`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};

test("App selects Dashboard initially and MARKET INTELLIGENCE by path", async () => {
    globalThis.window = { location: { pathname: "/" } };
    let module = await loadApp();
    assert.match(textOf(module.default()), /DASHBOARD PAGE/);
    assert.doesNotMatch(textOf(module.default()), /MARKET INTELLIGENCE PAGE/);

    globalThis.window = { location: { pathname: "/market-intelligence" } };
    module = await loadApp();
    assert.match(textOf(module.default()), /MARKET INTELLIGENCE PAGE/);
});
