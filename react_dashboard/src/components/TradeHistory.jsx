// src/components/RightPanel.jsx
import { useState, useEffect } from 'react';
import TradeHistory from './TradeHistory.jsx';

const API_BASE = 'http://34.85.66.137:8000';

export default function RightPanel() {
  const [logs, setLogs] = useState([]);
  const [botStatus, setBotStatus] = useState('STOPPED');
  const [history, setHistory] = useState([]);

  // --- データ取得 + 自動更新 ---
  useEffect(() => {
    const fetchLogs = () => {
      fetch(`${API_BASE}/logs`)
        .then(res => res.json())
        .then(data => setLogs(data))
        .catch(err => console.error('Logs fetch error:', err));
    };

    const fetchBotStatus = () => {
      fetch(`${API_BASE}/bot_status`)
        .then(res => res.json())
        .then(data => setBotStatus(data.status))
        .catch(err => console.error('Bot status fetch error:', err));
    };

    const fetchTradeHistory = () => {
      fetch(`${API_BASE}/trade_history`)
        .then(res => res.json())
        .then(data => setHistory(data))
        .catch(err => console.error('Trade history fetch error:', err));
    };

    fetchLogs();
    fetchBotStatus();
    fetchTradeHistory();

    const interval = setInterval(() => {
      fetchLogs();
      fetchBotStatus();
      fetchTradeHistory();
    }, 10000); // 10秒ごと更新

    return () => clearInterval(interval);
  }, []);

  // --- Bot Start/Stop ---
  const handleBotToggle = () => {
    const action = botStatus === 'RUNNING' ? 'stop' : 'start';

    fetch(`${API_BASE}/bot/${action}`, { method: 'POST' })
      .then(res => res.json())
      .then(data => setBotStatus(data.status))
      .catch(err => console.error('Bot toggle error:', err));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: '20px', height: '100%' }}>

      {/* Bot Status + Logs */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto' }}>

        <div className="card">
          <h3>Bot Status</h3>
          <p>Status: {botStatus}</p>
        </div>

        <div className="card" style={{ flex: 1, overflowY: 'auto' }}>
          <h3>Logs</h3>
          <ul style={{ paddingLeft: '20px' }}>
            {logs.map((log, i) => (
              <li key={i}>{log}</li>
            ))}
          </ul>
        </div>

        <div className="card" style={{ flex: 1, overflowY: 'auto' }}>
          <TradeHistory history={history} />
        </div>

      </div>

      {/* 右下 Start/Stop ボタン */}
      <div style={{ marginTop: 'auto', textAlign: 'right' }}>
        <button
          onClick={handleBotToggle}
          style={{ padding: '10px 20px', borderRadius: '6px' }}
        >
          {botStatus === 'RUNNING' ? 'Stop Bot' : 'Start Bot'}
        </button>
      </div>

    </div>
  );
}