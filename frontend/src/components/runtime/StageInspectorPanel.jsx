const INSPECTOR_FIELDS = [
    { label: "BACKEND FILE（ファイル）", value: "--" },
    { label: "FUNCTION（関数）", value: "--" },
    { label: "DURATION（実行時間）", value: "--" },
    { label: "INPUT（入力）", value: "--", expanded: true },
    { label: "OUTPUT（出力）", value: "--", expanded: true },
    { label: "EXCEPTION（例外）", value: "None", expanded: true },
    { label: "RELATED FILES（関連ファイル）", value: "--", expanded: true },
];

export default function StageInspectorPanel() {
    return (
        <section className="stage-inspector-card">
            <div className="governance-card-title">
                STAGE INSPECTOR（ステージ詳細）
            </div>

            <div className="stage-inspector-selection">
                <div className="stage-inspector-summary">
                    <span>STAGE（ステージ）</span>
                    <strong>Not Selected</strong>
                </div>

                <div className="stage-inspector-summary">
                    <span>STATUS（状態）</span>
                    <strong className="stage-inspector-wait">WAIT</strong>
                </div>
            </div>

            <div className="stage-inspector-fields">
                {INSPECTOR_FIELDS.map((field) => (
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
