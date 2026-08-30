import { RuntimeSummaryCard } from "./MoneyManagementSummaryCards";

export default function MoneyManagementRuntimeSummarySection({ viewModel }) {
    return (
        <section
            aria-label="Money Management runtime"
            className="mm-runtime-summary"
        >
            <RuntimeSummaryCard viewModel={viewModel} />
        </section>
    );
}
