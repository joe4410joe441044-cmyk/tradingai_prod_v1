import { useState, useEffect } from 'react'

const API_BASE = '/api'

export default function TradeHistory() {
  const [logs, setLogs] = useState([])
  const [botStatus, setBotStatus] = useState('STOPPED')
  const [history, setHistory] = useState([])

  // --------------------------
  // 繝・・繧ｿ蜿門ｾ・
  // --------------------------
  const fetchData = async () => {
    try {
      const [logsRes, statusRes] = await Promise.all([
        fetch(`${API_BASE}/logs`),
        fetch(`${API_BASE}/bot_status`)
      ])

      const logsText = await logsRes.text()
      const statusData = await statusRes.json()

      setLogs(
        logsText
          .split('\n')
          .filter(Boolean)
          .slice(-50)
      )

      setBotStatus(statusData.running ? 'RUNNING' : 'STOPPED')

      // trade_history縺ｯVPS縺ｫ辟｡縺・庄閭ｽ諤ｧ 竊・fallback
      setHistory([])

    } catch (err) {
      console.error('TradeHistory error:', err)
      setLogs([])
      setHistory([])
      setBotStatus('ERROR')
    }
  }

  // --------------------------
  useEffect(() => {
    fetchData()

    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  // --------------------------
  // BOT謫堺ｽ懶ｼ・PS莉墓ｧ假ｼ・
  // --------------------------
  const handleBotToggle = async () => {
    try {
      const action = botStatus === 'RUNNING' ? 'stop' : 'start'

      await fetch(`${API_BASE}/${action}`)
      fetchData()
    } catch (err) {
      console.error('Bot toggle error:', err)
    }
  }

  // --------------------------
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      flex: 1,
      gap: '20px',
      height: '100%'
    }}>

      {/* STATUS */}
      <div className="card">
        <h3>Bot Status</h3>
        <p>Status: {botStatus}</p>
      </div>

      {/* LOGS */}
      <div className="card" style={{ flex: 1, overflowY: 'auto' }}>
        <h3>Logs</h3>

        {logs.length === 0 ? (
          <p>No logs</p>
        ) : (
          <ul style={{ paddingLeft: '20px' }}>
            {logs.map((log, i) => (
              <li key={i}>{log}</li>
            ))}
          </ul>
        )}
      </div>

      {/* HISTORY・亥ｰ・擂諡｡蠑ｵ・・*/}
      <div className="card">
        <h3>Trade History</h3>
        <p>{history.length === 0 ? 'No data' : JSON.stringify(history)}</p>
      </div>

      {/* BUTTON */}
      <div style={{ textAlign: 'right' }}>
        <button
          onClick={handleBotToggle}
          style={{ padding: '10px 20px', borderRadius: '6px' }}
        >
          {botStatus === 'RUNNING' ? 'Stop Bot' : 'Start Bot'}
        </button>
      </div>

    </div>
  )
}
