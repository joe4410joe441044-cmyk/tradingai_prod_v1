import { useState, useEffect } from 'react';

export default function TestLogsAndBot() {
  const [logs, setLogs] = useState([]);
  const [botStatus, setBotStatus] = useState('STOPPED');

  // Logs 取得
  useEffect(() => {
    const fetchLogs = () => {
      fetch('http://localhost:8000/logs')
        .then(res => res.json())
        .then(data => setLogs(data))
        .catch(err => console.error('Logs fetch error:', err));
    };

    const fetchBotStatus = () => {
      fetch('http://localhost:8000/bot_status')
        .then(res => res.json())
        .then(data => setBotStatus(data.status))
        .catch(err => console.error('Bot status fetch error:', err));
    };

    fetchLogs();
    fetchBotStatus();

    const interval = setInterval(() => {
      fetchLogs();
      fetchBotStatus();
    }, 10000); // 10秒ごと更新

    return () => clearInterval(interval);
  }, []);

  const handleBotToggle = () => {
    const action = botStatus === 'RUNNING' ? 'stop' : 'start';
    fetch(`http://localhost:8000/bot/${action}`, { method: 'POST' })
      .then(res => res.json())
      .then(data => setBotStatus(data.status))
      .catch(err => console.error('Bot toggle error:', err));
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