import { useState } from "react";

import MMSupervisorSection from "../components/supervisor/MMSupervisorSection";
import SupervisorConversationShell from "../components/supervisor/SupervisorConversationShell";
import SupervisorDetailsDisclosure from "../components/supervisor/SupervisorDetailsDisclosure";
import SupervisorOverview from "../components/supervisor/SupervisorOverview";
import {
    AiHelpDrawer,
    AiHelpLauncher,
    SupervisorGuide,
    WhichAiGuide,
} from "../components/help/AiHelp";
import "../styles/supervisor.css";

export default function SupervisorPage() {
    const [helpDrawer, setHelpDrawer] = useState(null);
    const [guideSection, setGuideSection] = useState(null);

    const closeHelp = () => setHelpDrawer(null);
    const openWhichAi = () => setHelpDrawer("which-ai");
    const openSupervisorGuide = () => {
        setGuideSection(null);
        setHelpDrawer("supervisor-guide");
    };
    const requestSupervisorHelp = (section) => {
        setGuideSection(section);
        setHelpDrawer("supervisor-guide");
    };

    return (
        <main className="supervisor-page">
            <div className="ai-help-dock">
                <AiHelpLauncher
                    side="left"
                    label="どのAIに聞く？"
                    expanded={helpDrawer === "which-ai"}
                    controls="supervisor-which-ai-drawer"
                    onToggle={helpDrawer === "which-ai" ? closeHelp : openWhichAi}
                />
                <AiHelpLauncher
                    side="right"
                    label="Supervisor ガイド"
                    expanded={helpDrawer === "supervisor-guide"}
                    controls="supervisor-guide-drawer"
                    onToggle={helpDrawer === "supervisor-guide" ? closeHelp : openSupervisorGuide}
                />
            </div>

            <header className="supervisor-page__header">
                <h1>Supervisor</h1>
                <span className="supervisor-page__mode" aria-label="Supervisor mode: Shadow, read only">
                    SHADOW · READ ONLY
                </span>
            </header>

            <SupervisorOverview />

            <section className="supervisor-page__primary" aria-labelledby="master-supervisor-heading">
                <div className="supervisor-page__section-heading">
                    <div className="supervisor-page__section-heading-text">
                        <h2 id="master-supervisor-heading">MASTER SUPERVISOR</h2>
                        <button
                            type="button"
                            className="supervisor-heading-help"
                            aria-label="Master Supervisor ヘルプを開く"
                            onClick={() => requestSupervisorHelp("master")}
                        >
                            ?
                        </button>
                    </div>
                    <span className="supervisor-page__connection-state">SHADOW API</span>
                </div>
                <SupervisorConversationShell
                    supervisorName="Master Supervisor"
                    agentId="MASTER_SUPERVISOR"
                />
            </section>

            <div className="supervisor-page__secondary" aria-label="Specialist supervisors">
                <MMSupervisorSection onRequestSupervisorHelp={requestSupervisorHelp} />
            </div>

            <SupervisorDetailsDisclosure />

            <AiHelpDrawer
                id="supervisor-which-ai-drawer"
                side="left"
                open={helpDrawer === "which-ai"}
                title="どのAIに聞く？"
                onClose={closeHelp}
            >
                <WhichAiGuide />
            </AiHelpDrawer>

            <AiHelpDrawer
                id="supervisor-guide-drawer"
                side="right"
                open={helpDrawer === "supervisor-guide"}
                title="Supervisor ガイド"
                onClose={closeHelp}
            >
                <SupervisorGuide key={guideSection || "overview"} focusSection={guideSection} />
            </AiHelpDrawer>
        </main>
    );
}
