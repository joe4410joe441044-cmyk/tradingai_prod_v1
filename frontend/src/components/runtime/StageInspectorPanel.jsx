export default function StageInspectorPanel({ stage }) {
    const fields = [
        { label: "BACKEND FILE（ファイル）", value: stage?.backendFile ?? "--" },
        { label: "FUNCTION（関数）", value: stage?.functionName ?? "--" },
        { label: "DURATION（実行時間）", value: stage?.duration ?? "--" },
        { label: "INPUT（入力）", value: stage?.input ?? "--", expanded: true },
        { label: "OUTPUT（出力）", value: stage?.output ?? "--", expanded: true },
        { label: "EXCEPTION（例外）", value: stage?.exception ?? "None", expanded: true },
        { label: "RELATED FILES（関連ファイル）", value: stage?.relatedFiles ?? "--", expanded: true },
    ];

    const status = stage?.status ?? "WAIT";

    return (
        <section className="stage-inspector-card">
            <div className="governance-card-title">
                STAGE INSPECTOR（ステージ詳細）
            </div>

            <div className="stage-inspector-selection">
                <div className="stage-inspector-summary">
                    <span>STAGE（ステージ）</span>
                    <strong>{stage?.name ?? "Not Selected"}</strong>
                </div>

                <div className="stage-inspector-summary">
                    <span>STATUS（状態）</span>
                    <strong className={`runtime-status runtime-status-${status.toLowerCase()}`}>
                        {status}
                    </strong>
                </div>
            </div>

            <div className="stage-inspector-fields">
                {fields.map((field) => (
                    <div
                        className={field.expanded
                            ? "stage-inspector-field expanded"
                            : "stage-inspector-field"
                        }
                        key={field.label}
                    >
                        <span>{field.label}</span>
                        <code>{field.value}</code>
                    </div>
                ))}
            </div>
        </section>
    );
}
