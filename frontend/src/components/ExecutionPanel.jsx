export default function ExecutionPanel() {
  return (
    <div className="card">
      <h2>Execution</h2>

      <button>START</button>
      <button>STOP</button>

      <div>Mode: PAPER</div>

      <hr />

      <div>DRY RUN: ON (PAPER)</div>

      <button>Toggle Dry Run</button>
    </div>
  );
}