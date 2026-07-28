import { lazy, Suspense } from "react";

import MoneyManagementCardShell from "./MoneyManagementCardShell";
import { MONEY_MANAGEMENT_BOTTOM_CARDS } from "./moneyManagementLayout";

const MoneyManagementSimulationCard = lazy(
    () => import("./MoneyManagementSimulationCard"),
);
const MoneyManagementRuntimeHistoryCard = lazy(
    () => import("./MoneyManagementRuntimeHistoryCard"),
);

export default function MoneyManagementBottomSection({ configuration }) {
    return (
        <section
            aria-label="Money Management bottom area"
            className="mm-bottom"
        >
            <Suspense
                fallback={(
                    <MoneyManagementCardShell loading title="Simulation" />
                )}
            >
                <MoneyManagementSimulationCard
                    configuration={configuration}
                />
            </Suspense>
            <Suspense
                fallback={(
                    <MoneyManagementCardShell loading title="Runtime History" />
                )}
            >
                <MoneyManagementRuntimeHistoryCard />
            </Suspense>
            {MONEY_MANAGEMENT_BOTTOM_CARDS
                .filter((title) => ![
                    "Timeline",
                    "History",
                    "Future Chart",
                ].includes(title))
                .map((title) => (
                <MoneyManagementCardShell key={title} title={title} />
            ))}
        </section>
    );
}
