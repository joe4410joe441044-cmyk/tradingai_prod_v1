import MMSupervisorSection from "../components/supervisor/MMSupervisorSection";
import SupervisorConversationShell from "../components/supervisor/SupervisorConversationShell";
import SupervisorDetailsDisclosure from "../components/supervisor/SupervisorDetailsDisclosure";
import SupervisorOverview from "../components/supervisor/SupervisorOverview";
import "../styles/supervisor.css";

export default function SupervisorPage() {
    return (
        <main className="supervisor-page">
            <header className="supervisor-page__header">
                <h1>Supervisor</h1>
                <span className="supervisor-page__mode" aria-label="Supervisor mode: Shadow, read only">
                    SHADOW · READ ONLY
                </span>
            </header>

            <SupervisorOverview />

            <section className="supervisor-page__primary" aria-labelledby="master-supervisor-heading">
                <div className="supervisor-page__section-heading">
                    <h2 id="master-supervisor-heading">MASTER SUPERVISOR</h2>
                    <span className="supervisor-page__connection-state">SHADOW API</span>
                </div>
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
