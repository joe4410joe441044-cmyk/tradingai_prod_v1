import HelpDisclosure from "./HelpDisclosure";

const FACTS = [
    ["得意", "TradingAI状態、資金管理（MM）状態、仕様・設計の説明、なぜ取引できないか。"],
    ["根拠", "承認済みナレッジ（仕様）＋読み取り専用ランタイム数値＋AIの説明。"],
    ["信頼度", "ソース付きの「事実」が最強。「推論」はAIの判断。「不明」は取得できない状態。未確定を「正常・安全」にしない。"],
    ["できない", "注文、設定変更、Bot開始/停止、MM変更、緊急解除、利益保証、未来予測、外部情報。"],
    ["どこへ？", "全体の運用姿勢→Master。資金管理の詳細→MM。"],
];

export default function AdvisorGuide() {
    return (
        <div className="ai-help-content">
            <p className="ai-help-intro">
                AIアドバイザー（AI Advisor）は「読み取り専用の研究・分析パートナー」です。現状把握・原因調査・仕様理解・セカンドオピニオンを説明します。実行や変更は一切しません。
            </p>
            <dl className="ai-help-facts">
                {FACTS.map(([label, value]) => (
                    <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value}</dd>
                    </div>
                ))}
            </dl>
            <HelpDisclosure title="何が得意か・何を聞けるか">
                <p>
                    現在のTradingAI状態（Bot / Loop / Auto Trade / Governance / Emergency / Market / MM）の説明、Money Management状態の評価、仕様・設計・運用手順の意味、
                    「なぜ取引を開始できないか」「何が欠けているか」、意思決定の見直し・セカンドオピニオン、改善提案・事後的な仕組みの説明ができます。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="どこまで信頼できるか（回答の根拠）">
                <p>
                    根拠：①承認済み・ハッシュ検証済みのTradingAI仕様（Constitution、各マスター仕様など6ソース）
                    ②読み取り専用のランタイム数値（Bot / Governance / Emergency / Market / MM）
                    ③AIによる説明・推論。現在値は取得できた場合のみで、取得できない/古い場合はUNKNOWN/STALEとして伝えます。
                </p>
                <p>
                    「事実（facts）」はソースに直結し最も信頼できます。「推論（inferences）」はAIの判断で不確実性（低/中/高）が付きます。
                    「不明（unknowns）」は「今の権威データでは確定できない」＝異常ではありません。最終的な計算・許可・執行は決定論的なPython / Governance / Safety / Executionが所有します。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="UNKNOWN / STALEとは">
                <p>
                    「UNKNOWN（不明）」＝「壊れている」ではなく「いま取得できる正式な権威データではここを確定できません」。未確定を「正常・安全・準備完了」に読み替えません。
                </p>
                <p>
                    「STALE（古い）」＝「過去のある時点で取得・記録された値」であり「いまの値」ではありません。古いランタイム値を現在の健康な証拠として扱うのは避けてください。
                </p>
            </HelpDisclosure>
            <HelpDisclosure title="質問例">
                <p>「現在のTradingAI全体の状態を整理して。Bot、Loop、Auto Trade、Governance、Emergency、Market、Money Managementを確認して。」</p>
                <p>「現在のMoney Management状態を評価して。利用可能資金、Exposure、Position Capacity、Drawdown、Ruin Guard、Compounding、新規エントリー可否を確認して。」</p>
                <p>「Money ManagementがNORMALなら、市場も安定していて安心して取引できる、という理解で正しいですか？」</p>
                <p>「なぜ取引を開始できないのか、重要な順に説明して。」</p>
            </HelpDisclosure>
            <HelpDisclosure title="できないこと（実行境界）">
                <p>
                    注文・設定変更・Bot開始/停止・MM変更・緊急解除・ガバナンス上書き・利益保証・未来予測・外部情報・実際の取引データ分析・コードベース全体検索は行いません。
                </p>
                <p>どれか別のAIへ：全体の運用状態・姿勢 → Master。資金管理の詳細 → MM。なお、どれも「実行」はしません。</p>
            </HelpDisclosure>
        </div>
    );
}
