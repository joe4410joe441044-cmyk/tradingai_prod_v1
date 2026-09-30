import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { transformWithOxc } from "vite";

export async function compilePositionModules(temporary) {
    const base = new URL("../src/components/runtime/", import.meta.url);
    const model = new URL("accountRuntimeModel.js", base).href;
    for (const name of ["PositionCardFields", "CurrentPositionCard", "LastPositionEventCard"]) {
        const source = new URL(`${name}.jsx`, base);
        const { code } = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
        await writeFile(join(temporary, `${name}.mjs`), code
            .replaceAll('"./accountRuntimeModel.js"', JSON.stringify(model))
            .replaceAll('"./PositionCardFields.jsx"', '"./PositionCardFields.mjs"'));
    }
}
