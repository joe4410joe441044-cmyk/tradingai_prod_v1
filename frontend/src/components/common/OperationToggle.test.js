import assert from "node:assert/strict";
import {
    mkdtemp,
    readFile,
    rm,
    writeFile,
} from "node:fs/promises";
import {
    dirname,
    join,
} from "node:path";
import test from "node:test";
import {
    fileURLToPath,
    pathToFileURL,
} from "node:url";

import {
    transformWithOxc,
} from "vite";

let operationTogglePromise;

const loadOperationToggle = async () => {
    const sourceUrl = new URL("./OperationToggle.jsx", import.meta.url);
    const sourcePath = fileURLToPath(sourceUrl);
    const source = await readFile(sourceUrl, "utf8");
    const transformed = await transformWithOxc(
        source,
        sourcePath,
    );
    const tempDir = await mkdtemp(
        join(dirname(sourcePath), ".operation-toggle-test-")
    );
    const tempFile = join(tempDir, "OperationToggle.mjs");

    try {
        await writeFile(tempFile, transformed.code);

        const module = await import(
            `${pathToFileURL(tempFile).href}?t=${Date.now()}`
        );

        return module.default;
    } finally {
        await rm(
            tempDir,
            {
                force: true,
                recursive: true,
            },
        );
    }
};

const getOperationToggle = () => {
    if (!operationTogglePromise) {
        operationTogglePromise = loadOperationToggle();
    }

    return operationTogglePromise;
};

const childrenOf = (
    element
) => {
    if (!element || typeof element !== "object") {
        return [];
    }

    const children = element.props?.children;

    if (children === undefined || children === null) {
        return [];
    }

    return Array.isArray(children)
        ? children
        : [children];
};

const findElement = (
    element,
    predicate
) => {
    if (
        element
        && typeof element === "object"
        && predicate(element)
    ) {
        return element;
    }

    for (const child of childrenOf(element)) {
        const match = findElement(child, predicate);

        if (match) {
            return match;
        }
    }

    return null;
};

const collectText = (
    value
) => {
    if (value === null || value === undefined || value === false) {
        return "";
    }

    if (typeof value === "string" || typeof value === "number") {
        return String(value);
    }

    if (Array.isArray(value)) {
        return value.map(collectText).join(" ");
    }

    if (typeof value === "object") {
        return collectText(value.props?.children);
    }

    return "";
};

const renderToggle = async (
    props
) => {
    const OperationToggle = await getOperationToggle();
    const calls = [];
    const element = OperationToggle({
        label: "LOOP",
        onChange: (value) => calls.push(value),
        ...props,
    });
    const button = findElement(
        element,
        (candidate) => candidate.type === "button"
    );

    assert.ok(button);

    return {
        button,
        calls,
        element,
        text: collectText(element),
    };
};

test("OperationToggle exposes unchecked switch semantics and requests true once", async () => {
    const {
        button,
        calls,
        text,
    } = await renderToggle({
        checked: false,
    });

    assert.equal(button.props.type, "button");
    assert.equal(button.props.role, "switch");
    assert.equal(button.props["aria-checked"], false);
    assert.equal(button.props["aria-label"], "LOOP");
    assert.equal(button.props.disabled, false);
    assert.equal(button.props.onKeyDown, undefined);
    assert.match(text, /LOOP/);
    assert.match(text, /OFF/);
    assert.match(text, /ON/);

    button.props.onClick();

    assert.deepEqual(calls, [true]);
    assert.equal(button.props["aria-checked"], false);
});

test("OperationToggle exposes checked switch semantics and requests false once", async () => {
    const {
        button,
        calls,
    } = await renderToggle({
        checked: true,
    });

    assert.equal(button.props["aria-checked"], true);

    button.props.onClick();

    assert.deepEqual(calls, [false]);
    assert.equal(button.props["aria-checked"], true);
});

test("OperationToggle does not notify when disabled", async () => {
    const {
        button,
        calls,
    } = await renderToggle({
        checked: false,
        disabled: true,
    });

    assert.equal(button.props.disabled, true);

    button.props.onClick();

    assert.deepEqual(calls, []);
});

test("OperationToggle does not notify while loading and exposes busy state", async () => {
    const {
        button,
        calls,
        text,
    } = await renderToggle({
        checked: false,
        loading: true,
    });

    assert.equal(button.props.disabled, true);
    assert.equal(button.props["aria-busy"], "true");
    assert.match(text, /PROCESSING/);

    button.props.onClick();

    assert.deepEqual(calls, []);
});

test("OperationToggle uses explicit ariaLabel over visible label", async () => {
    const {
        button,
        text,
    } = await renderToggle({
        ariaLabel: "Toggle Auto Trade",
        checked: true,
        label: "AUTO TRADE",
    });

    assert.equal(button.props["aria-label"], "Toggle Auto Trade");
    assert.match(text, /AUTO TRADE/);
});
