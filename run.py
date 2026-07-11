import os
import sys
import webbrowser
import streamlit.web.cli as stcli
import threading
import time
import psutil

STREAMLIT_PORT = 8501
CHECK_INTERVAL = 3


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    for conn in psutil.net_connections(kind='inet'):
        if conn.laddr.port == port and conn.status == 'ESTABLISHED':
            return True
    return False


def is_browser_open(port: int) -> bool:
    """检查是否有浏览器连接 localhost:port（仅 ESTABLISHED 连接）"""
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'ESTABLISHED':
                return True
    except Exception:
        pass
    return False


def browser_watchdog(stop_event: threading.Event, port: int):
    """看门狗：监听浏览器连接状态"""
    time.sleep(5)  # 给用户留出打开浏览器的时间

    while not stop_event.is_set():
        if not is_browser_open(port):
            print("[INFO] Browser closed, exiting...")
            os._exit(0)  # 直接退出整个进程
        time.sleep(CHECK_INTERVAL)


def open_browser():
    """延迟打开浏览器"""
    time.sleep(2)
    webbrowser.open(f"http://localhost:{STREAMLIT_PORT}")


if __name__ == "__main__":
    # 切换到 exe 所在目录（确保路径正确）
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print(f"[INFO] Aurum starting on port {STREAMLIT_PORT}")
    print("[INFO] Browser will open automatically")
    print("[INFO] Service auto-exits when browser is closed")

    # 启动浏览器（独立线程）
    threading.Thread(target=open_browser, daemon=True).start()

    # 启动看门狗（独立线程）
    stop_event = threading.Event()
    watchdog = threading.Thread(target=browser_watchdog, args=(stop_event, STREAMLIT_PORT), daemon=True)
    watchdog.start()

    # 用 streamlit 的 CLI 入口直接启动（这是关键）
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