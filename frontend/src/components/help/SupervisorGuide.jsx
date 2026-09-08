import { useState } from "react";

import HelpDisclosure from "./HelpDisclosure";

function MasterGuideContent() {
    return (
        <div className="ai-help-content">
            <p className="ai-help-intro">
                TradingAI全体の運用監督。現在の状態・姿勢・人間が確認すべき点を「SHADOW（影・観察）」として説明・助言します。
            </p>
            <p className="ai-help-note">
                得意：全体状態、overall posture、取引の継続/縮小/停止の提案、人間注意、横断的な見方（MM+Market）。信頼度：構造化された監督的見解＝説明・推奨。会話回答はプロバイダーが有効な場合のみ。
            </p>
            <HelpDisclosure title="詳しく見る">
                <p>
                    SHADOW（現在のモード）の意味：観察・説明のみ。監視しながら「影」として評価・提案するだけで、実行・変更・注文は一切しません。
                    ADVISORY / ACTIVEへの昇格はなく、意図的にSHADOWに固定されています。実際の計算・許可・執行は決定論的Python（MM / Governance / Hard Safety / Execution）が所有します。
                </p>
                <p>
                    MM Supervisorとの関係：Masterは必ずMM評価を認証・バインディングして取り込みます。MMがUNKNOWNならMasterはUNKNOWN/一時停止のみで、正常にはしません。MMを越えてリスクを大きくしません。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="質問例">
                <p>「今TradingAI全体はどういう状態？」</p>
                <p>「現在のoverall postureは？」</p>
                <p>「取引を継続すべきか、縮小すべきか、停止すべきか？」</p>
                <p>「人間が確認すべきことは何？」</p>
            </HelpDisclosure>
            <HelpDisclosure title="できないこと（実行境界）">
                <p>
                    注文・ポジション変更・数量計算・リスク/レバ/エクスポージャー/レジーム/MM設定変更・Governance変更・Emergency解除・自動売買/Loop/モード/銘柄変更・設定変更・上書き・憲章書き換えはしません。
                </p>
                <p>どこへ？ 資金管理の詳細 → MM。設計・原因調査 → AI Advisor。</p>
            </HelpDisclosure>
        </div>
    );
}

function MMGuideContent() {
    return (
        <div className="ai-help-content">
            <p className="ai-help-intro">
                資金管理の専門監督役。資本・リスク・ドローダウン・エクスポージャー・ポジション容量・複利・Ruin Guardを権威あるMMデータで評価・説明します（SHADOW・読み取り専用）。
            </p>
            <p className="ai-help-note">
                資本が健全でも全体MMがNORMALとは限りません。UNKNOWNはそのままUNKNOWNです。ドローダウンは0.08=0.08%（8%ではない）。現在/残り/上限エクスポージャーは別物。
            </p>
            <HelpDisclosure title="詳しく見る">
                <p>
                    評価する項目：資本（equity / availableCapital / capitalSource）、リスク予算、現在のMM状態（NORMAL / CAUTION / DEFENSIVE / LOCKED / UNKNOWN）、ドローダウン（既に%）、現在/残りエクスポージャー、ポジション容量、Ruin Guard、Compounding、データ鮮度・理由コード、リスク方向の助言。
                </p>
                <p>
                    資金管理の権威：数値・状態はMM権威（MoneyManagementHttpBoundary）の読み取り。このAIは再計算せず、本物をそのまま提示します。実際の資金管理計算・設定・執行は決定論的なPython Money Management / Governance / Safety / Executionが所有します。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="質問例">
                <p>「現在の資金管理状態は？」</p>
                <p>「Exposureとremaining exposureは？」</p>
                <p>「Drawdownは？」</p>
                <p>「なぜUNKNOWNなのか？何が改善すれば状態が戻る？」</p>
            </HelpDisclosure>
            <HelpDisclosure title="できないこと（実行境界）">
                <p>
                    リスク%・レバ・エクスポージャー・レジーム・サイズ・Compounding・Ruin Guardの変更、Governance/Execution制御、注文・資金移動、MM計算の再実装・値の捏造、実際の「何ロット」の算出はしません。
                </p>
                <p>どこへ？ TradingAI全体・姿勢 → Master。設計・仕様・原因調査 → AI Advisor。</p>
            </HelpDisclosure>
        </div>
    );
}

function UnknownGuideContent() {
    return (
        <div className="ai-help-content">
            <p className="ai-help-intro">
                表示される状態の読み方と、権威（Authority）の範囲についての共通説明です。
            </p>
            <HelpDisclosure title="「UNKNOWN（不明）」とは">
                <p>
                    「壊れている」という意味ではありません。「いま取得できる正式な権威データでは、ここを確定できません」という意味です。仕様・設計・運用手順（知識）は存在するので、それに基づく説明はできます。確定・実行できる状態かどうかは未定です。
                </p>
                <p>
                    例：資金が100あり、Position Capacityが1でも、全体のMM評価がUNKNOWNなら「MMはNORMAL」とは言えません。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="「STALE（古い）」とは">
                <p>
                    「過去のある時点で取得・記録された値」であり、「いまの値」ではありません。古いランタイム値を、現在の健康な証拠として扱うのは避けてください。古いから数字で安堵せず、最新の正式表示で確認してください。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="数値はあるのに状態がUNKNOWN">
                <p>
                    その数値（例：利用可能資金）は資本・適格性の権威値として取得できていますが、全体のMM状態（riskState / metricsStatus / blockReasons）は別の権威で、そちらが未確定という意味です。つまり「資本が健全」＝「全体がNORMAL」ではありません。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="どの値がAuthority（権威）か">
                <p>
                    全体のMM状態：権威あるMM評価（mmRiskState / mmAvailable / mmMetricsStatus / mmSafeReason / mmBlockReasons / mmExecutionEntryAllowed）。
                </p>
                <p>資本・適格性：capitalAuthority / capitalSource / equity / availableCapital / remainingExposure / positionCapacity / riskBudget。</p>
                <p>ドローダウン：0.08 は 0.08%（0.282405 は 0.282405%）で、100倍しない。</p>
                <p>エクスポージャー：現在 / 残り / 上限 は別物。</p>
            </HelpDisclosure>
        </div>
    );
}

const SECTIONS = {
    master: "Master Supervisor（マスター・スーパーバイザー）",
    mm: "MM Supervisor（MMスーパーバイザー）",
    unknown: "UNKNOWN / STALE / 権威（Authority）",
};

export default function SupervisorGuide({ focusSection }) {
    const [open, setOpen] = useState(() => ({
        master: focusSection === "master",
        mm: focusSection === "mm",
        unknown: false,
    }));
    const toggle = (name) => () => setOpen((previous) => ({ ...previous, [name]: !previous[name] }));

    return (
        <div className="ai-help-content">
            <p className="ai-help-intro">
                スーパーバイザーの読み方・信頼できる範囲の説明です。Master / MMともにSHADOWで、実行・変更はしません。
            </p>
            <HelpDisclosure
                title={SECTIONS.master}
                open={open.master}
                onToggle={toggle("master")}
            >
                <MasterGuideContent />
            </HelpDisclosure>
            <HelpDisclosure
                title={SECTIONS.mm}
                open={open.mm}
                onToggle={toggle("mm")}
            >
                <MMGuideContent />
            </HelpDisclosure>
            <HelpDisclosure
                title={SECTIONS.unknown}
                open={open.unknown}
                onToggle={toggle("unknown")}
            >
                <UnknownGuideContent />
            </HelpDisclosure>
        </div>
    );
}
