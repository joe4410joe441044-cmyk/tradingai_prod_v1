import MMSupervisorSection from "../components/supervisor/MMSupervisorSection";
import SupervisorConversationShell from "../components/supervisor/SupervisorConversationShell";
import SupervisorDetailsDisclosure from "../components/supervisor/SupervisorDetailsDisclosure";
import SupervisorOverview from "../components/supervisor/SupervisorOverview";
import "../styles/supervisor.css";

export default function SupervisorPage() {
    return (
        <main className="supervisor-page">
            <header className="supervisor-page__header">
                <div>
                    <p className="supervisor-page__eyebrow">TRADINGAI OVERSIGHT</p>
                    <h1>SUPERVISOR</h1>
                </div>
                <span className="supervisor-page__mode" aria-label="Supervisor mode: Shadow">
                    MODE: SHADOW
                </span>
            </header>

            <SupervisorOverview />

            <section className="supervisor-page__primary" aria-labelledby="master-supervisor-heading">
                <div className="supervisor-page__section-heading">
                    <div>
                        <p className="supervisor-page__section-kicker">PRIMARY SUPERVISOR</p>
                        <h2 id="master-supervisor-heading">MASTER SUPERVISOR</h2>
                    </div>
                    <span className="supervisor-page__connection-state">SHADOW API</span>
                </div>
                <p className="supervisor-page__description">
                    TradingAI全体の状態や総合判断について質問できます。
                </p>
                <SupervisorConversationShell
                    supervisorName="Master Supervisor"
                    agentId="MASTER_SUPERVISOR"
                />
            </section>

            <div className="supervisor-page__secondary" aria-label="Specialist supervisors">
                <MMSupervisorSection />
            </div>

            <SupervisorDetailsDisclosure />
        </main>
    );
}
