// src/main.jsx

import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App.jsx";

import "./index.css";
import "./styles/dashboard.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  console.error("Root element (#root) not found in index.html");
} else {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}