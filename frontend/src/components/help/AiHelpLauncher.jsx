export default function AiHelpLauncher({ side, label, expanded = false, controls, onToggle }) {
    return (
        <button
            type="button"
            className={`ai-help-launcher ai-help-launcher--${side}`}
            aria-expanded={expanded}
            aria-controls={controls}
            onClick={onToggle}
        >
            <span className="ai-help-launcher__mark" aria-hidden="true">?</span>
            <span className="ai-help-launcher__label">{label}</span>
        </button>
    );
}
