import os
import sys
import webbrowser
import streamlit.web.cli as stcli
import threading
import time
import psutil

STREAMLIT_PORT = 8501
CHECK_INTERVAL = 3

def is_browser_open(port: int) -> bool:
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'ESTABLISHED':
                return True
    except Exception:
        pass
    return False

def browser_watchdog(stop_event: threading.Event, port: int):
    time.sleep(8)  # 增加等待时间
    was_open = False
    while not stop_event.is_set():
        if is_browser_open(port):
            was_open = True
        elif was_open:
            print("[INFO] Browser closed, exiting...")
            os._exit(0)
        time.sleep(CHECK_INTERVAL)

def open_browser():
    time.sleep(2)
    url = f"http://localhost:{STREAMLIT_PORT}"
    try:
        if not webbrowser.open(url):
            print(f"[INFO] 浏览器未能自动打开，请手动访问: {url}")
    except Exception as e:
        print(f"[WARN] 打开浏览器失败: {e}")
        print(f"[INFO] 请手动打开浏览器访问: {url}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"[INFO] Aurum starting on port {STREAMLIT_PORT}")
    print("[INFO] Browser will open automatically")
    print("[INFO] Service auto-exits when browser is closed")

    threading.Thread(target=open_browser, daemon=True).start()
    stop_event = threading.Event()
    watchdog = threading.Thread(target=browser_watchdog, args=(stop_event, STREAMLIT_PORT), daemon=True)
    watchdog.start()

    sys.argv = [
        "streamlit", "run",
        "aurum_app.py",
        "--server.headless=true",
        f"--server.port={STREAMLIT_PORT}",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
    ]

    try:
        stcli.main()
    except SystemExit:
        pass
    finally:
        stop_event.set()
        print("[INFO] Aurum exited")