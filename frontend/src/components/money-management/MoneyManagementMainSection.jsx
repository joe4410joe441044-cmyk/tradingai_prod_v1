import MoneyManagementRiskStateCard from "./MoneyManagementRiskStateCard";
import MoneyManagementRecoveryCard from "./MoneyManagementRecoveryCard";
import MoneyManagementPositionSizingCard from "./MoneyManagementPositionSizingCard";

export default function MoneyManagementMainSection({
    interaction,
    moneyManagement,
    viewModel,
}) {
    return (
        <section aria-labelledby="mm-operation-heading" className="mm-section-group">
            <h2 className="mm-section-title" id="mm-operation-heading">
                Operation / Decision
            </h2>
            <div className="mm-main">
                <MoneyManagementRiskStateCard viewModel={viewModel} />
                <div aria-label="Position sizing and recovery" className="mm-card-column">
                    <MoneyManagementPositionSizingCard viewModel={viewModel} />
                    <MoneyManagementRecoveryCard
                        interaction={interaction}
                        isRecovering={moneyManagement.isRecovering}
                        onRecover={moneyManagement.recover}
                    />
                </div>
            </div>
        </section>
    );
}
