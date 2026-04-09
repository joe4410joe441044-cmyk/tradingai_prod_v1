// src/main.jsx

import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'      // ← 本番用 App.jsx
import './index.css'             // CSS は既存のものを読み込み

// React 18+ 形式でレンダリング
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)