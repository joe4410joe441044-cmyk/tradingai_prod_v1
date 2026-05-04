import { useEffect, useRef, useState } from "react";

export default function useWebSocket(url) {
  const wsRef = useRef(null);
  const [data, setData] = useState({});

  useEffect(() => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("🟢 WS CONNECTED");
    };

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);

        // 🔥 完全置き換え（これが最重要）
        setData(parsed);

      } catch (e) {
        console.error("WS PARSE ERROR", e);
      }
    };

    ws.onclose = () => {
      console.log("🔴 WS CLOSED");
    };

    ws.onerror = (e) => {
      console.error("WS ERROR", e);
    };

    return () => {
      ws.close();
    };
  }, [url]);

  return data;
}