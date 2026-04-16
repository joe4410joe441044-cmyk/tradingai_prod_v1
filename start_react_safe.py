# start_all.py
import os
import subprocess
import socket
import time

# --------------------------
# ★ 環境に合わせてここだけ変更（重要）
BACKEND_DIR = r"H:\マイドライブ\tradingai_prod_v1\backend"
REACT_DIR = r"C:\trading\react_dashboard"

# ★ ★ここが今回の正解（修正済み）
VENV_PYTHON = r"H:\マイドライブ\tradingai_prod_v1\venv_new\Scripts\python.exe"

# --------------------------
# ポート使用中チェック
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0

# --------------------------
# FastAPI 起動
def start_fastapi():
    if not os.path.exists(BACKEND_DIR):
        raise FileNotFoundError(f"Backend ディレクトリが存在しません: {BACKEND_DIR}")

    if not os.path.exists(VENV_PYTHON):
        raise FileNotFoundError(f"venv Python が存在しません: {VENV_PYTHON}")

    port = 8000
    while is_port_in_use(port):
        print(f"FastAPI port {port} は使用中、次へ...")
        port += 1

    print(f"✅ FastAPI 起動 (port={port})")

    process = subprocess.Popen(
        [
            VENV_PYTHON,
            "-m", "uvicorn",
            "main:app",
            "--reload",
            "--port", str(port)
        ],
        cwd=BACKEND_DIR
    )

    # 起動待機
    print("⏳ FastAPI 起動待機中...")
    time.sleep(3)

    return process, port

# --------------------------
# React 起動
def start_react():
    if not os.path.exists(REACT_DIR):
        raise FileNotFoundError(f"React ディレクトリが存在しません: {REACT_DIR}")

    print("✅ React 起動中...")

    process = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=REACT_DIR,
        shell=True
    )

    # Vite起動待ち
    time.sleep(5)

    return process

# --------------------------
# ブラウザ起動
def open_browser():
    url = "http://localhost:5173"
    print(f"🌐 ブラウザ起動: {url}")
    subprocess.Popen(["start", url], shell=True)

# --------------------------
if __name__ == "__main__":
    print("=== FastAPI + React 自動起動 ===")

    fastapi_process, fastapi_port = start_fastapi()
    react_process = start_react()

    # ブラウザ起動
    open_browser()

    try:
        fastapi_process.wait()
        react_process.wait()
    except KeyboardInterrupt:
        print("🛑 終了処理中...")
        fastapi_process.terminate()
        react_process.terminate()
        