import { useState } from "react";

export default function MoneyManagementManualRefreshControl({
    disabledReason,
    label,
    onRefresh,
}) {
    const [failure, setFailure] = useState(null);

    const refresh = async () => {
        setFailure(null);
        const result = await onRefresh();
        if (!result?.ok && !result?.inProgress) {
            setFailure(
                "Refresh failed. Last known values may be outdated. Entry is blocked.",
            );
        }
    };

    return (
        <span
            aria-busy={label === "REFRESHING"}
            className="mm-header__refresh-control"
        >
            <button
                className="mi-status-label mi-status-label--muted mm-header__refresh"
                disabled={Boolean(disabledReason)}
                onClick={refresh}
                title={disabledReason ?? "Refresh status and configuration"}
                type="button"
            >
                {label}
            </button>
            {failure && (
                <span className="mm-header__refresh-error" role="alert">
                    {failure}
                </span>
            )}
        </span>
    );
}
