# updater.py
# 作用：解压新版本压缩包，覆盖旧文件（保留用户的 config.yaml 和 aurum_index.db）
import os
import sys
import time
import shutil
import subprocess


def main():
    # 期望接收 3 个参数：当前程序目录，新版本临时解压目录
    if len(sys.argv) < 3:
        return

    target_dir = sys.argv[1]  # 例如：D:/Aurum 文件夹所在位置
    source_dir = sys.argv[2]  # 新版本解压出来的临时文件夹

    # 等待主程序完全退出
    time.sleep(3)

    try:
        # 遍历新版本的所有文件
        for root, dirs, files in os.walk(source_dir):
            # 计算相对路径
            rel_path = os.path.relpath(root, source_dir)
            if rel_path == '.':
                dest_root = target_dir
            else:
                dest_root = os.path.join(target_dir, rel_path)
                os.makedirs(dest_root, exist_ok=True)

            for file in files:
                # 绝对不要覆盖用户的配置和数据库！
                if file in ['config.yaml', 'aurum_index.db']:
                    continue

                src_file = os.path.join(root, file)
                dst_file = os.path.join(dest_root, file)

                try:
                    shutil.copy2(src_file, dst_file)  # 复制并保留元数据
                except Exception as e:
                    # 如果复制失败，写日志但不中断（避免删库跑路）
                    with open('update_error.log', 'a') as f:
                        f.write(f"复制失败 {file}: {e}\n")

        # 复制完成后，重新启动主程序
        exe_path = os.path.join(target_dir, 'Aurum.exe')
        if os.path.exists(exe_path):
            subprocess.Popen([exe_path])

    except Exception as e:
        with open('update_error.log', 'w') as f:
            f.write(str(e))


if __name__ == '__main__':
    main()