import { useEffect, useState } from "react";

export default function useBotData() {

  const [data, setData] = useState({
    balance: 0,
    equity: 0,
    pnl: 0,
    price: 0,
    status: "STOPPED",
    symbol: null
  });

  useEffect(() => {

    let ws;
    let reconnectTimer;

    const connect = () => {

      // ✅ WebSocket URL（最優先で定義）
      const wsUrl = "ws://35.194.104.74:8001/ws";

      console.log("🌐 WS CONNECT:", wsUrl);

      // ✅ WebSocket生成
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("🟢 WS CONNECTED");
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          console.log("📡 WS DATA:", msg);

          setData(prev => ({
            ...prev,
            ...msg
          }));

        } catch (err) {
          console.error("❌ WS PARSE ERROR:", err);
        }
      };

      ws.onerror = (err) => {
        console.error("🔴 WS ERROR", err);
      };

      ws.onclose = (e) => {
        console.warn("🔴 WS CLOSED", e.code);

        // 🔥 自動再接続
        reconnectTimer = setTimeout(() => {
          console.log("♻️ WS RECONNECT...");
          connect();
        }, 2000);
      };
    };

    connect();

    return () => {
      if (ws) ws.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };

  }, []);

  return data;
}