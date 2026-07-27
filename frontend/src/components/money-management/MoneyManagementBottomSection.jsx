import MoneyManagementCardShell from "./MoneyManagementCardShell";
import { MONEY_MANAGEMENT_BOTTOM_CARDS } from "./moneyManagementLayout";

export default function MoneyManagementBottomSection() {
    return (
        <section
            aria-label="Money Management bottom area"
            className="mm-bottom"
        >
            {MONEY_MANAGEMENT_BOTTOM_CARDS.map((title) => (
                <MoneyManagementCardShell key={title} title={title} />
            ))}
        </section>
    );
}
