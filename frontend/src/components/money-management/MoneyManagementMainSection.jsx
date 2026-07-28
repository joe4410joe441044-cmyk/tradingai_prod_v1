import MoneyManagementConfigurationCard from "./MoneyManagementConfigurationCard";
import {
    PerformanceCard,
    ProjectionCard,
    StatisticsCard,
} from "./MoneyManagementMetricsCards";
import MoneyManagementRiskStateCard from "./MoneyManagementRiskStateCard";
import MoneyManagementRecoveryCard from "./MoneyManagementRecoveryCard";
import MoneyManagementPositionSizingCard from "./MoneyManagementPositionSizingCard";

export default function MoneyManagementMainSection({
    interaction,
    moneyManagement,
    viewModel,
}) {
    return (
        <section aria-label="Money Management main area" className="mm-main">
            <div aria-label="Risk and controls" className="mm-card-column">
                <MoneyManagementRiskStateCard viewModel={viewModel} />
                <MoneyManagementConfigurationCard
                    draft={moneyManagement.configurationDraft}
                    interaction={interaction}
                    onDraftChange={moneyManagement.updateConfigurationDraft}
                    onReset={moneyManagement.resetConfigurationDraft}
                    onSave={moneyManagement.saveConfiguration}
                />
                <MoneyManagementRecoveryCard
                    interaction={interaction}
                    isRecovering={moneyManagement.isRecovering}
                    onRecover={moneyManagement.recover}
                />
                <MoneyManagementPositionSizingCard viewModel={viewModel} />
            </div>
            <div
                aria-label="Performance and projection"
                className="mm-card-column"
            >
                <PerformanceCard viewModel={viewModel} />
                <StatisticsCard viewModel={viewModel} />
                <ProjectionCard viewModel={viewModel} />
            </div>
        </section>
    );
}
