import platform
import subprocess
import os

def open_folder(path):
    """跨平台打开文件夹"""
    if platform.system() == 'Windows':
        os.startfile(path)
    elif platform.system() == 'Darwin':  # macOS
        subprocess.run(['open', path])
    else:  # Linux
        subprocess.run(['xdg-open', path])