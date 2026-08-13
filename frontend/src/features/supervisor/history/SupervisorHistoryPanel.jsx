import {useEffect,useRef,useState} from "react";
import {getSupervisorHistory,getSupervisorReplay} from "../../../api/supervisorHistoryClient";
import SupervisorReplayPanel from "./SupervisorReplayPanel";
export default function SupervisorHistoryPanel(){
 const [agent,setAgent]=useState(""); const [status,setStatus]=useState(""); const [page,setPage]=useState(null); const [loading,setLoading]=useState(true); const [error,setError]=useState(""); const [replay,setReplay]=useState(null); const [currentCursor,setCurrentCursor]=useState(null); const [newer,setNewer]=useState([]); const controller=useRef();
 const load=(cursor=null)=>{controller.current?.abort(); const current=new AbortController(); controller.current=current; setLoading(true); setError(""); getSupervisorHistory({agentId:agent,status,cursor,signal:current.signal}).then(v=>{if(!current.signal.aborted)setPage(v)}).catch(e=>{if(!current.signal.aborted)setError(e.message)}).finally(()=>{if(!current.signal.aborted)setLoading(false)});};
 useEffect(()=>{setCurrentCursor(null);setNewer([]);load(); return()=>controller.current?.abort()},[agent,status]);
 const older=()=>{setNewer(values=>[...values,currentCursor]);setCurrentCursor(page.nextCursor);load(page.nextCursor)};
 const newerPage=()=>{const target=newer[newer.length-1]??null;setNewer(values=>values.slice(0,-1));setCurrentCursor(target);load(target)};
 const openReplay=(id)=>{setError(""); getSupervisorReplay(id).then(setReplay).catch(e=>setError(e.message))};
 return <section className="supervisor-history" aria-labelledby="supervisor-history-heading"><h3 id="supervisor-history-heading">Decision / Change History</h3>
 <div className="supervisor-history__filters"><label>Agent <select value={agent} onChange={e=>setAgent(e.target.value)}><option value="">ALL</option><option value="MASTER_SUPERVISOR">MASTER</option><option value="MM_SUPERVISOR">MM</option></select></label><label>Status <select value={status} onChange={e=>setStatus(e.target.value)}><option value="">ALL</option><option value="COMPLETED">SUCCESS</option><option value="FAILED_CLOSED">FAILED</option><option value="UNAVAILABLE">UNAVAILABLE</option></select></label></div>
 <div aria-live="polite">{loading&&"Loading…"}</div>{error&&<p role="alert">{error}</p>}{!loading&&page?.events.length===0&&<p>No Supervisor history.</p>}
 <ul>{page?.events.map(event=><li key={event.eventId}><time>{event.occurredAt}</time><strong>{event.agentId}</strong><span>{event.eventType} · {event.status}</span><p>{event.summary}</p><span>Attention: {event.humanAttention||"UNKNOWN"}</span><button type="button" aria-expanded={replay?.sourceEventId===event.eventId} onClick={()=>openReplay(event.eventId)}>View replay</button></li>)}</ul>
 {newer.length>0&&<button type="button" onClick={newerPage}>Newer</button>} {page?.nextCursor&&<button type="button" onClick={older}>Older</button>}<SupervisorReplayPanel replay={replay} onClose={()=>setReplay(null)}/></section>;
}
