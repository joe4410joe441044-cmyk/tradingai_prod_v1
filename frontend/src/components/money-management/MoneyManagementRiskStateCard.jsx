import MoneyManagementCardShell from "./MoneyManagementCardShell";
import {
    MoneyManagementMetricRows,
    MoneyManagementReasonList,
    MoneyManagementStatusBadge,
} from "./MoneyManagementPrimitives";

export default function MoneyManagementRiskStateCard({ viewModel }) {
    const risk = viewModel.riskState;
    const rows = [
        {
            label: "Recommended Action",
            value: {
                text: risk.recommendedAction,
                unavailable: risk.recommendedAction === "UNKNOWN",
                unit: null,
            },
        },
        {
            label: "Entry Permission",
            value: {
                text: risk.entryPermission.text,
                unavailable: false,
                unit: null,
            },
            variant: risk.entryPermission.variant,
        },
        {
            label: "Protection Level",
            value: {
                text: risk.protectionLevel,
                unavailable: false,
                unit: null,
            },
        },
        {
            label: "Primary Reason",
            value: {
                text: risk.primaryReason,
                unavailable: false,
                unit: null,
            },
        },
        {
            label: "Status Updated",
            value: {
                text: risk.updated,
                unavailable: risk.updated === "—",
                unit: null,
            },
        },
    ];

    return (
        <MoneyManagementCardShell
            className="mm-card--risk-state"
            loading={viewModel.state === "LOADING"}
            title="Risk State"
        >
            <MoneyManagementStatusBadge
                text={risk.state.text}
                variant={risk.state.variant}
            />
            <MoneyManagementMetricRows rows={rows} />
            <div
                aria-label="Money Management reasons and diagnostics"
                className="mm-reason-grid"
            >
                <MoneyManagementReasonList
                    group={risk.reasons.warning}
                    title="Warning Reasons"
                />
                <MoneyManagementReasonList
                    group={risk.reasons.hold}
                    title="Hold Reasons"
                />
                <MoneyManagementReasonList
                    group={risk.reasons.block}
                    title="Block Reasons"
                />
                <MoneyManagementReasonList
                    group={risk.reasons.diagnostic}
                    title="Diagnostic Reasons"
                />
            </div>
        </MoneyManagementCardShell>
    );
}
