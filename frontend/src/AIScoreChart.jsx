import { LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { useMemo } from "react";
import usePolling from "./hooks/usePolling";
import { API } from "./api";

export default function AIScoreChart({ symbol }) {

  // --------------------------
  // API fetch（純関数化）
  // --------------------------
  const fetchScore = async () => {
    const res = await fetch(API.scores(symbol));

    if (!res.ok) {
      throw new Error(`HTTP error: ${res.status}`);
    }

    const json = await res.json();

    return {
      time: new Date().toLocaleTimeString(),
      ai_score: typeof json?.score === "number" ? json.score : 0,
    };
  };

  // --------------------------
  // polling（完全統一）
  // --------------------------
  const { data: point } = usePolling(fetchScore, 2000);

  // --------------------------
  // chart data（蓄積）
  // --------------------------
  const data = useMemo(() => {
    if (!point) return [];

    return [point]; // 単発取得
  }, [point]);

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