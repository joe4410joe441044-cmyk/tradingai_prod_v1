import PipelineStageList from "./PipelineStageList";
import RuntimeLoopList from "./RuntimeLoopList";

export default function RuntimeHealthPanel() {
    return (
        <section className="terminal-monitor-section runtime-health-panel">
            <div className="terminal-section-header">
                2 | Runtime Health
            </div>

            <div className="runtime-health-grid">
                <PipelineStageList />
                <RuntimeLoopList />
            </div>
        </section>
    );
}
