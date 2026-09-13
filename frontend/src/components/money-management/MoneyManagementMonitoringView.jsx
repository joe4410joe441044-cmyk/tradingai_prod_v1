import { VIEW_AUTHORITIES } from "../../features/money-management/contracts/moneyManagementMonitoringContracts.js";

const LABELS = {
    LOADING: "LOADING（読込中）",
    LAST_KNOWN: "LAST_KNOWN（最終記録）",
    STALE: "STALE（更新停止中・最終記録）",
    UNAVAILABLE: "UNAVAILABLE（データなし）",
    ERROR: "REQUEST ERROR（取得失敗）",
};
export default function MoneyManagementMonitoringView({ viewAuthority, onSelect, data, runtime }) {
    return (
        <section aria-label="Monitoring View" className="mm-monitoring-view">
            <div className="mm-analytics-header">
                <h2 className="mm-section-title">Monitoring View（監視対象）</h2>
                <div role="group" aria-label="Monitoring View authority" className="operation-prep-segmented">
                    {VIEW_AUTHORITIES.map((authority) => (
                        <button
                            type="button"
                            key={authority}
                            aria-pressed={viewAuthority === authority}
                            className={viewAuthority === authority ? "is-selected" : ""}
                            onClick={() => onSelect(authority)}
                        >
                            {authority}
                        </button>
                    ))}
                </div>
            </div>
            <details className="mm-disclosure">
                <summary>Monitoring View の説明（使い方・表示の意味）</summary>
                <div className="mm-disclosure__content">
                    <h3>現在の状態</h3>
                    <div role={data.monitoringState === "ERROR" ? "alert" : "status"}>
                        <p>Actual Runtime（実稼働）: {runtime?.mode ?? "UNKNOWN"} / {runtime?.lifecycleState ?? "UNKNOWN"}</p>
                        <p>Monitoring View: {viewAuthority}</p>
                        <p>Monitoring Status: {viewAuthority} Monitoring — {LABELS[data.monitoringState]}</p>
                        <p>Source: {data.monitoring?.source ?? "—"} / {data.monitoring?.snapshot?.accountingAuthoritySource ?? "—"}</p>
                        <p>As of（記録時刻）: {data.monitoring?.asOf ?? "—"}</p>
                    </div>

                    <h3>Monitoring Viewについて</h3>
                    <p>Monitoring View は、MONEY MANAGEMENTで表示する監視・履歴データをPAPERまたはLIVEに切り替える機能です。このPAPER / LIVEボタンは「取引モードを変更するボタン」ではありません。切り替わるのは、MMで表示する監視・履歴データだけです。</p>

                    <h3>DashboardのPAPER / LIVEとの違い</h3>
                    <p>Dashboard &gt; TRADE SETTINGS &gt; TRADING MODE のPAPER / LIVEは、BOTを次回STARTするときの取引モードを設定します。一方、MONEY MANAGEMENTのPAPER / LIVEは「どちらのMMデータを見るか」を選択します。この2つは独立しています。</p>
                    <p>DashboardでLIVEを選択しても、MM Monitoring Viewが自動的にLIVEへ切り替わるわけではありません。MMでLIVEを選択しても、Dashboardの取引モードや実際のRuntimeをLIVEへ変更することはありません。</p>

                    <h3>Actual Runtimeについて</h3>
                    <p>Actual Runtime（実稼働）は、現在Trading Runtimeが実際にどの状態にあるかを表示します。監視対象を選ぶMonitoring Viewとは別です。</p>
                    <p>たとえば、Actual Runtimeが「PAPER / RUNNING」で、Monitoring Viewが「LIVE」という組み合わせも正常です。この場合、実際の取引RuntimeはPAPERで動作していますが、MM画面ではLIVE側の記録を確認しています。</p>
                    <p>Monitoring Viewを切り替えても、BOT START / STOP、注文、ポジション、取引権限、実稼働モードは変更されません。</p>

                    <h3>PAPER / LIVEデータについて</h3>
                    <p>PAPERとLIVEのMMデータは別々に扱われます。PAPERを選択するとPAPERの、LIVEを選択するとLIVEのCapital / Risk / Exposure / Performance / グラフ / MM履歴を表示します。</p>
                    <p>LIVEデータが存在しない場合、PAPERの値をLIVEとして代用せず、UNAVAILABLE（利用不可）や「No LIVE MM history available（履歴データなし）」などと表示されます。データがないことを示す表示であり、それだけで故障を意味するものではありません。</p>

                    <h3>Monitoring Statusについて</h3>
                    <ul>
                        <li><strong>CURRENT：</strong>現在のMonitoringデータが利用可能です。</li>
                        <li><strong>LAST_KNOWN：</strong>現在値ではなく、最後に正常に記録されたデータを表示しています。</li>
                        <li><strong>STALE：</strong>最後の記録は存在しますが、現在は更新されていない、または一定時間以上更新されていません。</li>
                        <li><strong>UNAVAILABLE：</strong>選択したPAPER / LIVEについて、表示できるMonitoringデータがありません。</li>
                    </ul>
                    <p>Sourceは表示データの出所、As of（記録時刻）はそのデータが記録された時刻です。</p>

                    <h3>重要：監視表示と取引許可は別です</h3>
                    <p>以下のグラフ・サマリーは、現在選択している {viewAuthority} の記録です。Capital / Risk / Exposure / Performance / Graph / Historyは監視・分析用の表示であり、現在のエントリー許可を示すものではありません。これらの表示だけを見て、現在LIVE注文が許可されていると判断しないでください。</p>
                    <p>実際の取引可否・Entry Permission・Runtime Authorityは、Actual RuntimeおよびTrading Runtime側のauthoritative state（取引権限の正となる状態）に従います。</p>
                </div>
            </details>
        </section>
    );
}
