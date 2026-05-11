export default function PositionSettings({

  config = {},
  setConfig = () => {},

}) {

  return (

    <div className="panel-section">

      <h3>📦 Position Settings</h3>

      {/* MAX POSITIONS */}

      <div className="form-group">

        <label>Max Positions</label>

        <input
          type="number"
          value={
            config.max_positions || 1
          }
          onChange={(e) =>
            setConfig({
              ...config,
              max_positions:
                e.target.value,
            })
          }
        />

      </div>

      {/* ALLOW HEDGING */}

      <div className="form-group">

        <label>Allow Hedging</label>

        <select
          value={
            config.allow_hedging || "OFF"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              allow_hedging:
                e.target.value,
            })
          }
        >

          <option>OFF</option>
          <option>ON</option>

        </select>

      </div>

      {/* SCALE IN */}

      <div className="form-group">

        <label>Scale In</label>

        <select
          value={
            config.scale_in || "OFF"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              scale_in:
                e.target.value,
            })
          }
        >

          <option>OFF</option>
          <option>ON</option>

        </select>

      </div>

    </div>
  );
}