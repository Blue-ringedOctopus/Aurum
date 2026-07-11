import os
import shutil
import time
import subprocess


def delete_folder_safely(folder_path: str) -> tuple:
    """安全删除单个文件夹，返回 (成功标志, 错误信息)"""
    if not os.path.exists(folder_path):
        return True, None  # 不存在视为成功（无需删除）
    try:
        shutil.rmtree(folder_path)
        return True, None
    except PermissionError:
        return False, f"文件夹被占用: {folder_path}"
    except OSError as e:
        return False, f"删除失败: {folder_path}，错误: {str(e)}"


def clean_empty_parents(folder_path: str, stop_root: str) -> list:
    """
    向上清理空目录，直到到达 stop_root（根目录）为止。
    返回已删除的文件夹路径列表。
    """
    deleted = []
    current = os.path.abspath(folder_path)
    stop_root = os.path.abspath(stop_root)

    while current != stop_root:
        # 检查当前文件夹是否存在且为空
        if not os.path.exists(current):
            break
        try:
            # 如果文件夹为空，删除它
            if not os.listdir(current):
                shutil.rmtree(current)
                deleted.append(current)
                # 继续向上移动到父目录
                current = os.path.dirname(current)
            else:
                # 文件夹非空，停止向上清理
                break
        except (PermissionError, OSError):
            # 无法读取或删除，停止向上清理
            break
    return deleted


def delete_folders_with_cleanup(folders_to_delete: list, stop_root: str) -> dict:
    """
    批量删除文件夹，并按深度排序（先删最深的）。
    如果任何一个删除失败，立即返回错误（不继续后续操作）。
    删除成功后，向上清理空的父目录（直到 stop_root）。
    返回: {'deleted': [...], 'errors': [...]}
    """
    # 1. 按路径长度降序排列（先删最深的，再删浅的）
    sorted_folders = sorted(folders_to_delete, key=len, reverse=True)

    deleted_primary = []
    errors = []

    # 2. 执行删除
    for folder in sorted_folders:
        if not os.path.exists(folder):
            continue
        success, err = delete_folder_safely(folder)
        if not success:
            # 只要有一个失败，立即终止，返回错误（数据库不动）
            return {'deleted': deleted_primary, 'errors': [err]}
        deleted_primary.append(folder)

    # 3. 向上清理空父目录（去重）
    all_deleted = set(deleted_primary)
    for folder in sorted_folders:
        # 只对已经成功删除的路径进行向上清理
        if folder in deleted_primary:
            parent = os.path.dirname(folder)
            cleaned = clean_empty_parents(parent, stop_root)
            all_deleted.update(cleaned)

    return {'deleted': list(all_deleted), 'errors': []}