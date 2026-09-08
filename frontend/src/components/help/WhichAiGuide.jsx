import HelpDisclosure from "./HelpDisclosure";

const ROUTES = [
    ["TradingAI全体の現在の運用状態・姿勢・人間注意", "マスター・スーパーバイザー"],
    [
        "資金管理の詳細（資本・リスク・ドローダウン・エクスポージャー・容量・複利）",
        "MMスーパーバイザー",
    ],
    [
        "仕様・設計・原因調査・セカンドオピニオン・「なぜ取引できないか」",
        "AIアドバイザー",
    ],
    ["注文・設定変更・開始/停止・リスク変更", "どのAIも実行できません"],
];

export default function WhichAiGuide() {
    return (
        <div className="ai-help-content">
            <p className="ai-help-intro">
                TradingAIのどのAIに質問すべきかを選ぶための案内です。いずれも「説明・助言」であり、実行はしません。
            </p>
            <dl className="ai-help-which-list">
                {ROUTES.map(([question, answer]) => (
                    <div className="ai-help-which-row" key={question}>
                        <dt>{question}</dt>
                        <dd>→ {answer}</dd>
                    </div>
                ))}
            </dl>
            <HelpDisclosure title="詳しく見る">
                <p>
                    注文の送信・取消、設定変更、Bot/ループの開始・停止、リスク・レバ・エクスポージャーの変更、緊急解除
                    はどのAIも実行できません。必ず決定論的なPython / Governance / Safety、または人間の判断で行います。
                </p>
                <p>
                    TradingAI全体の状態・姿勢 → マスター・スーパーバイザー。資金管理の詳細 → MMスーパーバイザー。
                    仕様・設計・原因調査・セカンドオピニオン → AIアドバイザー。実際の決定・許可・執行は決定論的なTradingAI層が所有します。
                </p>
            </HelpDisclosure>
        </div>
    );
}
