// src/index.jsx

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// root隕∫ｴ縺ｮ蟄伜惠繝√ぉ繝・け莉倥″・医け繝ｩ繝・す繝･髦ｲ豁｢・・
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
