import { useState, useEffect } from "react";
import { API } from "../api";

export default function PositionsTable() {
  const [positions, setPositions] = useState([]);

  const fetchData = async () => {
    try {
      const res = await fetch(API.positions());

      if (!res.ok) {
        console.error(await res.text());
        return;
      }

      const data = await res.json();

      setPositions(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error(err);
      setPositions([]);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div>
      <h3>Positions</h3>

      {positions.length === 0 ? (
        <p>No positions</p>
      ) : (
        <ul>
          {positions.map((p, i) => (
            <li key={i}>
              {p.symbol} | {p.side} | {p.pnl}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
