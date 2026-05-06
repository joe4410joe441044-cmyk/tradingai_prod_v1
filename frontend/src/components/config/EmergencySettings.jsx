export default function EmergencySettings() {
  return (
    <>

      <div className="form-group">
        <label>Kill Switch</label>

        <select>
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>

      <div className="form-group">
        <label>Max Daily Loss</label>

        <input
          type="number"
          defaultValue="50"
        />
      </div>

      <div className="form-group">
        <label>Max Trades</label>

        <input
          type="number"
          defaultValue="20"
        />
      </div>

      <div className="form-group">
        <label>Auto Stop on DD</label>

        <select>
          <option>ON</option>
          <option>OFF</option>
        </select>
      </div>

    </>
  );
}