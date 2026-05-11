export default function TradeSettings({

  config,
  setConfig,

}) {

  return (

    <div>

      {/* ========================= */}
      {/* TITLE */}
      {/* ========================= */}

      <div className="panel-header">

        <h3>
          🟢 Trade Settings
        </h3>

      </div>

      {/* ========================= */}
      {/* SYMBOL */}
      {/* ========================= */}

      <div className="form-group">

        <label>
          Symbol
        </label>

        <select
          value={config.symbol}
          onChange={(e) =>
            setConfig({
              ...config,
              symbol: e.target.value,
            })
          }
        >

          <option value="BTCUSDT">
            BTCUSDT
          </option>

          <option value="ETHUSDT">
            ETHUSDT
          </option>

          <option value="XRPUSDT">
            XRPUSDT
          </option>

        </select>

      </div>

      {/* ========================= */}
      {/* RISK */}
      {/* ========================= */}

      <div className="form-group">

        <label>
          Risk %
        </label>

        <input
          type="number"
          value={config.risk_percent}
          onChange={(e) =>
            setConfig({
              ...config,
              risk_percent: e.target.value,
            })
          }
        />

      </div>

      {/* ========================= */}
      {/* SL */}
      {/* ========================= */}

      <div className="form-group">

        <label>
          SL %
        </label>

        <input
          type="number"
          value={config.sl_percent}
          onChange={(e) =>
            setConfig({
              ...config,
              sl_percent: e.target.value,
            })
          }
        />

      </div>

      {/* ========================= */}
      {/* TP */}
      {/* ========================= */}

      <div className="form-group">

        <label>
          TP %
        </label>

        <input
          type="number"
          value={config.tp_percent}
          onChange={(e) =>
            setConfig({
              ...config,
              tp_percent: e.target.value,
            })
          }
        />

      </div>

      {/* ========================= */}
      {/* TIME EXIT */}
      {/* ========================= */}

      <div className="form-group">

        <label>
          Time Exit
        </label>

        <input
          type="number"
          value={config.time_exit || 3}
          onChange={(e) =>
            setConfig({
              ...config,
              time_exit: e.target.value,
            })
          }
        />

      </div>

      {/* ========================= */}
      {/* LEVERAGE */}
      {/* ========================= */}

      <div className="form-group">

        <label>
          Leverage
        </label>

        <input
          type="number"
          value={config.leverage}
          onChange={(e) =>
            setConfig({
              ...config,
              leverage: e.target.value,
            })
          }
        />

      </div>

    </div>
  );
}