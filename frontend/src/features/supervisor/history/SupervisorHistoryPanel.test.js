import assert from "node:assert/strict"; import test from "node:test"; import {readFile} from "node:fs/promises";
const source=await readFile(new URL("./SupervisorHistoryPanel.jsx",import.meta.url),"utf8");
test("history has loading empty error filters pagination and replay",()=>{for(const value of ["Loading…","No Supervisor history","role=\"alert\"","MASTER_SUPERVISOR","MM_SUPERVISOR","Older","Newer","View replay"]) assert.ok(source.includes(value)); assert.doesNotMatch(source,/JSON\.stringify|POST|PUT|DELETE/)});
