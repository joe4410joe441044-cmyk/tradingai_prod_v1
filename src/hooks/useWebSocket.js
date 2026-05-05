import { useEffect, useRef, useState } from "react";

export default function useWebSocket() {
  const wsRef = useRef(null);
  const [data, setData] = useState({});

  useEffect(() => {

    // ✅ URLを先に定義
    const wsUrl = `${window.location.origin.replace("http", "ws")}/ws/`;

    console.log("🌐 WS CONNECT:", wsUrl);

    // ✅ WebSocket生成
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("🟢 WS CONNECTED");
    };

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);

        // 🔥 完全置き換え
        setData(parsed);

      } catch (e) {
        console.error("WS PARSE ERROR", e);
      }
    };

    ws.onclose = (e) => {
      console.log("🔴 WS CLOSED", e.code);
    };

    ws.onerror = (e) => {
      console.error("WS ERROR", e);
    };

    return () => {
      ws.close();
    };

  }, []);

  return data;
}