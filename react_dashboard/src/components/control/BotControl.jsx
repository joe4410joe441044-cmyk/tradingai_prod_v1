export default function BotControl({ onStart, onStop }) {
  return (
    <div style={{ marginTop: "20px" }}>
      <h3>Bot Control</h3>

      <button onClick={onStart}>Start</button>
      <button onClick={onStop} style={{ marginLeft: "10px" }}>
        Stop
      </button>
    </div>
  );
}