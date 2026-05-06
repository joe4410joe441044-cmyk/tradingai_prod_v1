export default function ExecutionPanel() {
  return (
    <div className="panel-card execution-panel">

      {/* HEADER */}
      <div className="panel-header">
        <h3>⚡ EXECUTION</h3>
      </div>

      {/* STATUS CARD */}
      <div className="execution-status-card">

        <div className="status-row">
          <span className="label">MODE</span>
          <span className="value">🟢 SAFE</span>
        </div>

        <div className="status-row">
          <span className="label">DRY RUN</span>
          <span className="value danger">🔴 OFF (REAL)</span>
        </div>

        <div className="status-row">
          <span className="label">STATUS</span>
          <span className="value stopped">🔴 STOPPED</span>
        </div>

      </div>

      {/* BUTTONS */}
      <div className="execution-buttons">

        <button className="start-btn">
          ▶ START
        </button>

        <button className="stop-btn">
          ■ STOP
        </button>

      </div>

    </div>
  );
}