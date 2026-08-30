import { lazy, Suspense } from "react";

import MoneyManagementCardShell from "./MoneyManagementCardShell";
import MoneyManagementConfigurationCard from "./MoneyManagementConfigurationCard";
import { ProjectionCard, StatisticsCard } from "./MoneyManagementMetricsCards";

const MoneyManagementSimulationCard = lazy(
    () => import("./MoneyManagementSimulationCard"),
);
const MoneyManagementRuntimeHistoryCard = lazy(
    () => import("./MoneyManagementRuntimeHistoryCard"),
);

export default function MoneyManagementBottomSection({
    interaction,
    moneyManagement,
    viewModel,
}) {
    return (
        <div className="mm-lower-sections">
            <section
                aria-labelledby="mm-analysis-heading"
                className="mm-section-group"
            >
                <h2 className="mm-section-title" id="mm-analysis-heading">
                    Configuration / Analysis
                </h2>
                <StatisticsCard viewModel={viewModel} />
                <details className="mm-disclosure">
                    <summary className="mm-disclosure__summary-row">
                        <span>Configuration（設定）</span>
                        <span className="mm-disclosure__meta">
                            {interaction.configuration.draftStatus} · Revision {interaction.configuration.revision}
                        </span>
                    </summary>
                    <div className="mm-disclosure__content">
                        <MoneyManagementConfigurationCard
                            draft={moneyManagement.configurationDraft}
                            interaction={interaction}
                            onDraftChange={moneyManagement.updateConfigurationDraft}
                            onReset={moneyManagement.resetConfigurationDraft}
                            onSave={moneyManagement.saveConfiguration}
                        />
                    </div>
                </details>
                <details className="mm-disclosure">
                    <summary>Simulation（シミュレーション）</summary>
                    <div className="mm-disclosure__content">
                        <Suspense fallback={(
                            <MoneyManagementCardShell loading title="Simulation" />
                        )}>
                            <MoneyManagementSimulationCard configuration={moneyManagement.configuration} />
                        </Suspense>
                    </div>
                </details>
                <ProjectionCard viewModel={viewModel} />
            </section>
            <section
                aria-labelledby="mm-history-heading"
                className="mm-section-group"
            >
                <h2 className="mm-section-title" id="mm-history-heading">
                    History / Diagnostics
                </h2>
                <details className="mm-disclosure">
                    <summary>Runtime History（実行履歴）</summary>
                    <div className="mm-disclosure__content">
                        <Suspense fallback={(
                            <MoneyManagementCardShell
                                loading
                                title="Runtime History"
                            />
                        )}>
                            <MoneyManagementRuntimeHistoryCard />
                        </Suspense>
                    </div>
                </details>
            </section>
        </div>
    );
}
