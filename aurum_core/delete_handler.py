import os
import shutil
import sqlite3
from typing import List, Tuple, Dict, Set
from aurum_core.database import clean_orphan_tags

# ---------- 辅助函数 ----------
def force_delete_folder(folder_path: str) -> Tuple[bool, str]:
    """
    强制删除文件夹（包括所有子文件和子文件夹）。
    先递归移除所有文件的只读属性，然后删除。
    返回 (是否成功, 错误信息)
    """
    if not os.path.exists(folder_path):
        return True, ""

    # 递归修改文件权限（去除只读）
    def on_rm_error(func, path, exc_info):
        # 尝试修改权限并重试
        try:
            os.chmod(path, 0o777)
            func(path)
        except Exception as e:
            # 如果仍然失败，记录错误但不中断
            pass

    try:
        shutil.rmtree(folder_path, ignore_errors=False, onerror=on_rm_error)
        # 检查是否还存在
        if os.path.exists(folder_path):
            return False, f"删除后文件夹仍然存在: {folder_path}"
        return True, ""
    except Exception as e:
        return False, str(e)

def collect_folders_to_delete(records: List[Tuple[str, str]], db_path: str) -> Tuple[set, set, set]:
    """
    收集需要删除的日期文件夹、患者文件夹和医院文件夹路径
    records: [(patient_name, visit_date), ...]
    返回: (date_folders, patient_folders, hospital_folders)
    """
    date_folders = set()
    patient_folders = set()
    hospital_folders = set()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for patient_name, visit_date in records:
        cursor.execute(
            "SELECT docx_path FROM visits WHERE patient_name = ? AND visit_date = ?",
            (patient_name, visit_date)
        )
        row = cursor.fetchone()
        if row and row[0]:
            docx_path = row[0]
            date_folder = os.path.dirname(docx_path)                      # .../医院/患者/日期
            patient_folder = os.path.dirname(date_folder)                 # .../医院/患者
            hospital_folder = os.path.dirname(patient_folder)             # .../医院
            date_folders.add(date_folder)
            patient_folders.add(patient_folder)
            hospital_folders.add(hospital_folder)
    conn.close()
    return date_folders, patient_folders, hospital_folders

def sync_delete_folders(date_folders: set, patient_folders: set, hospital_folders: set) -> Dict:
    """
    同步删除文件夹：先删日期 → 删患者（整个文件夹）→ 删空医院
    任何删除失败立即终止。
    返回: {'deleted_dates': [...], 'deleted_patients': [...], 'deleted_hospitals': [...], 'errors': [...]}
    """
    deleted_dates = []
    deleted_patients = []
    deleted_hospitals = []
    errors = []

    # 1. 删日期文件夹
    for folder in date_folders:
        if not os.path.exists(folder):
            continue
        success, err = force_delete_folder(folder)
        if not success:
            return {'deleted_dates': deleted_dates, 'deleted_patients': deleted_patients, 'deleted_hospitals': deleted_hospitals, 'errors': [err]}
        deleted_dates.append(folder)

    # 2. 删患者文件夹（整个文件夹，包括其中的所有文件）
    for folder in patient_folders:
        if not os.path.exists(folder):
            continue
        success, err = force_delete_folder(folder)
        if not success:
            return {'deleted_dates': deleted_dates, 'deleted_patients': deleted_patients, 'deleted_hospitals': deleted_hospitals, 'errors': [err]}
        deleted_patients.append(folder)

    # 3. 清理空医院文件夹
    for folder in hospital_folders:
        if not os.path.exists(folder):
            continue
        try:
            if not os.listdir(folder):  # 为空
                success, err = force_delete_folder(folder)
                if not success:
                    return {'deleted_dates': deleted_dates, 'deleted_patients': deleted_patients, 'deleted_hospitals': deleted_hospitals, 'errors': [err]}
                deleted_hospitals.append(folder)
        except (PermissionError, OSError):
            # 无法检查，跳过
            pass

    return {
        'deleted_dates': deleted_dates,
        'deleted_patients': deleted_patients,
        'deleted_hospitals': deleted_hospitals,
        'errors': errors
    }

# ---------- 核心删除函数 ----------
def delete_records_clean(
    deleted_records_info: List[Tuple[str, str]],
    db_path: str,
    sync_enabled: bool = False
) -> Dict:
    result = {
        'success': False,
        'message': '',
        'deleted_records': 0,
        'deleted_folders': 0,
        'errors': []
    }

    # 1. 收集文件夹路径
    date_folders, patient_folders, hospital_folders = collect_folders_to_delete(deleted_records_info, db_path)

    # 2. 同步删除文件夹（如果开启）
    if sync_enabled and date_folders:
        folder_result = sync_delete_folders(date_folders, patient_folders, hospital_folders)
        if folder_result['errors']:
            result['message'] = "同步删除文件夹失败，操作已取消，数据库未受影响。"
            result['errors'] = folder_result['errors']
            return result
        total_deleted = (
            len(folder_result.get('deleted_dates', [])) +
            len(folder_result.get('deleted_patients', [])) +
            len(folder_result.get('deleted_hospitals', []))
        )
        result['deleted_folders'] = total_deleted
        result['_deleted_hospitals'] = folder_result.get('deleted_hospitals', [])

    # 3. 删除数据库记录（无论同步删除是否开启，都执行）
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN TRANSACTION")
        deleted_patients = set()
        for patient_name, visit_date in deleted_records_info:
            cursor.execute(
                "DELETE FROM visits WHERE patient_name = ? AND visit_date = ?",
                (patient_name, visit_date)
            )
            if cursor.rowcount > 0:
                deleted_patients.add(patient_name)
                result['deleted_records'] += 1

        # ---- 先删除关联表中的孤立关联 ----
        cursor.execute("DELETE FROM visit_mark_links WHERE visit_id NOT IN (SELECT id FROM visits)")
        cursor.execute(
            "DELETE FROM patient_group_links WHERE patient_name NOT IN (SELECT patient_name FROM patient_profiles)")

        # ---- 清理孤儿关联表数据（双保险） ----
        cursor.execute("DELETE FROM visit_mark_links WHERE visit_id NOT IN (SELECT id FROM visits)")
        cursor.execute(
            "DELETE FROM patient_group_links WHERE patient_name NOT IN (SELECT patient_name FROM patient_profiles)")

        # ---- 清理孤儿标签 ----
        from aurum_core.database import clean_orphan_tags
        clean_orphan_tags(conn)

        # ---- 删除无就诊记录的患者档案 ----
        for patient in deleted_patients:
            cursor.execute("SELECT COUNT(*) FROM visits WHERE patient_name = ?", (patient,))
            if cursor.fetchone()[0] == 0:
                cursor.execute("DELETE FROM patient_profiles WHERE patient_name = ?", (patient,))

        conn.commit()
        result['success'] = True
        result['message'] = f"已删除 {result['deleted_records']} 条记录"

    except Exception as e:
        conn.rollback()
        result['message'] = f"数据库删除失败，已回滚。错误: {e}"
        result['errors'].append(str(e))
    finally:
        conn.close()

    return result