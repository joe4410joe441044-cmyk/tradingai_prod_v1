// src/components/SampleBotControl.jsx
import React, { useState } from "react";

const API_BASE = "";

export default function SampleBotControl() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const checkBotStatus = async () => {
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/bot_status`);

      if (!res.ok) {
        throw new Error("API Error");
      }

      const data = await res.json();

      // 陞ｳ莨夲ｽｿ・ｽE邵ｺ・ｫ隰ｨ・ｴ陟厄ｽ｢繝ｻ・ｽE繝ｻ・ｽ陞｢鄙ｫ・檎ｸｺ・ｦ邵ｺ・ｦ郢ｧ繧願ｪ邵ｺ・｡邵ｺ・ｪ邵ｺ繝ｻ繝ｻ・ｽ繝ｻ・ｽE
      setStatus({
        running: data?.running ?? false,
        raw: data,
      });

    } catch (err) {
      console.error("Bot status error:", err);
      setStatus({ error: "隰暦ｽ･驍ｯ螢ｼ・､・ｱ隰ｨ繝ｻ/ API隴幢ｽｪ隘搾ｽｷ陷阪・ });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "20px", border: "1px solid #ccc", width: "320px" }}>
      <h3>Sample BOT Status</h3>

      <button onClick={checkBotStatus} disabled={loading}>
        {loading ? "error" : "霑･・ｶ隲ｷ迢暦ｽ｢・ｺ髫ｱ繝ｻ}
      </button>

      <div style={{ marginTop: "10px" }}>
        {status ? (
          <pre style={{ background: "#f5f5f5", padding: "10px" }}>
            {JSON.stringify(status, null, 2)}
          </pre>
        ) : (
          <p>邵ｺ阮呻ｼ・ｸｺ・ｫBOT霑･・ｶ隲ｷ荵昶ｲ髯ｦ・ｨ驕会ｽｺ邵ｺ霈費ｽ檎ｸｺ・ｾ邵ｺ繝ｻ/p>
        )}
      </div>
    </div>
  );
}
