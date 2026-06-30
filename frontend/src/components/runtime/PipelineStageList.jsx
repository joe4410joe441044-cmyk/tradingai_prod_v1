export default function PipelineStageList({
    stages = [],
    selectedStageId,
    onSelectStage,
}) {
    return (
        <div className="runtime-health-group">
            <div className="runtime-health-group-title">
                EXECUTION PIPELINE（実行パイプライン）
                <span>{stages.length} STAGES</span>
            </div>

            <ol className="pipeline-stage-list">
                {stages.map((stage, index) => (
                    <li className="pipeline-stage" key={stage.id}>
                        <button
                            aria-pressed={selectedStageId === stage.id}
                            className={selectedStageId === stage.id
                                ? "pipeline-stage-button selected"
                                : "pipeline-stage-button"
                            }
                            onClick={() => onSelectStage?.(stage.id)}
                            type="button"
                        >
                            <span className="pipeline-stage-index">
                                {String(index + 1).padStart(2, "0")}
                            </span>
                            <span className="pipeline-stage-name">
                                {stage.name}
                            </span>
                            <span className={`runtime-status runtime-status-${stage.status.toLowerCase()}`}>
                                {stage.status}
                            </span>
                        </button>
                    </li>
                ))}
            </ol>
        </div>
    );
}
