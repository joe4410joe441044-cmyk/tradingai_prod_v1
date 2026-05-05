export default function StrategyControl({ values, onChange }) {

  const handle = (key, value) => {
    if (onChange) onChange({ [key]: value });
  };

  return (
    <div style={{ background: "#111", padding: 12, borderRadius: 12 }}>
      <h3>🧠 Strategy</h3>

      <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        value={values.mode}
        onChange={(e) => handle("mode", parseFloat(e.target.value))}
      />

      <input
        placeholder="Gamma"
        value={values.gamma}
        onChange={(e) => handle("gamma", parseFloat(e.target.value))}
      />

      <input
        placeholder="Delta"
        value={values.delta_buy}
        onChange={(e) => handle("delta_buy", parseFloat(e.target.value))}
      />

      <input
        placeholder="Sigma"
        value={values.sigma}
        onChange={(e) => handle("sigma", parseFloat(e.target.value))}
      />

      <input
        placeholder="Edge"
        value={values.edge}
        onChange={(e) => handle("edge", parseFloat(e.target.value))}
      />
    </div>
  );
}