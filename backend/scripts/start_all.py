# start_all.py (ポート自動切替版)
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
# 設定（絶対パス指定）
# -----------------------------
# H: ドライブの FastAPI
BASE_DIR = r"H:\マイドライブ\tradingai_prod_v1\backend"
FASTAPI_PORT = 8000
FASTAPI_URL = f"http://127.0.0.1:{FASTAPI_PORT}/positions"

# C: ドライブの React
REACT_DIR = r"C:\trading\react_dashboard"
REACT_DEFAULT_PORT = 5173

# その他設定
BROWSER_OPEN_DELAY = 1.0
REACT_START_RETRIES = 5
FASTAPI_TIMEOUT = 60

# -----------------------------
# FastAPI 起動
# -----------------------------
print("Starting FastAPI...")
fastapi_proc = subprocess.Popen(
    [sys.executable, "run_backend.py"],
    cwd=BASE_DIR,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

print(f"Waiting for FastAPI at {FASTAPI_URL} ...")
for _ in range(FASTAPI_TIMEOUT):
    try:
        resp = requests.get(FASTAPI_URL)
        if resp.status_code == 200:
            print("FastAPI is ready!")
            break
    except requests.exceptions.RequestException:
        pass
    time.sleep(1)
else:
    print("Error: FastAPI did not start within timeout.")
    fastapi_proc.terminate()
    sys.exit(1)

# -----------------------------
# 空きポート検出
# -----------------------------
def find_free_port(start_port):
    port = start_port
    while port < start_port + 50:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
            port += 1
    return None

# -----------------------------
# React 起動（Unicode + ポート自動切替対応）
# -----------------------------
def start_react():
    for attempt in range(REACT_START_RETRIES):
        port = find_free_port(REACT_DEFAULT_PORT)
        if port is None:
            print("Error: Could not find free port for React.")
            return None, None

        print(f"Starting React (Vite) on port {port} - Attempt {attempt+1} ...")
        env = os.environ.copy()
        env["PORT"] = str(port)
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=REACT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            env=env,
        )

        # React ログから URL を検出
        url_pattern = re.compile(rb'Local:\s*(http://localhost:\d+)')
        url = None
        start_time = time.time()
        while time.time() - start_time < 30:
            line = proc.stdout.readline()
            if not line:
                break
            decoded_line = line.decode("cp932", errors="replace")
            print(decoded_line, end="")
            match = url_pattern.search(line)
            if match:
                url = match.group(1).decode()
                break

        if url:
            print(f"React is running at {url}")
            return proc, url
        else:
            print("React URL not detected, retrying...")
            proc.terminate()
            time.sleep(2)
    return None, None

react_proc, react_url = start_react()
if react_proc is None or react_url is None:
    print("Error: Could not start React successfully.")
    fastapi_proc.terminate()
    sys.exit(1)

# -----------------------------
# ブラウザを開く
# -----------------------------
threading.Timer(BROWSER_OPEN_DELAY, lambda: webbrowser.open(react_url)).start()

# -----------------------------
# 両方のプロセスを待機
# -----------------------------
try:
    fastapi_proc.wait()
    react_proc.wait()
except KeyboardInterrupt:
    print("Shutting down...")
    fastapi_proc.terminate()
    react_proc.terminate()