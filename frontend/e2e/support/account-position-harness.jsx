import React from "react";
import { createRoot } from "react-dom/client";
import { AccountStatusView } from "../../src/pages/AccountStatusPage.jsx";
import "../../src/index.css";
import "../../src/App.css";
import "../../src/styles/dashboard.css";

const scenario = new URLSearchParams(location.search).get("scenario") ?? "long";
const open = { status:"OPEN",mode:"PAPER",control:"MANUAL",symbol:"GRIFFAINUSDT",side:"LONG",orderSide:"BUY",quantity:6174,quantityUnit:"coin",coinQuantity:6174,contractQuantity:12,entryPrice:.016195,markPrice:.016195,unrealizedPnl:0,positionValue:99.98793,leverage:null,marginUsed:null,liquidationPrice:null,entryTime:1790728279,holdingMs:643,source:"PAPER_SIMULATION",freshness:"FRESH",sourceUpdatedAt:1790728279.643 };
const last = { event:"CLOSED",mode:"PAPER",control:"MANUAL",symbol:"GRIFFAINUSDT",side:"LONG",quantity:6174,quantityUnit:"coin",entryPrice:.016195,exitPrice:.016195,realizedPnl:0,holdingMs:643,openedAt:1790728279,closedAt:1790728279.643,exitReason:"MOMENTUM_DECAY",source:"PARAMETER_PERFORMANCE_TRADE_HISTORY" };
const scenarios = {
    long:open,
    short:{...open,mode:"LIVE",control:"BOT",symbol:"XRPUSDTM",side:"SHORT",quantity:12,quantityUnit:"contract",coinQuantity:null,leverage:5,marginUsed:12.4,liquidationPrice:.012,unrealizedPnl:-1.23,source:"KUCOIN_FUTURES"},
    flat:{status:"FLAT",mode:"PAPER",freshness:"FRESH"},
    unknown:{status:"UNKNOWN",mode:"LIVE"},
    stale:{...open,status:"UNKNOWN",freshness:"STALE"},
    multiple:{status:"UNKNOWN",mode:"LIVE",reason:"MULTIPLE_POSITIONS",positions:[{symbol:"XRPUSDTM",side:"LONG"},{symbol:"ETHUSDTM",side:"SHORT"}]},
};

const selected = scenarios[scenario];
const otherMode = selected.mode === "PAPER" ? "LIVE" : "PAPER";
const emptyFlat = { status: "FLAT", mode: otherMode, control: "UNKNOWN", freshness: "FRESH", positions: [] };
const selectedEvent = { ...last, mode: selected.mode };
const otherEvent = { event: "NONE", mode: otherMode, control: "UNKNOWN" };

const accountRuntime = {
    positionsByMode: { [selected.mode]: selected, [otherMode]: emptyFlat },
    lastPositionEventsByMode: { [selected.mode]: selectedEvent, [otherMode]: otherEvent },
    currentPosition: selected,
    lastPositionEvent: selectedEvent,
};

createRoot(document.getElementById("root")).render(<div className="dashboard"><AccountStatusView botStatus={{selectedMode:selected.mode,accountRuntime}} /></div>);
