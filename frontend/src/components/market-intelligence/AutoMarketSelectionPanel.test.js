import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

test("MI AUTO card receives authoritative status without a symbol fallback", async () => {
    const source = new URL("./AutoMarketSelectionPanel.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".mi-ams-panel-test-"));
    const output = join(temporary, "AutoMarketSelectionPanel.mjs");
    const cardStub = moduleUrl("export default function Card(props){return {type:'card',props}}");
    const providerStub = moduleUrl("export const useMarketIntelligence=()=>globalThis.__MI_AMS_CONTEXT__");
    const apiStub = moduleUrl("export const API={paperAutoReselect:()=>'/api/runtime/paper-auto/reselect'}");
    const authStub = moduleUrl("export const authenticatedControlRequest=async()=>({ok:true})");
    const modelStub = moduleUrl("export const deriveReselectBlocker=(botStatus)=>({disabled:Boolean(botStatus?.position_active),reason:botStatus?.position_active?'POSITION_OPEN':null})");
    const reactStub = moduleUrl("export const useState=(initial)=>[initial,()=>{}]");
    const code = transformed.code
        .replace('from "../AutoMarketSelectionCard";', `from "${cardStub}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`)
        .replace('from "../../api/index.js";', `from "${apiStub}";`)
        .replace('from "../../features/auth/operatorAuth.js";', `from "${authStub}";`)
        .replace('from "../../features/auto-market-selection/autoMarketSelectionModel.js";', `from "${modelStub}";`)
        .replace('from "react";', `from "${reactStub}";`);
    try {
        await writeFile(output, code);
        const { default: Panel } = await import(`${pathToFileURL(output).href}?test=ams-panel`);
        const status = {
            selectionMode: "AUTO",
            activeSymbol: "ETHUSDT",
            requestedSymbol: "XRPUSDTM",
            autoRuntime: { runtimeState: "READY", status: "COMPLETED" },
        };
        globalThis.__MI_AMS_CONTEXT__ = { autoMarketSelectionStatus: status, botStatus: {} };
        const element = Panel();
        assert.equal(element.props.status, status);
        assert.equal(element.props.status.activeSymbol, "ETHUSDT");
        assert.equal(element.props.status.requestedSymbol, "XRPUSDTM");
        assert.equal(element.props.collapsible, true);
        assert.equal(element.props.reselectDisabled, false);
        assert.equal(element.props.reselectReason, null);
        assert.equal(typeof element.props.onReselect, "function");

        globalThis.__MI_AMS_CONTEXT__ = {
            autoMarketSelectionStatus: status,
            botStatus: { position_active: true },
        };
        const blocked = Panel();
        assert.equal(blocked.props.reselectDisabled, true);
        assert.equal(blocked.props.reselectReason, "POSITION_OPEN");
    } finally {
        delete globalThis.__MI_AMS_CONTEXT__;
        await rm(temporary, { recursive: true, force: true });
    }
});
