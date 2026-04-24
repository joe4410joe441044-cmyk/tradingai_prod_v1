import time
import traceback

print("===================================")
print("🚀 BOT ONLY TEST START (NO REDIS)")
print("===================================")

# =========================
# ① IMPORT TEST
# =========================
print("\n[1] Import Test...")

try:
    from backend.bot_manager import BotManager
    print("✅ Import OK")
except Exception as e:
    print("❌ Import Failed")
    traceback.print_exc()
    exit()

# =========================
# ② BOT START
# =========================
print("\n[2] Bot Start Test...")

try:
    bot = BotManager()
    bot.start()
    time.sleep(2)

    status = bot.get_status()

    if status["running"]:
        print("✅ Bot Running")
    else:
        print("❌ Bot Not Running")
        exit()

except Exception as e:
    print("❌ Bot Start Failed")
    traceback.print_exc()
    exit()

# =========================
# ③ PRICE FLOW TEST
# =========================
print("\n[3] Price Flow Test...")

try:
    for i in range(5):
        price = 70000 + i * 10
        bot.set_price("BTCUSDT", price)
        print(f"Injected price: {price}")
        time.sleep(1)

    current_price = bot.get_price()

    if current_price > 0:
        print(f"✅ Price Flow OK: {current_price}")
    else:
        print("❌ Price not updated")
        exit()

except Exception as e:
    print("❌ Price Flow Failed")
    traceback.print_exc()
    exit()

# =========================
# ④ LOG TEST
# =========================
print("\n[4] Log Test...")

logs = bot.get_logs()

if logs:
    print("✅ Logs OK")
    for l in logs[-5:]:
        print(l)
else:
    print("⚠️ No logs")

# =========================
# ⑤ POSITION TEST
# =========================
print("\n[5] Position Test...")

positions = bot.get_positions()

print("Positions:", positions)

# =========================
# FINISH
# =========================
print("\n===================================")
print("🎉 BOT TEST COMPLETED")
print("===================================")