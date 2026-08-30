import MoneyManagementBottomSection from "../components/money-management/MoneyManagementBottomSection";
import MoneyManagementCapitalDrawdownSection from "../components/money-management/MoneyManagementCapitalDrawdownSection";
import MoneyManagementHeader from "../components/money-management/MoneyManagementHeader";
import MoneyManagementMainSection from "../components/money-management/MoneyManagementMainSection";
import MoneyManagementRuntimeSummarySection from "../components/money-management/MoneyManagementRuntimeSummarySection";
import MoneyManagementTopSummarySection from "../components/money-management/MoneyManagementTopSummarySection";
import {
    createMoneyManagementInteractionViewModel,
    useMoneyManagement,
} from "../features/money-management";
import {
    createMoneyManagementViewModel,
} from "../features/money-management/view/moneyManagementViewModel";

export default function MoneyManagementPage() {
    const moneyManagement = useMoneyManagement();
    const viewModel = createMoneyManagementViewModel(moneyManagement);
    const interaction =
        createMoneyManagementInteractionViewModel(moneyManagement);

    return (
        <main className="mi-page mm-page">
            <MoneyManagementHeader
                header={viewModel.header}
                onRefresh={moneyManagement.refresh}
                refresh={interaction.refresh}
            />

            {viewModel.banner && viewModel.state !== "UNAVAILABLE" && (
                <p
                    className={[
                        "mm-page__state",
                        `mm-page__state--${viewModel.state.toLowerCase()}`,
                    ].join(" ")}
                    role="status"
                >
                    {viewModel.banner}
                </p>
            )}

            <MoneyManagementCapitalDrawdownSection />
            <MoneyManagementTopSummarySection viewModel={viewModel} />
            <MoneyManagementRuntimeSummarySection viewModel={viewModel} />
            <MoneyManagementMainSection
                interaction={interaction}
                moneyManagement={moneyManagement}
                viewModel={viewModel}
            />
            <MoneyManagementBottomSection
                interaction={interaction}
                moneyManagement={moneyManagement}
                viewModel={viewModel}
            />
        </main>
    );
}
