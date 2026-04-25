# start_all_win_safe.py
import os
import subprocess
import sys
import time
import webbrowser
import requests
import threading
import re

# -----------------------------
# 設定
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REACT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "react_dashboard"))
FASTAPI_PORT = 8000
FASTAPI_URL = f"http://127.0.0.1:{FASTAPI_PORT}/positions"
BROWSER_OPEN_DELAY = 1.0  # FastAPI起動後にブラウザを開く遅延
REACT_START_RETRIES = 3   # React URL 検出リトライ回数
FASTAPI_TIMEOUT = 60      # FastAPI 起動待機最大秒数

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

# FastAPI が起動するまで待機
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
# React 起動（Windows 安全版）
# -----------------------------
def start_react():
    for attempt in range(REACT_START_RETRIES):
        print(f"Starting React (Vite) - Attempt {attempt+1} ...")
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=REACT_DIR,         # 必ず react_dashboard で実行
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,            # Windows では必須
        )

        # React ログから URL を検出
        url_pattern = re.compile(r'Local:\s*(http://localhost:\d+)')
        url = None
        start_time = time.time()
        while time.time() - start_time < 30:  # 最大30秒待機
            line = proc.stdout.readline()
            if not line:
                break
            print(line, end="")
            match = url_pattern.search(line)
            if match:
                url = match.group(1)
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

# ブラウザを開く
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