import { useState, useEffect } from 'react'
import { API } from "../../api";

export default function RightPanel() {
  const [status, setStatus] = useState('STOPPED')
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  // --------------------------
  // データ取得（統一API版）
  // --------------------------
  const fetchData = async () => {
    try {
      setLoading(true)

      const [statusRes, logsRes] = await Promise.all([
        fetch(API.botStatus()),
        fetch(API.logs())
      ])

      const statusData = statusRes.ok ? await statusRes.json() : null

      // logsはテキスト形式維持（互換性優先）
      const logsText = logsRes.ok ? await logsRes.text() : ""

      setStatus(statusData?.running ? 'RUNNING' : 'STOPPED')

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
  // BOT START（統一API）
  // --------------------------
  const startBot = async () => {
    try {
      await fetch(API.botStart(), { method: "POST" })
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  // --------------------------
  // BOT STOP（統一API）
  // --------------------------
  const stopBot = async () => {
    try {
      await fetch(API.botStop(), { method: "POST" })
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