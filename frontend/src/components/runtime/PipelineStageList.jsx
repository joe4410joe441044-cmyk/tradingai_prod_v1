const PIPELINE_STAGES = [
    "START REQUEST",
    "TradingRuntime",
    "MarketData",
    "OrderBook",
    "RuntimeAdapter",
    "RuntimeState",
    "Strategy Plugin",
    "AI Plugin",
    "Governance Runtime",
    "Execution Runtime",
    "Execution Governance",
    "Execution Signal Adapter",
    "Execution Engine",
    "Exchange Client",
    "Exchange API",
    "COMPLETE",
];

export default function PipelineStageList() {
    return (
        <div className="runtime-health-group">
            <div className="runtime-health-group-title">
                EXECUTION PIPELINE（実行パイプライン）
                <span>16 STAGES</span>
            </div>

            <ol className="pipeline-stage-list">
                {PIPELINE_STAGES.map((stage, index) => (
                    <li className="pipeline-stage" key={stage}>
                        <span className="pipeline-stage-index">
                            {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="pipeline-stage-name">
                            {stage}
                        </span>
                        <span className="runtime-wait-state">
                            WAIT
                        </span>
                    </li>
                ))}
            </ol>
        </div>
    );
}
