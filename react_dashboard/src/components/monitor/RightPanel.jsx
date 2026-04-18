import { useState, useEffect } from 'react'
import { API } from "../../api";

export default function RightPanel() {
  const [status, setStatus] = useState('STOPPED')
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    try {
      const [statusRes, logsRes] = await Promise.all([
        fetch(API.botStatus()),
        fetch(API.logs())
      ])

      if (!statusRes.ok) {
        setStatus('ERROR')
      } else {
        const statusData = await statusRes.json()
        setStatus(statusData?.running ? 'RUNNING' : 'STOPPED')
      }

      const logsText = logsRes.ok ? await logsRes.text() : ""

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

  const startBot = async () => {
    try {
      await fetch(API.botStart(), { method: "POST" })
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  const stopBot = async () => {
    try {
      await fetch(API.botStop(), { method: "POST" })
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 3000)
    return () => clearInterval(interval)
  }, [])

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