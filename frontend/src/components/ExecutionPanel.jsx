export default function ExecutionPanel() {
  return (
    <div className="execution-panel">

      <div className="execution-buttons">
        <button>▶ START</button>

        <button>■ STOP</button>
      </div>

      <div className="execution-status">

        <div>MODE: SAFE / NORMAL / AGG</div>

        <div>DRY RUN: OFF (REAL)</div>

        <div>STATUS: 🟢 RUNNING</div>

      </div>

    </div>
  );
}