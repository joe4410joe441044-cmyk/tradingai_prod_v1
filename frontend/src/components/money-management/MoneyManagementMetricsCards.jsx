import MoneyManagementCardShell from "./MoneyManagementCardShell";
import {
    MoneyManagementMetricRows,
    MoneyManagementStatusBadge,
} from "./MoneyManagementPrimitives";

export function PerformanceCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            loading={viewModel.state === "LOADING"}
            title="Performance"
        >
            <MoneyManagementMetricRows rows={viewModel.performance} />
        </MoneyManagementCardShell>
    );
}

export function StatisticsCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            loading={viewModel.state === "LOADING"}
            title="Statistics"
        >
            <MoneyManagementMetricRows rows={viewModel.statistics} />
        </MoneyManagementCardShell>
    );
}

export function ProjectionCard({ viewModel }) {
    return (
        <MoneyManagementCardShell
            className="mm-card--projection"
            loading={viewModel.state === "LOADING"}
            title="Projection"
        >
            <MoneyManagementStatusBadge
                text={viewModel.projection.current.text}
                variant={viewModel.projection.current.variant}
            />
            <p className="mm-projection-note">
                {viewModel.projection.description}
            </p>
        </MoneyManagementCardShell>
    );
}
