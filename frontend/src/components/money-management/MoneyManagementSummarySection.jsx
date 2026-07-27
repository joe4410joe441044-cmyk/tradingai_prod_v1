import {
    CapitalSummaryCard,
    ExposureSummaryCard,
    RiskSummaryCard,
    RuntimeSummaryCard,
} from "./MoneyManagementSummaryCards";

export default function MoneyManagementSummarySection({ viewModel }) {
    return (
        <section
            aria-label="Money Management summary"
            className="mm-summary"
        >
            <RuntimeSummaryCard viewModel={viewModel} />
            <RiskSummaryCard viewModel={viewModel} />
            <ExposureSummaryCard viewModel={viewModel} />
            <CapitalSummaryCard viewModel={viewModel} />
        </section>
    );
}
