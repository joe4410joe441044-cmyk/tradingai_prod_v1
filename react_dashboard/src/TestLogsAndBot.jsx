import { useState, useEffect } from 'react';

export default function TestLogsAndBot() {
  const [logs, setLogs] = useState([]);
  const [botStatus, setBotStatus] = useState('STOPPED');

  // Logs & Bot Status 陷ｿ髢・ｾ繝ｻ
  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const res = await fetch('/api/logs');
        const text = await res.text(); // 遶翫・HTML陝・ｽｾ驕ｲ繝ｻ

        // 隰ｾ・ｹ髯ｦ蠕後帝ｩ滓ｦ翫・陋ｹ繝ｻ
        const logArray = text.split('\n').filter(line => line.trim() !== '');
        setLogs(logArray);
      } catch (err) {
        console.error('Logs fetch error:', err);
      }
    };

    const fetchBotStatus = async () => {
      try {
        const res = await fetch('/api/bot_status');
        const data = await res.json();
        setBotStatus(data.status);
      } catch (err) {
        console.error('Bot status fetch error:', err);
      }
    };

    fetchLogs();
    fetchBotStatus();

    const interval = setInterval(() => {
      fetchLogs();
      fetchBotStatus();
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  // BOT ON/OFF
  const handleBotToggle = async () => {
    const action = botStatus === 'RUNNING' ? 'stop' : 'start';

    try {
      await fetch(`/api/${action}`);
      // 陷讎雁徐陟輔・
      const res = await fetch('/api/bot_status');
      const data = await res.json();
      setBotStatus(data.status);
    } catch (err) {
      console.error('Bot toggle error:', err);
    }
  };

  return (
    <div>
      <h2>Bot Status: {botStatus}</h2>
      <button onClick={handleBotToggle}>
        {botStatus === 'RUNNING' ? 'Stop Bot' : 'Start Bot'}
      </button>

      <h3>Logs</h3>
      <ul>
        {logs.map((log, i) => (
          <li key={i}>{log}</li>
        ))}
      </ul>
    </div>
  );
}
