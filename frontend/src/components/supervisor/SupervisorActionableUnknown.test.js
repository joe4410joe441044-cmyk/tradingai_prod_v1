import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
const source = await readFile(new URL("./SupervisorActionableUnknown.jsx", import.meta.url), "utf8");
test("shared UNKNOWN presentation includes every human-actionable field and no controls", () => {
 for (const heading of ["Unknown / Not Available", "Reason", "Missing Information", "Next Step", "Decision Impact"]) assert.match(source, new RegExp(heading));
 assert.doesNotMatch(source, /button|onClick|fetch|POST/);
});
