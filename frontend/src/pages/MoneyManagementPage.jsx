import MoneyManagementBottomSection from "../components/money-management/MoneyManagementBottomSection";
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
    const bannerRole = viewModel.state === "UNAVAILABLE"
        ? "alert"
        : "status";

    return (
        <main className="mi-page mm-page">
            <MoneyManagementHeader
                header={viewModel.header}
                onRefresh={moneyManagement.refresh}
                refresh={interaction.refresh}
            />

            {viewModel.banner && (
                <p
                    className={[
                        "mm-page__state",
                        `mm-page__state--${viewModel.state.toLowerCase()}`,
                    ].join(" ")}
                    role={bannerRole}
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
            <MoneyManagementBottomSection
                configuration={moneyManagement.configuration}
            />
        </main>
    );
}
