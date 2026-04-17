import { LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { useEffect, useState } from "react";

const API_BASE = "";

export default function AIScoreChart({ symbol }) {
  const [data, setData] = useState([]);

  const load = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/ai/scores?symbol=${symbol}`
      );

      if (!res.ok) {
        throw new Error(`HTTP error: ${res.status}`);
      }

      const json = await res.json();

      // FastAPI縺ｮ繝ｬ繧ｹ繝昴Φ繧ｹ縺九ｉ繧ｹ繧ｳ繧｢蜿門ｾ・
      const score = typeof json?.score === "number" ? json.score : 0;

      setData((prev) => {
        const newPoint = {
          time: new Date().toLocaleTimeString(),
          ai_score: score,
        };

        // 譛譁ｰ50莉ｶ縺縺台ｿ晄戟・医Γ繝｢繝ｪ蟇ｾ遲厄ｼ・
        const updated = [...prev, newPoint];
        return updated.slice(-50);
      });
    } catch (e) {
      console.error("AI score fetch error:", e);

      // 繧ｨ繝ｩ繝ｼ譎ゅ・0縺ｧ蝓九ａ繧・
      setData((prev) => {
        const newPoint = {
          time: new Date().toLocaleTimeString(),
          ai_score: 0,
        };

        const updated = [...prev, newPoint];
        return updated.slice(-50);
      });
    }
  };

  useEffect(() => {
    if (!symbol) return;

    load();
    const t = setInterval(load, 2000);

    return () => clearInterval(t);
  }, [symbol]);

  return (
    <div>
      <h2>AI Score</h2>

      <LineChart width={900} height={300} data={data}>
        <XAxis dataKey="time" />
        <YAxis domain={[0, 1]} />
        <Tooltip />
        <Line type="monotone" dataKey="ai_score" />
      </LineChart>
    </div>
  );
}