export default function EmergencySettings({

  config = {},
  setConfig = () => {},

}) {

  return (

    <div className="panel-section">

      <h3>🚨 Emergency Settings</h3>

      {/* KILL SWITCH */}

      <div className="form-group">

        <label>Kill Switch</label>

        <select
          value={
            config.kill_switch || "SAFE"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              kill_switch:
                e.target.value,
            })
          }
        >

          <option>SAFE</option>
          <option>OFF</option>

        </select>

      </div>

      {/* MAX DAILY LOSS */}

      <div className="form-group">

        <label>Max Daily Loss</label>

        <input
          type="number"
          value={
            config.max_daily_loss || 50
          }
          onChange={(e) =>
            setConfig({
              ...config,
              max_daily_loss:
                e.target.value,
            })
          }
        />

      </div>

      {/* MAX TRADES */}

      <div className="form-group">

        <label>Max Trades</label>

        <input
          type="number"
          value={
            config.max_trades || 20
          }
          onChange={(e) =>
            setConfig({
              ...config,
              max_trades:
                e.target.value,
            })
          }
        />

      </div>

      {/* AUTO STOP ON DD */}

      <div className="form-group">

        <label>Auto Stop on DD</label>

        <select
          value={
            config.auto_stop_dd || "ON"
          }
          onChange={(e) =>
            setConfig({
              ...config,
              auto_stop_dd:
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