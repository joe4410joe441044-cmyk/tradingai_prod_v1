import usePolling from "../../hooks/usePolling";
import { API } from "../../api";

export default function PositionsTable() {

  // --------------------------
  // fetch positions
  // --------------------------
  const fetchPositions = async () => {
    const res = await fetch(API.positions());

    if (!res.ok) {
      throw new Error("Positions API error");
    }

    const data = await res.json();

    return (data?.positions ?? []).slice(-50);
  };

  // --------------------------
  // polling
  // --------------------------
  const {
    data,
    error,
    loading
  } = usePolling(fetchPositions, 5000);

  // --------------------------
  // safety guard
  // --------------------------
  const positions = Array.isArray(data) ? data : [];

  return (
    <div style={{ padding: "10px", border: "1px solid #333" }}>

      <h3>Positions</h3>

      {/* LOADING */}
      {loading && <p>Loading...</p>}

      {/* ERROR */}
      {error && (
        <p style={{ color: "red" }}>
          Fetch error
        </p>
      )}

      {/* EMPTY STATE */}
      {!loading && positions.length === 0 ? (
        <p>No positions</p>
      ) : (
        <ul style={{ maxHeight: "300px", overflowY: "auto" }}>
          {positions.map((p, i) => (
            <li key={`${p.symbol}-${p.side}-${i}`}>
              {p.symbol ?? "?"} | {p.side ?? "?"} | {Number(p.pnl ?? 0).toFixed(2)}
            </li>
          ))}
        </ul>
      )}

    </div>
  );
}