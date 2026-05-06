export default function AdvancedSettings() {
  return (
    <>

      <div className="form-group">
        <label>Dry Run</label>

        <select defaultValue="ON">
          <option>ON</option>
          <option>OFF</option>
        </select>
      </div>

      <div className="form-group">
        <label>Partial TP</label>

        <select defaultValue="OFF">
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>

      <div className="form-group">
        <label>Break Even</label>

        <select defaultValue="OFF">
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>

      <div className="form-group">
        <label>Trailing Stop</label>

        <select defaultValue="OFF">
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>

      <div className="form-group">
        <label>Time Lock</label>

        <select defaultValue="OFF">
          <option>OFF</option>
          <option>ON</option>
        </select>
      </div>

    </>
  );
}