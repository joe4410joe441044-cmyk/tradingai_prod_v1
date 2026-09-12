import React from "react";
import { createRoot } from "react-dom/client";
import MoneyManagementPage from "../../src/pages/MoneyManagementPage.jsx";
import "../../src/App.css";
import "../../src/index.css";
import "../../src/styles/market-intelligence.css";
import "../../src/styles/money-management.css";
createRoot(document.getElementById("root")).render(
    <div className="market-intelligence"><MoneyManagementPage /></div>,
);
