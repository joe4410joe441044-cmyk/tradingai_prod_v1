import { useState, useEffect } from 'react'

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
        fetch('http://localhost:8000/bot_status'),
        fetch('http://localhost:8000/logs')
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
  // Bot操作（★追加）
  // --------------------------
  const startBot = async () => {
    await fetch('http://localhost:8000/bot/start', {
      method: 'POST'
    })
    fetchData()
  }

  const stopBot = async () => {
    await fetch('http://localhost:8000/bot/stop', {
      method: 'POST'
    })
    fetchData()
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

      {/* ★ここ追加 */}
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