// src/main.jsx

import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App.jsx";
import "./App.css";
import "./index.css";
import "./styles/dashboard.css";
import "./styles/market-intelligence.css";
import "./styles/market-recorder.css";
import "./styles/ai-advisor.css";
import "./styles/money-management.css";

const HTTPS_ENFORCEMENT_EXCLUDED_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

if (
    typeof window !== "undefined"
    && window.location.protocol === "http:"
    && !HTTPS_ENFORCEMENT_EXCLUDED_HOSTS.has(window.location.hostname)
) {
    window.location.replace(
        "https://" + window.location.host + window.location.pathname
        + window.location.search + window.location.hash,
    );
}

const rootElement = document.getElementById("root");

if (!rootElement) {
  console.error("Root element (#root) not found in index.html");
} else {
  ReactDOM.createRoot(rootElement).render(
    <App />
  );
}
