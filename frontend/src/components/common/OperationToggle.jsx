export default function OperationToggle({
    checked,
    disabled = false,
    loading = false,
    onChange,
    label,
    ariaLabel,
    onText = "ON",
    offText = "OFF",
    className = "",
}) {
    const isChecked = checked === true;
    const isDisabled = disabled === true;
    const isLoading = loading === true;
    const isUnavailable = isDisabled || isLoading;
    const accessibleLabel = ariaLabel || label || "Operation toggle";
    const rootClassName = [
        "operation-toggle",
        isChecked ? "operation-toggle--checked" : "operation-toggle--unchecked",
        isDisabled ? "operation-toggle--disabled" : "",
        isLoading ? "operation-toggle--loading" : "",
        className,
    ].filter(Boolean).join(" ");

    const handleClick = () => {
        if (isUnavailable) {
            return;
        }

        if (typeof onChange === "function") {
            onChange(!isChecked);
        }
    };

    return (
        <div className={rootClassName}>
            {label && (
                <span className="operation-toggle__label">
                    {label}
                </span>
            )}

            <button
                aria-busy={isLoading ? "true" : undefined}
                aria-checked={isChecked}
                aria-label={accessibleLabel}
                className="operation-toggle__control"
                disabled={isUnavailable}
                onClick={handleClick}
                role="switch"
                type="button"
            >
                <span
                    aria-hidden="true"
                    className="operation-toggle__state operation-toggle__state--off"
                >
                    {offText}
                </span>

                <span
                    aria-hidden="true"
                    className="operation-toggle__track"
                >
                    <span className="operation-toggle__thumb" />
                </span>

                <span
                    aria-hidden="true"
                    className="operation-toggle__state operation-toggle__state--on"
                >
                    {onText}
                </span>

                {isLoading && (
                    <span
                        aria-hidden="true"
                        className="operation-toggle__loading-text"
                    >
                        PROCESSING
                    </span>
                )}
            </button>
        </div>
    );
}
