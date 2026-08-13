export async function getSupervisorHistory({agentId,status,cursor,signal,fetchImpl=globalThis.fetch}={}) {
    const query=new URLSearchParams({limit:"20"});
    if(agentId) query.set("agentId",agentId); if(status) query.set("status",status); if(cursor) query.set("cursor",cursor);
    const response=await fetchImpl(`/api/supervisor/history?${query}`,{signal});
    const body=await response.json(); if(!response.ok||!Array.isArray(body.events)) throw new Error(body?.message||"History unavailable."); return body;
}
export async function getSupervisorReplay(eventId,{signal,fetchImpl=globalThis.fetch}={}) {
    const response=await fetchImpl(`/api/supervisor/history/${encodeURIComponent(eventId)}/replay`,{signal});
    const body=await response.json();
    if(!response.ok||body.replayMode!=="READ_ONLY"||body.operationalEffect!=="NONE"||body.providerCalled!==false||body.runtimeCalled!==false) throw new Error(body?.message||"Replay unavailable.");
    return body;
}
