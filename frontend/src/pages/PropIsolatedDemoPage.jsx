import OfflinePropWorkflow from "../components/prop-accounts/OfflinePropWorkflow.jsx";
import "../components/prop-accounts/prop-accounts.css";
import { syntheticPropEvaluationClient } from "../features/prop-accounts/syntheticPropEvaluationClient.js";

export default function PropIsolatedDemoPage() {
    return (
        <main className="cc-prop-accounts" data-testid="prop-isolated-demo-page">
            <section className="cc-prop-accounts__hero" role="status">
                <span className="cc-prop-accounts__eyebrow">DEFAULT OFF · ISOLATED DEMO</span>
                <h1>PROP隔離デモ</h1>
                <p>架空データ専用です。実口座・通常口座・runtime・注文権限・公式ルールとは接続しません。</p>
                <strong>SYNTHETIC / NOT OFFICIAL / NO EXECUTION AUTHORITY</strong>
                <ul>
                    <li>入力と評価はsyntheticであり、実口座残高・取引結果ではありません。</li>
                    <li>実口座の登録・接続、注文権限の付与は行いません。</li>
                    <li>入力・口座・結果は永続保存されず、operator session終了後に再利用されません。</li>
                </ul>
            </section>
            <OfflinePropWorkflow client={syntheticPropEvaluationClient} />
        </main>
    );
}
