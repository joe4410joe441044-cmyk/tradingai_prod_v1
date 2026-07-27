import {
    MoneyManagementStatusBadge,
} from "./MoneyManagementPrimitives";
import MoneyManagementManualRefreshControl from "./MoneyManagementManualRefreshControl";

export default function MoneyManagementHeader({
    header,
    onRefresh,
    refresh,
}) {
    return (
        <header className="mi-header mm-header">
            <div>
                <h1 className="mi-header__title">Money Management</h1>
                <p className="mi-header__subtitle">
                    Capital Protection &amp; Risk Management Engine
                </p>
            </div>

            <div
                aria-label="Money Management status and controls"
                className="mi-header__badges"
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
                <span className="mi-status-label mi-status-label--muted">
                    {header.updated}
                </span>
            </div>
        </header>
    );
}
