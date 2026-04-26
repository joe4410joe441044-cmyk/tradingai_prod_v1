import { useEffect, useState, useRef } from "react";

export default function useAIStream() {
  const [events, setEvents] = useState([]);
  const wsRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws");
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("✅ WS CONNECTED");
    };

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        setEvents((prev) => [data, ...prev].slice(0, 100));
      } catch (e) {
        console.error("WS PARSE ERROR", e);
      }
    };

    ws.onerror = (err) => {
      console.error("WS ERROR", err);
    };

    ws.onclose = () => {
      console.log("WS CLOSED");
    };

    return () => ws.close();
  }, []);

  return events;
}