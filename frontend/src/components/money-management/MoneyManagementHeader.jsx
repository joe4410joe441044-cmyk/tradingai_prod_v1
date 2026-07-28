import {
    MoneyManagementStatusBadge,
} from "./MoneyManagementPrimitives";
import MoneyManagementManualRefreshControl from "./MoneyManagementManualRefreshControl";

export default function MoneyManagementHeader({
    header,
    onRefresh,
    refresh,
}) {
    const updatedTime = header.updated.replace(/^Updated\s+/i, "");
    return (
        <header className="mm-status-bar">
            <div
                aria-label="Money Management status bar"
                className="mm-status-bar__controls"
            >
                <MoneyManagementStatusBadge
                    text={header.mode.text}
                    variant={header.mode.variant}
                />
                <MoneyManagementStatusBadge
                    text={header.connection.text}
                    variant={header.connection.variant}
                />
                <MoneyManagementManualRefreshControl
                    disabledReason={refresh.disabledReason}
                    label={refresh.label}
                    onRefresh={onRefresh}
                />
                <time className="mm-status-bar__time">
                    {updatedTime}
                </time>
            </div>
        </header>
    );
}
