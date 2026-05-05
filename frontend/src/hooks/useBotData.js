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

      // ✅ 本番対応（超重要）
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const wsUrl = `${protocol}://${window.location.host}/ws`;

      console.log("🌐 WS CONNECT:", wsUrl);

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