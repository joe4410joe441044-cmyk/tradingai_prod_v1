export default function RuntimeLoopList({ loops = [] }) {
    return (
        <div className="runtime-health-group">
            <div className="runtime-health-group-title">
                RUNTIME LOOPS（ランタイムループ）
                <span>{loops.length} LOOPS</span>
            </div>

            <div className="runtime-loop-list">
                {loops.map((loop) => (
                    <div className="runtime-loop-row" key={loop.id}>
                        <span>{loop.name}</span>
                        <span className={`runtime-status runtime-status-${loop.status.toLowerCase()}`}>
                            {loop.status}
                        </span>
                    </div>
                ))}
            </div>
        </div>
    );
}
