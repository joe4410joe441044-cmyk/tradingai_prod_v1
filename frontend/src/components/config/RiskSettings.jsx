export default function RiskSettings() {
  return (
    <>

      <div className="form-group">
        <label>Max DD %</label>

        <input
          type="number"
          defaultValue="10"
        />
      </div>

      <div className="form-group">
        <label>Max Loss Streak</label>

        <input
          type="number"
          defaultValue="3"
        />
      </div>

      <div className="form-group">
        <label>Max Position</label>

        <input
          type="number"
          defaultValue="100"
        />
      </div>

    </>
  );
}