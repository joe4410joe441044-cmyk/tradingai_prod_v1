# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import time
import webbrowser
import requests
import threading
import re
import socket

# -----------------------------
# パス（🔥 完全相対パス）
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
FRONTEND_DIR = os.path.join(BASE_DIR, "react_dashboard")

FASTAPI_PORT = 8001
FASTAPI_URL = f"http://127.0.0.1:{FASTAPI_PORT}/api/bot/summary"

REACT_DEFAULT_PORT = 5173

BROWSER_OPEN_DELAY = 1.0
REACT_START_RETRIES = 5
FASTAPI_TIMEOUT = 60

# -----------------------------
# FastAPI 起動（🔥 uvicorn直起動）
# -----------------------------
print("🚀 Starting FastAPI...")

fastapi_proc = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(FASTAPI_PORT),
    ],
    cwd=BASE_DIR,
)

# -----------------------------
# FastAPI 起動待機
# -----------------------------
print(f"⏳ Waiting for FastAPI at {FASTAPI_URL} ...")

for _ in range(FASTAPI_TIMEOUT):
    try:
        resp = requests.get(FASTAPI_URL)
        if resp.status_code == 200:
            print("✅ FastAPI is ready!")
            break
    except Exception:
        pass
    time.sleep(1)
else:
    print("❌ FastAPI failed to start")
    fastapi_proc.terminate()
    sys.exit(1)

# -----------------------------
# 空きポート検出
# -----------------------------
def find_free_port(start_port):
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) != 0:
                return port
    return None

# -----------------------------
# React 起動（Vite）
# -----------------------------
def start_react():
    for attempt in range(REACT_START_RETRIES):
        port = find_free_port(REACT_DEFAULT_PORT)

        if port is None:
            print("❌ No free port for React")
            return None, None

        print(f"🚀 Starting React on port {port} (Attempt {attempt+1})")

        env = os.environ.copy()
        env["PORT"] = str(port)

        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=FRONTEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

        url = None
        start_time = time.time()

        while time.time() - start_time < 30:
            line = proc.stdout.readline()
            if not line:
                break

            decoded = line.decode(errors="ignore")
            print(decoded, end="")

            match = re.search(r"http://localhost:\d+", decoded)
            if match:
                url = match.group(0)
                break

        if url:
            print(f"✅ React ready: {url}")
            return proc, url

        print("⚠️ Retry React...")
        proc.terminate()
        time.sleep(2)

    return None, None


react_proc, react_url = start_react()

if not react_proc:
    print("❌ React failed")
    fastapi_proc.terminate()
    sys.exit(1)

# -----------------------------
# ブラウザ起動
# -----------------------------
threading.Timer(
    BROWSER_OPEN_DELAY,
    lambda: webbrowser.open(react_url)
).start()

# -----------------------------
# プロセス監視
# -----------------------------
try:
    fastapi_proc.wait()
    react_proc.wait()
except KeyboardInterrupt:
    print("🛑 Shutting down...")
    fastapi_proc.terminate()
    react_proc.terminate()