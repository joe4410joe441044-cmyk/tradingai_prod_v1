export default function SupervisorReplayPanel({replay,onClose}) {
    if(!replay) return null;
    return <section className="supervisor-replay" aria-label="Supervisor replay">
        <div><strong>REPLAY — READ ONLY</strong><button type="button" onClick={onClose}>Close</button></div>
        <p>This does not re-run the Agent or change TradingAI.</p>
        <dl><dt>Status</dt><dd>{replay.status}</dd><dt>Summary</dt><dd>{replay.summary}</dd><dt>Freshness</dt><dd>{replay.freshness||"UNKNOWN"}</dd><dt>Failure</dt><dd>{replay.failureCode||"NONE"}</dd><dt>Operational effect</dt><dd>NONE</dd><dt>Provider called</dt><dd>NO</dd><dt>Runtime called</dt><dd>NO</dd></dl>
    </section>;
}
