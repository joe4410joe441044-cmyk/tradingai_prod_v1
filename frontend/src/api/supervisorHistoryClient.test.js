import assert from "node:assert/strict"; import test from "node:test";
import {getSupervisorHistory,getSupervisorReplay} from "./supervisorHistoryClient.js";
test("history uses GET filters and cursor",async()=>{let url; const fetchImpl=async u=>(url=u,{ok:true,json:async()=>({events:[],order:"NEWEST_FIRST"})}); await getSupervisorHistory({agentId:"MM_SUPERVISOR",status:"COMPLETED",cursor:"c",fetchImpl}); assert.match(url,/agentId=MM_SUPERVISOR/); assert.match(url,/cursor=c/)});
test("replay requires read-only non-operational envelope",async()=>{const fetchImpl=async()=>({ok:true,json:async()=>({replayMode:"READ_ONLY",operationalEffect:"NONE",providerCalled:false,runtimeCalled:false})}); assert.equal((await getSupervisorReplay("e",{fetchImpl})).replayMode,"READ_ONLY")});
