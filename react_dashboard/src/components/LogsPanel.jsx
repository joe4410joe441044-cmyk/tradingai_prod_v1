import { useState, useEffect } from "react";
import { API } from "../api";

export default function LogsPanel() {
  const [logs, setLogs] = useState([]);

  const fetchData = async () => {
    try {
      const res = await fetch(API.logs());

      if (!res.ok) {
        console.error(await res.text());
        return;
      }

      const data = await res.json();

      setLogs(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error(err);
      setLogs([]);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <h3>Logs</h3>

      {logs.length === 0 ? (
        <p>No logs</p>
      ) : (
        <ul>
          {logs.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}