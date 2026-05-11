export default function ExecutionSettings({

  config = {},
  setConfig = () => {},

}) {

  return (

    <div className="panel-section">

      <h3>⚙️ Execution Settings</h3>

      {/* COOLDOWN */}

      <div className="form-group">

        <label>Cooldown</label>

        <input
          type="number"
          value={config.cooldown || 2}
          onChange={(e) =>
            setConfig({
              ...config,
              cooldown: e.target.value,
            })
          }
        />

      </div>

      {/* MAX ENTRIES */}

      <div className="form-group">

        <label>Max Entries/min</label>

        <input
          type="number"
          value={config.max_entries || 5}
          onChange={(e) =>
            setConfig({
              ...config,
              max_entries: e.target.value,
            })
          }
        />

      </div>

      {/* ONE SIGNAL ONLY */}

      <div className="form-group">

        <label>One Signal Only</label>

        <select
          value={
            config.one_signal_only || "ON"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              one_signal_only:
                e.target.value,
            })
          }
        >

          <option>ON</option>
          <option>OFF</option>

        </select>

      </div>

      {/* RE-ENTRY DELAY */}

      <div className="form-group">

        <label>Re-entry Delay</label>

        <input
          type="number"
          value={
            config.reentry_delay || 3
          }
          onChange={(e) =>
            setConfig({
              ...config,
              reentry_delay:
                e.target.value,
            })
          }
        />

      </div>

      {/* SIGNAL LOCK */}

      <div className="form-group">

        <label>Signal Lock</label>

        <select
          value={
            config.signal_lock || "ON"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              signal_lock:
                e.target.value,
            })
          }
        >

          <option>ON</option>
          <option>OFF</option>

        </select>

      </div>

    </div>
  );
}