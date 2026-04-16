import { useState, useEffect } from 'react'

const API_BASE = '/api'

export default function RightPanel() {
  const [status, setStatus] = useState('STOPPED')
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  // --------------------------
  // 繝・・繧ｿ蜿門ｾ・
  // --------------------------
  const fetchData = async () => {
    try {
      setLoading(true)

      const [statusRes, logsRes] = await Promise.all([
        fetch(`${API_BASE}/bot_status`),
        fetch(`${API_BASE}/logs`)
      ])

      const statusData = await statusRes.json()

      // logs縺ｯTEXT縺ｧ蜿励￠繧具ｼ磯㍾隕∽ｿｮ豁｣・・
      const logsText = await logsRes.text()

      setStatus(statusData.running ? 'RUNNING' : 'STOPPED')

      const parsedLogs = logsText
        .split('\n')
        .filter(Boolean)
        .slice(-50)

      setLogs(parsedLogs)

    } catch (err) {
      console.error('RightPanel error:', err)
      setStatus('ERROR')
      setLogs([])
    } finally {
      setLoading(false)
    }
  }

  // --------------------------
  // BOT謫堺ｽ懶ｼ・PS莉墓ｧ假ｼ・
  // --------------------------
  const startBot = async () => {
    try {
      await fetch(`${API_BASE}/start`)
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  const stopBot = async () => {
    try {
      await fetch(`${API_BASE}/stop`)
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  // --------------------------
  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 3000)
    return () => clearInterval(interval)
  }, [])

  // --------------------------
  return (
    <div>
      <h3>Bot Status</h3>
      <p>{loading ? 'Loading...' : status}</p>

      <button onClick={startBot}>Start</button>
      <button onClick={stopBot} style={{ marginLeft: '10px' }}>
        Stop
      </button>

      <h3>Logs</h3>

      {loading ? (
        <p>Loading...</p>
      ) : (
        <ul>
          {logs.map((log, index) => (
            <li key={index}>{log}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
