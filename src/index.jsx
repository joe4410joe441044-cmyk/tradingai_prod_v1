// src/index.jsx

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// root髫補悪・ｴ・ｰ邵ｺ・ｮ陝・ｼ懈Β郢昶・縺臥ｹ昴・縺題脂蛟･窶ｳ繝ｻ蛹ｻ縺醍ｹ晢ｽｩ郢昴・縺咏ｹ晢ｽ･鬮ｦ・ｲ雎・ｽ｢繝ｻ繝ｻ
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
