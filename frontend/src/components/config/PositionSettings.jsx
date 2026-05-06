export default function PositionSettings() {
  return (
    <div className="panel-section">
      <h3>📦 Position Settings</h3>

      <div className="form-group">
        <label>Max Positions</label>
        <input type="number" defaultValue="1" />
      </div>

      <div className="form-group">
        <label>Allow Hedging</label>

        <select>
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>

      <div className="form-group">
        <label>Scale In</label>

        <select>
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>
    </div>
  );
}