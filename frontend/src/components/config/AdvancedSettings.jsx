export default function AdvancedSettings({

  config = {},
  setConfig = () => {},

}) {

  return (

    <div className="panel-section">

      <h3>📦 Advanced</h3>

      {/* DRY RUN */}

      <div className="form-group">

        <label>Dry Run</label>

        <select
          value={
            config.dry_run || "ON"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              dry_run:
                e.target.value,
            })
          }
        >

          <option>ON</option>
          <option>OFF</option>

        </select>

      </div>

      {/* PARTIAL TP */}

      <div className="form-group">

        <label>Partial TP</label>

        <select
          value={
            config.partial_tp || "OFF"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              partial_tp:
                e.target.value,
            })
          }
        >

          <option>OFF</option>
          <option>ON</option>

        </select>

      </div>

      {/* BREAK EVEN */}

      <div className="form-group">

        <label>Break Even</label>

        <select
          value={
            config.break_even || "OFF"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              break_even:
                e.target.value,
            })
          }
        >

          <option>OFF</option>
          <option>ON</option>

        </select>

      </div>

      {/* TRAILING STOP */}

      <div className="form-group">

        <label>Trailing Stop</label>

        <select
          value={
            config.trailing_stop || "OFF"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              trailing_stop:
                e.target.value,
            })
          }
        >

          <option>OFF</option>
          <option>ON</option>

        </select>

      </div>

      {/* TIME LOCK */}

      <div className="form-group">

        <label>Time Lock</label>

        <input
          type="number"
          value={
            config.time_lock || 3
          }
          onChange={(e) =>
            setConfig({
              ...config,
              time_lock:
                e.target.value,
            })
          }
        />

      </div>

    </div>
  );
}