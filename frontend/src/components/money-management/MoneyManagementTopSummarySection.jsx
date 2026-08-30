import {
    CapitalSummaryCard,
    ExposureSummaryCard,
    RiskSummaryCard,
} from "./MoneyManagementSummaryCards";
import { PerformanceCard } from "./MoneyManagementMetricsCards";

export default function MoneyManagementTopSummarySection({ viewModel }) {
    return (
        <section
            aria-label="Money Management summary"
            className="mm-summary"
        >
            <CapitalSummaryCard viewModel={viewModel} />
            <RiskSummaryCard viewModel={viewModel} />
            <ExposureSummaryCard viewModel={viewModel} />
            <PerformanceCard viewModel={viewModel} />
        </section>
    );
}
