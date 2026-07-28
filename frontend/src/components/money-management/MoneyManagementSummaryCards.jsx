import MoneyManagementCardShell from "./MoneyManagementCardShell";
import {
    MoneyManagementMetricRows,
    MoneyManagementStatusBadge,
} from "./MoneyManagementPrimitives";

export function RuntimeSummaryCard({ viewModel }) {
    const runtimeRows = viewModel.runtime
        .filter((row) => row.label !== "Updated")
        .map((row) => row.label === "Polling"
            ? { ...row, label: "Status Polling" }
            : row);
    return (
        <MoneyManagementCardShell
            loading={viewModel.state === "LOADING"}
            title="Runtime"
        >
            <MoneyManagementMetricRows rows={runtimeRows} />
        </MoneyManagementCardShell>
    );
}

export function RiskSummaryCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            loading={viewModel.state === "LOADING"}
            title="Risk"
        >
            <MoneyManagementStatusBadge
                text={viewModel.riskSummary.state.text}
                variant={viewModel.riskSummary.state.variant}
            />
            <MoneyManagementMetricRows
                rows={viewModel.riskSummary.rows}
            />
        </MoneyManagementCardShell>
    );
}

export function ExposureSummaryCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            loading={viewModel.state === "LOADING"}
            title="Exposure"
        >
            <MoneyManagementMetricRows rows={viewModel.exposure} />
        </MoneyManagementCardShell>
    );
}

export function CapitalSummaryCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            loading={viewModel.state === "LOADING"}
            title="Capital"
        >
            <MoneyManagementMetricRows rows={viewModel.capital} />
        </MoneyManagementCardShell>
    );
}
