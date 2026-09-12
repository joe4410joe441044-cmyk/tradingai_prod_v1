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
                <div role="group" aria-label="Monitoring View authority" className="mm-analytics-periods">
                    {VIEW_AUTHORITIES.map((authority) => (
                        <button type="button" key={authority} aria-pressed={viewAuthority === authority} onClick={() => onSelect(authority)}>
                            {authority}
                        </button>
                    ))}
                </div>
            </div>
            <p>監視データの表示のみを切り替えます。実稼働・取引権限は変更しません。</p>
            <p>Actual Runtime（実稼働）: {runtime?.mode ?? "UNKNOWN"} / {runtime?.lifecycleState ?? "UNKNOWN"}</p>
            <div role={data.monitoringState === "ERROR" ? "alert" : "status"}>
                <strong>{viewAuthority} Monitoring — {LABELS[data.monitoringState]}</strong>
                <p>Source: {data.monitoring?.source ?? "—"} / {data.monitoring?.snapshot?.accountingAuthoritySource ?? "—"}</p>
                <p>As of（記録時刻）: {data.monitoring?.asOf ?? "—"}</p>
                <p>以下のグラフ・サマリーは {viewAuthority} の記録です。現在のエントリー許可を示すものではありません。</p>
            </div>
        </section>
    );
}
