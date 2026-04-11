import { LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { useEffect, useState } from "react";

export default function AIScoreChart({ symbol }) {

  const [data, setData] = useState([]);

  const load = async () => {
    const res = await fetch(`/api/ai/scores?symbol=${symbol}`);
    const json = await res.json();

    setData(
      json.map(d => ({
        time: new Date(d.timestamp * 1000).toLocaleTimeString(),
        ai_score: d.ai_score
      }))
    );
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, []);

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