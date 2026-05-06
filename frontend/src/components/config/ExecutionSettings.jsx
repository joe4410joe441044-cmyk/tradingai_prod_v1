export default function ExecutionSettings() {
  return (
    <div className="panel-section">
      <h3>⚙️ Execution Settings</h3>

      <div className="form-group">
        <label>Cooldown</label>
        <input type="number" defaultValue="2" />
      </div>

      <div className="form-group">
        <label>Max Entries/min</label>
        <input type="number" defaultValue="5" />
      </div>

      <div className="form-group">
        <label>One Signal Only</label>
        <select>
          <option>ON</option>
          <option>OFF</option>
        </select>
      </div>

      <div className="form-group">
        <label>Re-entry Delay</label>
        <input type="number" defaultValue="3" />
      </div>

      <div className="form-group">
        <label>Signal Lock</label>
        <select>
          <option>ON</option>
          <option>OFF</option>
        </select>
      </div>
    </div>
  );
}