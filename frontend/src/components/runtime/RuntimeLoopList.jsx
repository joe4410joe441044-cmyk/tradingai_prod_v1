const RUNTIME_LOOPS = [
    "Runtime Loop",
    "Market Feed",
    "OrderBook WS",
    "Strategy Loop",
    "AI Loop",
    "Governance Loop",
    "Execution Queue",
    "Exchange Sync",
    "Portfolio Sync",
];

export default function RuntimeLoopList() {
    return (
        <div className="runtime-health-group">
            <div className="runtime-health-group-title">
                RUNTIME LOOPS（ランタイムループ）
                <span>{RUNTIME_LOOPS.length} LOOPS</span>
            </div>

            <div className="runtime-loop-list">
                {RUNTIME_LOOPS.map((loop) => (
                    <div className="runtime-loop-row" key={loop}>
                        <span>{loop}</span>
                        <span className="runtime-wait-state">WAIT</span>
                    </div>
                ))}
            </div>
        </div>
    );
}
