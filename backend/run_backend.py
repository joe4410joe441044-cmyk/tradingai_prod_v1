# H:\マイドライブ\tradingai_prod_v1\backend\run_backend.py
import uvicorn
import webbrowser
import threading

def open_browser():
    webbrowser.open("http://localhost:8000/positions")

if __name__ == "__main__":
    # 別スレッドでブラウザを開く
    threading.Timer(1.0, open_browser).start()

    # FastAPI を起動（Windowsでも安全）
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)