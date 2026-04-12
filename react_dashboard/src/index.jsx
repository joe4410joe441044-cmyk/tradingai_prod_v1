// src/index.jsx

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// root要素の存在チェック付き（クラッシュ防止）
const rootElement = document.getElementById("root");

if (!rootElement) {
  console.error("Root element not found");
} else {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}