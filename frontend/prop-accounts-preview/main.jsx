import React from "react";
import { createRoot } from "react-dom/client";

import PropAccountsPanel from "../src/components/prop-accounts/PropAccountsPanel.jsx";
import "./preview.css";

createRoot(document.getElementById("root")).render(
    <React.StrictMode>
        <div className="cc-prop-preview">
            <PropAccountsPanel />
        </div>
    </React.StrictMode>,
);
