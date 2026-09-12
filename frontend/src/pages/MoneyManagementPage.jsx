import { useEffect, useState } from "react";
import MoneyManagementMonitoringView from "../components/money-management/MoneyManagementMonitoringView";
import { initialViewAuthority, requireViewAuthority } from "../features/money-management/contracts/moneyManagementMonitoringContracts.js";
import { useMoneyManagementMonitoring } from "../features/money-management/hooks/useMoneyManagementMonitoring.js";
import { createMonitoringViewModel } from "../features/money-management/view/moneyManagementMonitoringViewModel.js";
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
    const [selection, setSelection] = useState(null);
    const viewAuthority = selection ?? "PAPER";
    useEffect(() => {
        if (moneyManagement.rawStatus || moneyManagement.statusError || !moneyManagement.isInitialLoading) {
            setSelection((current) => current ?? initialViewAuthority(moneyManagement.rawStatus?.mode));
        }
    }, [moneyManagement.rawStatus, moneyManagement.statusError, moneyManagement.isInitialLoading]);
    const monitoring = useMoneyManagementMonitoring(viewAuthority, selection !== null);
    const monitoringViewModel = createMonitoringViewModel(monitoring);
    const selectView = (authority) => setSelection(requireViewAuthority(authority));
    const refresh = async () => {
        const [runtimeResult] = await Promise.all([moneyManagement.refresh(), monitoring.refresh()]);
        return runtimeResult;
    };
    const viewModel = createMoneyManagementViewModel(moneyManagement);
    const interaction =
        createMoneyManagementInteractionViewModel(moneyManagement);

    return (
        <main className="mi-page mm-page">
            <MoneyManagementHeader
                header={viewModel.header}
                onRefresh={refresh}
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

            <MoneyManagementMonitoringView viewAuthority={viewAuthority} onSelect={selectView} data={monitoring} runtime={moneyManagement.status} />
            <MoneyManagementCapitalDrawdownSection viewAuthority={viewAuthority} history={monitoring} />
            <MoneyManagementTopSummarySection viewModel={monitoringViewModel} />
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
