import { useState, useEffect } from 'react'
import PositionsTable from './components/PositionsTable.jsx'
import PriceCard from './components/PriceCard.jsx'
import RightPanel from './components/RightPanel.jsx'

export default function App() {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)
  const [botStatus, setBotStatus] = useState({ running: false })
  const [currentPrice, setCurrentPrice] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)

  // ✅ 修正：nginx経由でAPIへアクセス
  const BASE_URL = "/api"

  useEffect(() => {
    const controller = new AbortController()

    const fetchData = async () => {
      try {
        setLoading(true)
        setErrorMsg(null)

        // ポジション取得
        const posRes = await fetch(`${BASE_URL}/positions`, {
          signal: controller.signal
        })
        if (!posRes.ok) throw new Error('ポジション取得失敗')
        const posData = await posRes.json()
        setPositions(Array.isArray(posData) ? posData : [])

        // BOTステータス取得
        const statusRes = await fetch(`${BASE_URL}/bot_status`, {
          signal: controller.signal
        })
        if (!statusRes.ok) throw new Error('BOTステータス取得失敗')
        const statusData = await statusRes.json()
        setBotStatus(statusData)

        // 価格
        if (posData.length > 0) {
          setCurrentPrice(posData[posData.length - 1].mark_price)
        } else {
          setCurrentPrice(null)
        }

      } catch (err) {
        if (err.name !== 'AbortError') {
          console.error(err)
          setPositions([])
          setBotStatus({ running: false })
          setCurrentPrice(null)
          setErrorMsg('接続に失敗しました。FastAPI が起動しているか確認してください。')
        }
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000)

    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, []) // ← BASE_URL依存削除（固定なので不要）

  // Bot操作
  const startBot = async () => {
    try {
      await fetch(`${BASE_URL}/start`)
      setBotStatus({ running: true })
    } catch (err) {
      console.error(err)
      setErrorMsg('BOTの起動に失敗しました')
    }
  }

  const stopBot = async () => {
    try {
      await fetch(`${BASE_URL}/stop`)
      setBotStatus({ running: false })
    } catch (err) {
      console.error(err)
      setErrorMsg('BOTの停止に失敗しました')
    }
  }

  return (
    <div style={{ display: 'flex', gap: '20px', padding: '20px' }}>
      <div style={{ flex: 1 }}>
        <PriceCard currentPrice={currentPrice} />
        <PositionsTable positions={positions} loading={loading} />

        {errorMsg && (
          <div style={{ color: 'red', marginTop: '10px' }}>
            {errorMsg}
          </div>
        )}

        <div style={{ marginTop: '20px' }}>
          <button onClick={startBot} disabled={botStatus.running} style={{ marginRight: '10px' }}>
            Start Bot
          </button>
          <button onClick={stopBot} disabled={!botStatus.running}>
            Stop Bot
          </button>
          <span style={{ marginLeft: '20px' }}>
            Status: {botStatus.running ? 'RUNNING' : 'STOPPED'}
          </span>
        </div>
      </div>

      <div style={{ width: '350px' }}>
        <RightPanel />
      </div>
    </div>
  )
}