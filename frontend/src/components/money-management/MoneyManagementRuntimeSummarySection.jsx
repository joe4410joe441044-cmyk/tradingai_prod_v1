import { RuntimeSummaryCard } from "./MoneyManagementSummaryCards";

export default function MoneyManagementRuntimeSummarySection({ viewModel }) {
    return (
        <section
            aria-label="Money Management runtime"
            className="mm-runtime-summary"
        >
            <h2 className="mm-section-title">Actual Runtime（実稼働）</h2>
            <p>以下の Runtime・Operation / Decision・Configuration / Analysis は実稼働の状態と設定です。</p>
            <RuntimeSummaryCard viewModel={viewModel} />
        </section>
    );
}
