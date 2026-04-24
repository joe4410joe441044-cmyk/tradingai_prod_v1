from monitoring.system_monitor import SystemMonitor


def run_test():

    monitor = SystemMonitor()

    print("=== START TEST ===")

    # =========================
    # ① statusテスト
    # =========================
    monitor.update_status("backend", True)
    monitor.update_status("trade_core", True)
    monitor.update_status("risk_manager", False)

    print("\n[INTEGRATION CHECK]")
    print(monitor.integration_check())

    # =========================
    # ② eventログテスト
    # =========================
    monitor.log_event("BOT_START", {"status": "ok"})
    monitor.log_event("PRICE_UPDATE", {"price": 100})

    # =========================
    # ③ errorテスト
    # =========================
    monitor.test_error()

    # =========================
    # ④ health確認
    # =========================
    print("\n[HEALTH CHECK]")
    print(monitor.health_check())

    # =========================
    # ⑤ logs確認
    # =========================
    print("\n[LOGS]")
    for log in monitor.get_logs():
        print(log)

    print("=== END TEST ===")


if __name__ == "__main__":
    run_test()