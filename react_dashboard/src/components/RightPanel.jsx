import { useState, useEffect } from 'react'

const API_BASE = 'http://34.85.66.137:8000'

export default function RightPanel() {
  const [status, setStatus] = useState('STOPPED')
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  // --------------------------
  // 取得
  // --------------------------
  const fetchData = async () => {
    try {
      setLoading(true)

      const [statusRes, logsRes] = await Promise.all([
        fetch(`${API_BASE}/bot_status`),
        fetch(`${API_BASE}/logs`)
      ])

      const statusData = await statusRes.json()
      const logsData = await logsRes.json()

      setStatus(statusData.running ? 'RUNNING' : 'STOPPED')
      setLogs(Array.isArray(logsData) ? logsData : [])

    } catch (err) {
      console.error(err)
      setStatus('ERROR')
      setLogs([])
    } finally {
      setLoading(false)
    }
  }

  // --------------------------
  // Bot操作
  // --------------------------
  const startBot = async () => {
    try {
      await fetch(`${API_BASE}/bot/start`, {
        method: 'POST'
      })
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  const stopBot = async () => {
    try {
      await fetch(`${API_BASE}/bot/stop`, {
        method: 'POST'
      })
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
            <li key={index}>
              [{log.time}] {log.type} - {log.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}