export default function TradeSettings() {
  return (
    <>

      <div className="form-group">
        <label>Symbol</label>

        <select defaultValue="BTCUSDT">
          <option>BTCUSDT</option>
          <option>ETHUSDT</option>
          <option>XRPUSDT</option>
        </select>
      </div>

      <div className="form-group">
        <label>Risk %</label>

        <input
          type="number"
          defaultValue="1"
        />
      </div>

      <div className="form-group">
        <label>SL %</label>

        <input
          type="number"
          defaultValue="1"
        />
      </div>

      <div className="form-group">
        <label>TP %</label>

        <input
          type="number"
          defaultValue="0.5"
        />
      </div>

      <div className="form-group">
        <label>Time Exit</label>

        <input
          type="number"
          defaultValue="3"
        />
      </div>

      <div className="form-group">
        <label>Leverage</label>

        <input
          type="number"
          defaultValue="10"
        />
      </div>

    </>
  );
}