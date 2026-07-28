import MoneyManagementBottomSection from "../components/money-management/MoneyManagementBottomSection";
import MoneyManagementAnalyticsSection from "../components/money-management/MoneyManagementAnalyticsSection";
import MoneyManagementHeader from "../components/money-management/MoneyManagementHeader";
import MoneyManagementMainSection from "../components/money-management/MoneyManagementMainSection";
import MoneyManagementSummarySection from "../components/money-management/MoneyManagementSummarySection";
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

            <MoneyManagementSummarySection viewModel={viewModel} />
            <MoneyManagementMainSection
                interaction={interaction}
                moneyManagement={moneyManagement}
                viewModel={viewModel}
            />
            <MoneyManagementAnalyticsSection />
            <MoneyManagementBottomSection
                configuration={moneyManagement.configuration}
            />
        </main>
    );
}
