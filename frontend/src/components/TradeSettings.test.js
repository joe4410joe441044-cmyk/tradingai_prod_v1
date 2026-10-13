import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithOxc } from "vite";

async function component() {
    const source = await readFile(new URL("./TradeSettings.jsx", import.meta.url), "utf8");
    const { code } = await transformWithOxc(source, "TradeSettings.jsx", {
        jsx: { runtime: "classic" },
    });
    const stub = `const React = { createElement: (type, props, ...children) => ({type, props: {...props, children}}) };
const useState = value => [value, () => {}];`;
    const isolated = code.replace(/import React,\s*\{\s*useState\s*\}\s*from\s*["']react["'];?/, stub);
    return (await import(`data:text/javascript,${encodeURIComponent(isolated)}`)).default;
}
function riskInput(node) {
    if (!node || typeof node !== "object") return null;
    if (node.type === "input" && node.props.max === "5") return node;
    for (const child of (node.props?.children || []).flat(Infinity)) {
        const result = riskInput(child);
        if (result) return result;
    }
    return null;
}
test("Trade Settings represents 2.1 and keeps existing fallback without automatic updates", async () => {
    const Component = await component();
    const changes = [];
    const elevated = riskInput(Component({values: {risk_percent: 2.1}, onChange: value => changes.push(value)}));
    assert.equal(elevated.props.value, 2.1);
    assert.equal(elevated.props.max, "5");
    assert.equal(riskInput(Component({values: {risk_percent: 0.5}})).props.value, 0.5);
    assert.equal(riskInput(Component({})).props.value, 1); // Preserve pre-task legacy fallback.
    assert.deepEqual(changes, []);
    elevated.props.onChange({target: {value: "2.1"}});
    assert.deepEqual(changes, [{risk_percent: 2.1}]);
});
