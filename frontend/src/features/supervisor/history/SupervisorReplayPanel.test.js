import assert from "node:assert/strict"; import test from "node:test"; import {readFile} from "node:fs/promises";
const source=await readFile(new URL("./SupervisorReplayPanel.jsx",import.meta.url),"utf8");
test("replay explicitly states read-only and no re-execution",()=>{assert.match(source,/REPLAY — READ ONLY/); assert.match(source,/does not re-run/); assert.match(source,/Operational effect/); assert.match(source,/Provider called/); assert.doesNotMatch(source,/fetch\(|mutation|submit/)});
