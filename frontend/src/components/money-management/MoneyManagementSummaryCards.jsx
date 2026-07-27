import MoneyManagementCardShell from "./MoneyManagementCardShell";
import {
    MoneyManagementMetricRows,
    MoneyManagementStatusBadge,
} from "./MoneyManagementPrimitives";

const cardNote = (viewModel) => (
    viewModel.lastKnown ? "Last known value" : null
);

export function RuntimeSummaryCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            dataNote={cardNote(viewModel)}
            loading={viewModel.state === "LOADING"}
            title="Runtime"
        >
            <MoneyManagementMetricRows rows={viewModel.runtime} />
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
            dataNote={cardNote(viewModel)}
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
            dataNote={cardNote(viewModel)}
            loading={viewModel.state === "LOADING"}
            title="Capital"
        >
            <MoneyManagementMetricRows rows={viewModel.capital} />
        </MoneyManagementCardShell>
    );
}
