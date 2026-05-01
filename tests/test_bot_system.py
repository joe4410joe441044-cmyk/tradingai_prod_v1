# test_bot_system.py

import os
os.environ["TEST_MODE"] = "1"  # 🔥 テスト時のみ自動ON（最重要）

import time
import requests

BASE = "http://127.0.0.1:8001"


def log(title, data):
    print(f"\n=== {title} ===")
    print(data)


# =========================
# ① 起動
# =========================
def test_start():
    r = requests.post(f"{BASE}/api/bot/start", json={})
    log("START", r.json())


# =========================
# ② 状態取得
# =========================
def test_summary():
    r = requests.get(f"{BASE}/api/bot/summary")
    data = r.json()
    log("SUMMARY", data)

    if data.get("balance") == 1000:
        print("❌ ダミーBalance検出（本番NG）")

    if data.get("status") == "ERROR":
        print("❌ SUMMARY ERROR → engine or API崩壊")

    return data


# =========================
# ③ リスク確認
# =========================
def test_risk():
    r = requests.get(f"{BASE}/api/risk/status")
    data = r.json()
    log("RISK", data)

    if data.get("kill_switch"):
        print("⚠ KillSwitch発動中")

    return data


# =========================
# ④ リセット確認
# =========================
def test_risk_reset():
    r = requests.post(f"{BASE}/api/risk/reset")
    log("RISK RESET", r.json())


# =========================
# ⑤ 擬似注文テスト
# =========================
def test_order():
    r = requests.post(f"{BASE}/api/bot/test_entry")
    log("TEST ORDER", r.json())


# =========================
# ⑥ 価格更新チェック
# =========================
def test_price_flow():
    print("\n=== PRICE FLOW ===")
    prev = None

    for _ in range(5):
        r = requests.get(f"{BASE}/api/bot/summary")
        data = r.json()

        price = data.get("price", 0)
        print("price:", price)

        if prev and price == prev:
            print("⚠ 価格が固定（WS or on_price未発火）")

        prev = price
        time.sleep(1)


# =========================
# ⑦ DD強制テスト
# =========================
def test_force_dd():
    print("\n=== FORCE DD TEST ===")

    r = requests.post(f"{BASE}/api/risk/force_dd", json={
        "initial": 1000,
        "current": 800
    })

    log("FORCE DD", r.json())

    # 状態確認
    time.sleep(1)
    risk = test_risk()

    if not risk.get("kill_switch"):
        print("❌ DD発動していない → ロジック or API未接続")
    else:
        print("✅ DD KillSwitch 正常発動")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    test_start()
    time.sleep(2)

    test_summary()
    test_risk()
    test_price_flow()

    # 🔥 今回の核心
    test_force_dd()

    test_risk_reset()
    test_order()

    print("\n✅ テスト完了")