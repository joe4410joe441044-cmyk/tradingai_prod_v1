# tools/position_calculator.py

def safe_float_input(prompt):
    while True:
        try:
            value = input(prompt).replace(",", "").strip()
            return float(value)
        except ValueError:
            print("⚠️ 数値で入力してください（例: 1000 / 79,000）")


def calc_qty(balance, risk_pct, price, sl_pct, leverage):
    if sl_pct <= 0:
        raise Exception("🚨 損切り幅は0より大きくしてください")

    risk_amount = balance * (risk_pct / 100)
    qty = risk_amount / (price * (sl_pct / 100))

    position_value = qty * price
    required_margin = position_value / leverage
    usage_pct = (required_margin / balance) * 100

    return {
        "qty": qty,
        "position_value": position_value,
        "required_margin": required_margin,
        "risk_amount": risk_amount,
        "usage_pct": usage_pct
    }


def evaluate_usage(usage):
    if usage < 20:
        return "⚠️ 低すぎ（資金余りすぎ）"
    elif 20 <= usage < 40:
        return "🟡 やや低い（安全寄り）"
    elif 40 <= usage <= 70:
        return "🟢 最適ゾーン"
    elif 70 < usage <= 90:
        return "🟠 やや高い（注意）"
    else:
        return "🔴 危険（ロスカット近い）"


def simulate():
    print("\n=== トレードシミュレーション（RR対応） ===\n")

    balance = safe_float_input("初期資金 (USDT): ")
    risk_pct = safe_float_input("リスク (%): ")
    sl_pct = safe_float_input("損切り幅 (%): ")
    leverage = safe_float_input("レバレッジ: ")
    rr = safe_float_input("RR（利確倍率 例: 2 = リスクの2倍利益）: ")

    trade_count = 0
    win_count = 0
    loss_count = 0

    while True:
        price = safe_float_input("\nBTC価格: ")

        result = calc_qty(balance, risk_pct, price, sl_pct, leverage)

        print("\n--- トレード情報 ---")
        print(f"現在資金: {balance:.2f} USDT")
        print(f"qty: {result['qty']:.6f} BTC")
        print(f"ポジション: {result['position_value']:,.2f} USDT")
        print(f"証拠金: {result['required_margin']:,.2f} USDT")
        print(f"使用率: {result['usage_pct']:.2f}% → {evaluate_usage(result['usage_pct'])}")
        print(f"リスク額: {result['risk_amount']:.2f} USDT")
        print(f"想定利益（RR適用）: {result['risk_amount'] * rr:.2f} USDT")

        action = input("\n結果 (w=勝ち / l=負け / q=終了): ").lower()

        if action == "w":
            profit = result["risk_amount"] * rr
            balance += profit
            win_count += 1
            trade_count += 1
            print(f"✅ 勝ち +{profit:.2f} → 資金: {balance:.2f}")

        elif action == "l":
            loss = result["risk_amount"]
            balance -= loss
            loss_count += 1
            trade_count += 1
            print(f"❌ 負け -{loss:.2f} → 資金: {balance:.2f}")

        elif action == "q":
            break
        else:
            print("⚠️ 無効入力")
            continue

        # 簡易統計
        if trade_count > 0:
            win_rate = (win_count / trade_count) * 100
            print(f"\n--- 統計 ---")
            print(f"トレード数: {trade_count}")
            print(f"勝率: {win_rate:.2f}%")
            print(f"勝ち: {win_count} / 負け: {loss_count}")

        if balance <= 0:
            print("💀 資金ゼロ → 破産")
            break


if __name__ == "__main__":
    simulate()