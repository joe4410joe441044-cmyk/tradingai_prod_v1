import PipelineStageList from "./PipelineStageList";
import RuntimeLoopList from "./RuntimeLoopList";

export default function RuntimeHealthPanel({
    stages,
    loops,
    selectedStageId,
    onSelectStage,
}) {
    return (
        <section className="terminal-monitor-section runtime-health-panel">
            <div className="terminal-section-header">
                2 | Runtime Health
            </div>

            <div className="runtime-health-grid">
                <PipelineStageList
                    stages={stages}
                    selectedStageId={selectedStageId}
                    onSelectStage={onSelectStage}
                />
                <RuntimeLoopList loops={loops} />
            </div>
        </section>
    );
}
