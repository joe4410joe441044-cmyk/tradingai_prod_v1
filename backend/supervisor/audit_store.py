"""Bounded append-only SQLite store for sanitized Supervisor events."""
from __future__ import annotations
import base64, json, sqlite3, threading
from pathlib import Path
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from .history_contracts import SupervisorHistoryEvent, SupervisorHistoryPage

SUPERVISOR_AUDIT_MAX_EVENTS=5000
SUPERVISOR_AUDIT_MAX_LIMIT=100
DEFAULT_SUPERVISOR_AUDIT_PATH=Path("logs/runtime/supervisor_audit.sqlite3")
_SECRET_MARKERS=("API_KEY","APIKEY","SECRET","TOKEN","PASSWORD","PRIVATE_KEY")
def _safe_question(value):
    text=str(value).strip()
    return "[REDACTED]" if any(marker in text.upper() for marker in _SECRET_MARKERS) else text

class SupervisorAuditStore:
    def __init__(self,path=DEFAULT_SUPERVISOR_AUDIT_PATH,max_events=SUPERVISOR_AUDIT_MAX_EVENTS):
        self.path=Path(path); self.max_events=max_events; self._lock=threading.RLock(); self._initialize()
    def _connect(self): return sqlite3.connect(self.path,timeout=2.0,isolation_level=None)
    def _initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self._connect() as db:
                db.execute("CREATE TABLE IF NOT EXISTS supervisor_events (seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,occurred_at TEXT NOT NULL,agent_id TEXT NOT NULL,event_type TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS supervisor_conversation_turns (seq INTEGER PRIMARY KEY AUTOINCREMENT,message_id TEXT NOT NULL UNIQUE,conversation_id TEXT NOT NULL,agent_id TEXT NOT NULL,requested_at TEXT NOT NULL,responded_at TEXT NOT NULL,question TEXT NOT NULL,answer TEXT NOT NULL,status TEXT NOT NULL,attention TEXT NOT NULL,operational_effect TEXT NOT NULL CHECK(operational_effect='NONE'))")
        except (OSError,sqlite3.Error) as e: raise SupervisorBoundaryError(SupervisorFailureCode.STORE_UNAVAILABLE,"audit store unavailable") from e
    def append(self,event: SupervisorHistoryEvent):
        payload=event.stable_json()
        try:
            with self._lock,self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT COUNT(*) FROM supervisor_events").fetchone()[0]>=self.max_events:
                    db.execute("ROLLBACK"); raise SupervisorBoundaryError(SupervisorFailureCode.STORE_FULL,"audit store full")
                try: db.execute("INSERT INTO supervisor_events(event_id,occurred_at,agent_id,event_type,status,payload) VALUES(?,?,?,?,?,?)",(event.eventId,event.occurredAt.isoformat(),event.agentId.value,event.eventType.value,event.status,payload))
                except sqlite3.IntegrityError as e: db.execute("ROLLBACK"); raise SupervisorBoundaryError(SupervisorFailureCode.DUPLICATE_EVENT,"duplicate event") from e
                db.execute("COMMIT")
        except SupervisorBoundaryError: raise
        except sqlite3.Error as e: raise SupervisorBoundaryError(SupervisorFailureCode.STORE_UNAVAILABLE,"audit store unavailable") from e
    @staticmethod
    def _cursor(seq): return base64.urlsafe_b64encode(str(seq).encode()).decode().rstrip("=")
    @staticmethod
    def _decode(value):
        try: return int(base64.urlsafe_b64decode(value+"="*(-len(value)%4)).decode())
        except Exception as e: raise SupervisorBoundaryError(SupervisorFailureCode.CURSOR_INVALID,"invalid cursor") from e
    def list(self,*,agent_id=None,event_type=None,status=None,limit=20,cursor=None):
        if not 1<=limit<=SUPERVISOR_AUDIT_MAX_LIMIT: raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID,"invalid limit")
        clauses=[]; args=[]
        for col,val in (("agent_id",agent_id),("event_type",event_type),("status",status)):
            if val: clauses.append(f"{col}=?"); args.append(val)
        if cursor: clauses.append("seq<?"); args.append(self._decode(cursor))
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        try:
            with self._connect() as db: rows=db.execute(f"SELECT seq,payload FROM supervisor_events{where} ORDER BY seq DESC LIMIT ?",(*args,limit+1)).fetchall()
            events=tuple(SupervisorHistoryEvent.model_validate_json(r[1]) for r in rows[:limit]); next_cursor=self._cursor(rows[limit-1][0]) if len(rows)>limit else None
            return SupervisorHistoryPage(events=events,nextCursor=next_cursor)
        except SupervisorBoundaryError: raise
        except Exception as e: raise SupervisorBoundaryError(SupervisorFailureCode.READ_FAILED,"audit read failed") from e
    def get(self,event_id):
        try:
            with self._connect() as db: row=db.execute("SELECT payload FROM supervisor_events WHERE event_id=?",(event_id,)).fetchone()
            if not row: raise SupervisorBoundaryError(SupervisorFailureCode.EVENT_NOT_FOUND,"event not found")
            return SupervisorHistoryEvent.model_validate_json(row[0])
        except SupervisorBoundaryError: raise
        except Exception as e: raise SupervisorBoundaryError(SupervisorFailureCode.READ_FAILED,"audit read failed") from e

    def append_conversation_turn(self,request,response):
        values=(response.messageId,request.conversationId,request.agentId.value,request.requestedAt.isoformat(),response.respondedAt.isoformat(),_safe_question(request.message),response.answer,response.status.value,response.humanAttention.value,response.operationalEffect)
        try:
            with self._lock,self._connect() as db: db.execute("INSERT INTO supervisor_conversation_turns(message_id,conversation_id,agent_id,requested_at,responded_at,question,answer,status,attention,operational_effect) VALUES(?,?,?,?,?,?,?,?,?,?)",values)
        except sqlite3.Error as e: raise SupervisorBoundaryError(SupervisorFailureCode.STORE_UNAVAILABLE,"conversation store unavailable") from e



    def _session(self,rows):
        first=rows[0]; last=rows[-1]; title=first[5][:60]+("…" if len(first[5])>60 else "")
        return {"conversationId":first[1],"agentId":first[2],"startedAt":first[3],"lastUpdatedAt":last[4],"title":title,"status":last[7],"attention":last[8],"operationalEffect":"NONE","messages":[item for row in rows for item in ({"role":"USER","text":row[5],"timestamp":row[3]},{"role":"SUPERVISOR","text":row[6],"timestamp":row[4],"status":row[7],"attention":row[8]})]}

    def list_conversation_sessions(self,agent_id,limit=20):
        try:
            with self._connect() as db:
                ids=db.execute("SELECT conversation_id,MAX(seq) latest FROM supervisor_conversation_turns WHERE agent_id=? GROUP BY conversation_id ORDER BY latest DESC LIMIT ?",(agent_id,limit)).fetchall(); sessions=[]
                for conversation_id,_ in ids:
                    rows=db.execute("SELECT seq,conversation_id,agent_id,requested_at,responded_at,question,answer,status,attention,operational_effect FROM supervisor_conversation_turns WHERE agent_id=? AND conversation_id=? ORDER BY seq",(agent_id,conversation_id)).fetchall(); sessions.append(self._session(rows))
                return {"schemaVersion":1,"sessions":sessions,"order":"NEWEST_FIRST","readOnly":True}
        except Exception as e: raise SupervisorBoundaryError(SupervisorFailureCode.READ_FAILED,"conversation history read failed") from e

    def get_conversation_session(self,agent_id,conversation_id):
        with self._connect() as db: rows=db.execute("SELECT seq,conversation_id,agent_id,requested_at,responded_at,question,answer,status,attention,operational_effect FROM supervisor_conversation_turns WHERE agent_id=? AND conversation_id=? ORDER BY seq",(agent_id,conversation_id)).fetchall()
        if not rows: raise SupervisorBoundaryError(SupervisorFailureCode.EVENT_NOT_FOUND,"conversation session not found")
        return self._session(rows)|{"readOnly":True}
