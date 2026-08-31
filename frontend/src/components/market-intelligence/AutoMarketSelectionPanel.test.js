import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

test("MI AUTO card receives authoritative status without a symbol fallback", async () => {
    const source = new URL("./AutoMarketSelectionPanel.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".mi-ams-panel-test-"));
    const output = join(temporary, "AutoMarketSelectionPanel.mjs");
    const cardStub = "data:text/javascript,export default function Card(props){return {type:'card',props}}";
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_AMS_CONTEXT__";
    const code = transformed.code
        .replace('from "../AutoMarketSelectionCard";', `from "${cardStub}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`);
    try {
        await writeFile(output, code);
        const { default: Panel } = await import(`${pathToFileURL(output).href}?test=ams-panel`);
        const status = {
            selectionMode: "AUTO",
            activeSymbol: "ETHUSDT",
            requestedSymbol: "XRPUSDTM",
            autoRuntime: { runtimeState: "READY", status: "COMPLETED" },
        };
        globalThis.__MI_AMS_CONTEXT__ = { autoMarketSelectionStatus: status };
        const element = Panel();
        assert.equal(element.props.status, status);
        assert.equal(element.props.status.activeSymbol, "ETHUSDT");
        assert.equal(element.props.status.requestedSymbol, "XRPUSDTM");
        assert.equal(element.props.collapsible, true);
    } finally {
        delete globalThis.__MI_AMS_CONTEXT__;
        await rm(temporary, { recursive: true, force: true });
    }
});
