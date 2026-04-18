import { useState, useEffect } from "react";
import { API } from "../../api/index"; // ← 修正

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

      // 安全化
      setLogs(data?.logs ?? data ?? []);
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
            <li key={i}>
              {typeof l === "string" ? l : JSON.stringify(l)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}