# --- 核心归档函数 ---
import os
import sqlite3
import shutil
from aurum_core.database import get_db_path
from aurum_core.text_utils import read_file_content, normalize_date_str
import re
from aurum_core.user_settings import get_user_setting

DATE_PATTERN = re.compile(
    r'^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}[日号]|'
    r'\d{8}|\d{6}|\d{2}年\d{1,2}月\d{1,2}[日号])(?:\s*)(.*)$'
)

def clean_patient_name(name: str) -> str:
    """
    清洗患者姓名
    - 去除首尾空格
    - 去除括号及其内容（包括中文括号、英文括号）
    - 去除日期格式（如 2025-06-01）
    - 去除“初诊”、“复诊”、“首诊”等常见备注
    - 合并连续空格
    - 过滤非法文件名字符
    """
    if not name:
        return name

    # 1. 去除首尾空格
    name = name.strip()

    # 2. 去除括号及其内容（中文括号（）和英文括号()）
    name = re.sub(r'[（(][^）)]*[）)]', '', name)

    # 3. 去除“初诊”、“复诊”、“首诊”、“二诊”等
    name = re.sub(r'[初首二三四五六七八九]诊', '', name)

    # 4. 去除日期格式（如 2025-06-01、2025/06/01、2025年06月01日）
    name = re.sub(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?', '', name)
    name = re.sub(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', '', name)

    # 5. 全角数字/字母转半角
    name = name.translate(str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    ))

    # 6. 移除非法文件名字符（保留中文、英文、数字、下划线、连字符）
    name = re.sub(r'[<>:"/\\|?*]', '', name)

    # 7. 合并连续空格为一个
    name = re.sub(r'\s+', ' ', name)

    # 8. 去除首尾空格和多余标点
    name = name.strip(' .,;:！？。，；：')

    return name if name else "未知患者"

def clean_path(path: str) -> str:
    """去除路径字符串首尾的引号（双引号或单引号）"""
    if not path:
        return path
    return path.strip().strip('"').strip("'")

def select_medical_file(folder_path: str, expected_date: str = None) -> tuple:
    """
    智能选择患者文件夹中的病历文件（docx/doc/txt）。
    新增逻辑：
    1. 文件内容必须包含医学关键词（主诉、舌脉、诊断等）
    2. 文件内容必须包含就诊日期（如果提供了 expected_date）
    3. 支持多种日期格式解析（YYYY-MM-DD, YYYY/MM/DD, YYYY年MM月DD日等）
    返回 (文件路径, 状态信息) 其中状态信息为提示文本
    """
    import re
    from datetime import datetime

    # ---- 新增：检查文件夹是否存在 ----
    if not os.path.exists(folder_path):
        return None, f"文件夹不存在: {folder_path}"

    candidates = []
    for f in os.listdir(folder_path):
        file_path = os.path.join(folder_path, f)
        if not os.path.isfile(file_path):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in ('.docx', '.doc', '.txt'):
            candidates.append(file_path)

    if not candidates:
        return None, "未找到任何 .docx/.doc/.txt 文件"

    # 解析期望日期
    target_date = None
    if expected_date:
        patterns = [
            r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})',
            r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]?',  # 允许 日/号/无
            r'(\d{4})年(\d{1,2})月',
        ]
        for pat in patterns:
            m = re.search(pat, expected_date)
            if m:
                year = int(m.group(1))
                month = int(m.group(2))
                day = int(m.group(3)) if len(m.groups()) >= 3 else 1
                try:
                    target_date = datetime(year, month, day).date()
                    break
                except:
                    continue

    # 对每个候选文件，检查日期是否匹配
    date_matched_files = []
    for path in candidates:
        content = read_file_content(path)
        if not content:
            continue
        # 检查内容中是否包含目标日期（如果 target_date 存在）
        if target_date:
            found = False
            for pat in patterns:
                for m in re.finditer(pat, content):
                    try:
                        year = int(m.group(1))
                        month = int(m.group(2))
                        day = int(m.group(3)) if len(m.groups()) >= 3 else 1
                        found_date = datetime(year, month, day).date()
                        if found_date == target_date:
                            found = True
                            break
                    except:
                        continue
                if found:
                    break
            if found:
                date_matched_files.append(path)
        else:
            # 如果没有期望日期，则直接加入（但这种情况很少）
            date_matched_files.append(path)

    if date_matched_files:
        # 在日期匹配的文件中，优先选择包含医学关键词的
        for path in date_matched_files:
            content = read_file_content(path)
            if content and any(kw in content for kw in ['主诉', '舌脉', '诊断', '方药', '处方', '药方']):
                return path, "✅ 通过日期匹配且包含医学关键词"
        # 其次选文件最大的
        date_matched_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
        return date_matched_files[0], "【病历文件】⚠️ 通过日期匹配但未找到明确医学关键词，请人工确认"
    else:
        # ---- 新增保底策略 ----
        # 如果没有任何文件匹配日期，但文件夹中有文档文件，尝试用保底逻辑
        if candidates:
            # 1. 优先选择包含医学关键词的文件（不检查日期）
            for path in candidates:
                content = read_file_content(path)
                if content and any(kw in content for kw in ['主诉', '舌脉', '诊断', '方药', '处方', '药方']):
                    return path, "【病历文件】⚠️ 未匹配日期，但包含医学关键词，已自动采用"
            # 2. 如果只有一个文档文件，直接采用
            if len(candidates) == 1:
                return candidates[0], "【病历文件】⚠️ 未匹配日期，且文件夹中仅有一个文档文件，已自动采用"
            # 3. 如果有多个文档，选文件最大的
            candidates.sort(key=lambda x: os.path.getsize(x), reverse=True)
            return candidates[0], "【病历文件】⚠️ 未匹配日期，已选文件最大的文档，请人工确认"
        else:
            return None, "❌ 未找到任何可识别的病历文件"

def _find_medical_file(folder_path: str) -> str:
    """在文件夹中查找第一个病历文件（.docx/.doc/.txt）"""
    for f in os.listdir(folder_path):
        if f.lower().endswith(('.docx', '.doc', '.txt')):
            return os.path.join(folder_path, f)
    return None

def _insert_visit_record(cursor, patient: str, visit_date: str, hospital: str, docx_path: str):
    """
    插入或更新就诊记录。
    返回值：
        - "inserted": 成功插入新记录
        - "updated": 更新了已有记录
        - "empty": 文件为空
        - "occupied": 文件被占用
        - False: 其他错误
    """
    if not os.path.exists(docx_path):
        return False
    if os.path.getsize(docx_path) == 0:
        return "empty"

    try:
        content = read_file_content(docx_path)
    except (PermissionError, OSError):
        return "occupied"
    except Exception:
        return False

    if not content or not content.strip():
        return "empty"

    try:
        cursor.execute(
            "SELECT id FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
            (patient, visit_date, hospital)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE visits SET docx_path = ?, full_medical_text = ? WHERE id = ?",
                (docx_path, content, existing[0])
            )
            action = "updated"
        else:
            cursor.execute('''
                INSERT INTO visits 
                (patient_name, visit_date, hospital, docx_path, full_medical_text)
                VALUES (?, ?, ?, ?, ?)
            ''', (patient, visit_date, hospital, docx_path, content))
            action = "inserted"

        # ========== 提取诊断（读取用户偏好） ==========
        import streamlit as st
        import json
        from aurum_core.text_utils import extract_diagnosis

        diag_mode = get_user_setting('diagnosis_keyword_mode', '中医')
        default_to_tcm = (diag_mode == "中医")
        tcm_list, wm_list = extract_diagnosis(content, default_to_tcm=default_to_tcm)
        if tcm_list:
            cursor.execute(
                "UPDATE visits SET diagnosis = ? WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                (json.dumps(tcm_list, ensure_ascii=False), patient, visit_date, hospital)
            )
        if wm_list:
            cursor.execute(
                "UPDATE visits SET western_diagnosis = ? WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                (json.dumps(wm_list, ensure_ascii=False), patient, visit_date, hospital)
            )
        return action
    except Exception:
        return False

def _insert_empty_visit_record(cursor, patient: str, visit_date: str, hospital: str, date_folder_path: str, docx_path_override: str = None) -> str:
    """
    插入空记录。
    返回值：
        - "inserted": 成功插入新记录
        - "updated": 更新了已有记录（路径变化）
        - False: 错误
    """
    try:
        cursor.execute(
            "SELECT id FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
            (patient, visit_date, hospital)
        )
        existing = cursor.fetchone()

        if existing:
            # 已有记录，更新路径
            cursor.execute(
                "UPDATE visits SET docx_path = ?, full_medical_text = NULL, date_folder_path = ? WHERE id = ?",
                (docx_path_override, date_folder_path, existing[0])
            )
            return "updated"
        else:
            cursor.execute(
                "INSERT INTO visits (patient_name, visit_date, hospital, docx_path, full_medical_text, date_folder_path) VALUES (?, ?, ?, ?, NULL, ?)",
                (patient, visit_date, hospital, docx_path_override, date_folder_path)
            )
            return "inserted"
    except Exception:
        return False

def is_archived_structure(root_path: str) -> bool:
    """
    检测根目录下是否存在至少一个路径满足：深度 ≥ 2（相对于根目录），
    且该目录名匹配日期模式。
    返回 True 表示是已归档结构，False 表示未整理。
    """
    for dirpath, dirnames, filenames in os.walk(root_path):
        rel_path = os.path.relpath(dirpath, root_path)
        if rel_path == '.':
            depth = 0
        else:
            depth = len(rel_path.split(os.sep))
        # 深度 ≥ 2 意味着至少是 医院/患者 或 医院/日期/患者 等
        if depth >= 2:
            current_dir = os.path.basename(dirpath)
            if DATE_PATTERN.match(current_dir):
                return True
    return False

def reorganize_files(src, tgt, aggregate: bool = False, mode: str = "copy"):
    """
    归档整理主函数

    参数:
        src: 源目录
        tgt: 目标目录
        aggregate: 是否汇总就诊记录
        mode: "copy" 复制模式（默认）或 "move" 移动模式
    """

    # --- 第一步：检查源目录 ---
    if not os.path.exists(src):
        return "❌ 源路径不存在，请检查"

    try:
        items = os.listdir(src)
        if not items:
            return "⚠️ 源目录为空，未找到任何文件夹，请检查路径是否正确。"
    except PermissionError:
        return "⛔ 没有权限读取源文件夹"

    # ---- 先检测根目录类型（不创建目标目录） ----
    base_name = os.path.basename(src)
    match_root = DATE_PATTERN.match(base_name)
    log_lines = []

    # ========== 新增：显示归档模式 ==========
    mode_display = "复制" if mode == "copy" else "移动"
    log_lines.append(f"📦 模式：{mode_display}")
    log_lines.append("")

    if match_root and os.path.isdir(src):
        # 根目录本身就是日期文件夹 → 结构A
        date_folders = [base_name]
        root_is_date = True
        log_lines.append(f"🔍 根目录：{src}，发现根目录为日期文件夹")
    else:
        # 检查是否有日期子文件夹
        date_folders = []
        for f in items:
            full_path = os.path.join(src, f)
            if os.path.isdir(full_path) and DATE_PATTERN.match(f):
                date_folders.append(f)
        if date_folders:
            root_is_date = False
            log_lines.append(f"🔍 根目录：{src}，发现 {len(date_folders)} 个日期子文件夹")
        else:
            # 没有日期文件夹，检查是否为已归档结构（医院/患者/日期）→ 结构B
            hospital_candidates = [f for f in items if os.path.isdir(os.path.join(src, f))]
            if hospital_candidates:
                return (
                    "❌ 检测到您输入的是已整理好的归档文件夹（医院/患者/日期），请使用「🔄 刷新数据库」"
                )
            else:
                return "⚠️ 归档失败：根目录下既没有日期文件夹，也没有可识别的医院文件夹。请确认源目录是否正确。"

    # ========== 以下为结构A（日期文件夹，需要复制） ==========
    # ---- 检查源目录与目标目录是否相同（仅结构A需要） ----
    if os.path.abspath(src) == os.path.abspath(tgt):
        return "⚠️ 源目录与目标目录相同，请修改目标目录为不同路径。"

    # ---- 创建目标目录（结构A专用） ----
    try:
        os.makedirs(tgt, exist_ok=True)
    except Exception as e:
        return f"❌ 目标目录路径无效或无法创建：{e}"

    # ---- 结构A处理流程 ----
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    patient_data = {}
    total_patients = 0

    # ========== 新增：记录成功复制的路径（用于移动模式） ==========
    copied_paths = []

    # 统计总记录数
    total_visits = 0
    for date_folder in date_folders:
        if root_is_date:
            date_path = src
        else:
            date_path = os.path.join(src, date_folder)
        sub_items = os.listdir(date_path)
        patient_folders = [p for p in sub_items if os.path.isdir(os.path.join(date_path, p))]
        total_visits += len(patient_folders)
    log_lines.append(f"📋 共需处理 {total_visits} 条就诊记录")

    # ---- 第一阶段：复制并写入数据库 ----
    for date_folder in date_folders:
        if root_is_date:
            date_path = src
        else:
            date_path = os.path.join(src, date_folder)

        m = DATE_PATTERN.match(date_folder)
        if not m:
            log_lines.append(f"   ⚠️ 跳过无法解析的日期文件夹：{date_folder}")
            continue
        raw_date = m.group(1)
        hospital_name = m.group(2) if m.group(2) else "未归类患者"
        pure_date = normalize_date_str(raw_date)

        sub_items = os.listdir(date_path)
        patient_folders = [p for p in sub_items if os.path.isdir(os.path.join(date_path, p))]

        if not patient_folders:
            log_lines.append(f"   ⚠️ {date_folder} 下没有患者文件夹，跳过")
            continue

        for patient_raw in patient_folders:
            patient = clean_patient_name(patient_raw)
            patient_src_path = os.path.join(date_path, patient_raw)
            enable_hospital_layer = get_user_setting('enable_hospital_layer', True)
            if enable_hospital_layer:
                patient_tgt_path = os.path.join(tgt, hospital_name, patient, pure_date)
            else:
                patient_tgt_path = os.path.join(tgt, patient, pure_date)

            if patient not in patient_data:
                patient_data[patient] = {
                    'gender': None,
                    'birth_date': None,
                    'phone': None,
                    'id_card': None,
                    'address': None,
                    'visits': []
                }
            patient_data[patient]['visits'].append({
                'date': pure_date,
                'hospital': hospital_name,
                'diagnosis': '',
                'prescription': '',
                'remarks': ''
            })

            file_count = 0
            for root, dirs, files in os.walk(patient_src_path):
                file_count += len(files)

            if file_count == 0:
                # 创建目标目录（空文件夹）
                os.makedirs(patient_tgt_path, exist_ok=True)
                # ========== 新增：空文件夹也记录到 copied_paths ==========
                if mode == "move":
                    copied_paths.append((patient_src_path, patient_tgt_path))
                # 插入空记录
                if _insert_empty_visit_record(cursor, patient, pure_date, hospital_name, patient_tgt_path):
                    log_lines.append(f"   ⚠️ {patient}（{pure_date}，{hospital_name}）文件夹为空，已处理")
                    total_patients += 1
                else:
                    log_lines.append(f"   ❌ {patient}（{pure_date}，{hospital_name}）创建空记录失败")
                continue

            # ========== 修改：复制文件夹，记录成功路径 ==========
            try:
                shutil.copytree(patient_src_path, patient_tgt_path, dirs_exist_ok=True)
                if mode == "move":
                    copied_paths.append((patient_src_path, patient_tgt_path))
                # ========== 修改：日志泛化为「已处理」 ==========
                log_lines.append(f"   ✅ {patient}（{pure_date}）已处理")
            except Exception as e:
                log_lines.append(f"   ❌ {patient}（{pure_date}）复制失败：{e}")
                continue

            # 使用 select_medical_file 智能选择病历文件
            docx_file, select_status = select_medical_file(patient_tgt_path, pure_date)
            if select_status:
                log_lines.append(f"   ℹ️ {patient}（{pure_date}）{select_status}")

            if docx_file:
                result = _insert_visit_record(cursor, patient, pure_date, hospital_name, docx_file)
                if result == "inserted":
                    total_patients += 1
                elif result == "updated":
                    log_lines.append(
                        f"   ⚠️ {patient}（{pure_date}，{hospital_name}）记录已存在，已更新文件内容"
                    )
                elif result == "occupied":
                    log_lines.append(f"   ⚠️ {patient}（{pure_date}）病历文件被占用，请关闭后重试")
                elif result == "empty":
                    if _insert_empty_visit_record(cursor, patient, pure_date, hospital_name, patient_tgt_path,
                                                  docx_file):
                        log_lines.append(f"   ⚠️ {patient}（{pure_date}，{hospital_name}）病历文件为空，已创建空记录")
                        total_patients += 1
                    else:
                        log_lines.append(f"   ❌ {patient}（{pure_date}，{hospital_name}）创建空记录失败")
                else:
                    log_lines.append(f"   ⚠️ {patient}（{pure_date}）病历文件无效或为空，已跳过")

    conn.commit()

    # ========== 新增：第二阶段：移动模式下删除源文件 ==========
    if mode == "move" and copied_paths:
        log_lines.append("")
        log_lines.append("📦 正在删除原始文件...")
        deleted_count = 0
        failed_count = 0
        cleaned_parents = set()

        for src_path, tgt_path in copied_paths:
            if not os.path.exists(src_path):
                continue
            try:
                shutil.rmtree(src_path)
                deleted_count += 1

                # ---- 清理空的父目录（向上直到源根目录的前一层） ----
                parent = os.path.dirname(src_path)
                while parent and os.path.exists(parent):
                    # 如果父目录就是源目录本身，停止向上清理（留到最后单独处理）
                    if os.path.abspath(parent) == os.path.abspath(src):
                        break
                    try:
                        if not os.listdir(parent):
                            os.rmdir(parent)
                            cleaned_parents.add(parent)
                            parent = os.path.dirname(parent)
                        else:
                            break
                    except (OSError, PermissionError):
                        break
            except Exception as e:
                log_lines.append(f"   ⚠️ 删除失败：{src_path}，错误：{e}")
                failed_count += 1

            # ========== 新增：删除空的源根目录 ==========
        if os.path.exists(src) and os.path.isdir(src):
            try:
                if not os.listdir(src):
                    os.rmdir(src)
                    log_lines.append(f"   🧹 已清理空的源目录：{src}")
            except Exception as e:
                log_lines.append(f"   ⚠️ 清理源目录失败：{src}，错误：{e}")

        if failed_count == 0:
            log_lines.append(f"✅ 已删除 {deleted_count} 个原始文件夹")
            if cleaned_parents:
                log_lines.append(f"   🧹 已清理 {len(cleaned_parents)} 个空的父目录")
        else:
            log_lines.append(f"⚠️ 已删除 {deleted_count} 个，{failed_count} 个删除失败（文件保留在源目录）")

    # ---- 提取个人信息并生成档案（结构A专用） ----
    if total_patients > 0:
        try:
            from aurum_core.extract_patient_profiles import update_all_profiles
            update_all_profiles()
        except Exception as e:
            log_lines.append(f"   ⚠️ 自动提取个人信息失败：{e}")

        from aurum_core.file_processor import update_patient_archive_by_db
        for patient in patient_data.keys():
            try:
                update_patient_archive_by_db(patient, aggregate=aggregate)
                log_lines.append(f"   ✅ {patient} 的档案已生成")
            except Exception as e:
                log_lines.append(f"   ⚠️ {patient} 档案生成失败：{e}")

    conn.close()
    log_lines.append(f"\n🎉 归档完成！请前往 `{tgt}` 查看整理后的文件。")
    return "\n".join(log_lines)

def update_patient_archive_by_db(patient_name: str, aggregate: bool = False):
    """
    根据数据库记录，自动发现所有归档根目录并更新 _患者档案.txt。
    用于编辑个人信息后同步更新所有根目录下的档案。

    参数:
        patient_name: 患者姓名
        aggregate: 是否汇总所有根目录的就诊记录
            - False（默认）：每个根目录下的档案只包含该目录内的就诊记录
            - True：每个根目录下的档案都包含该患者的全部就诊记录
    """
    import sqlite3
    import json
    from datetime import datetime
    from collections import defaultdict

    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aurum_index.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 获取该患者所有就诊记录（含 docx_path）
    cursor.execute(
        "SELECT visit_date, hospital, diagnosis, prescription, visit_remarks, docx_path "
        "FROM visits WHERE patient_name = ? ORDER BY visit_date ASC",
        (patient_name,)
    )
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        print(f"⚠️ 患者 {patient_name} 没有就诊记录，无法生成档案")
        return

    # 获取患者档案信息
    cursor.execute(
        "SELECT gender, birth_date, phone, id_card, address, personal_remarks "
        "FROM patient_profiles WHERE patient_name = ?",
        (patient_name,)
    )
    profile = cursor.fetchone()
    conn.close()

    # 按归档根目录分组，同时收集全部记录（用于汇总模式）
    root_to_rows = defaultdict(list)
    all_rows = []
    for row in rows:
        visit_date, hospital, diagnosis, prescription, remarks, docx_path = row
        if docx_path and os.path.exists(docx_path):
            # 提取根目录：.../根目录/医院/患者/日期/病历.docx
            enable_hospital_layer = get_user_setting('enable_hospital_layer', True)
            if enable_hospital_layer:
                date_folder = os.path.dirname(docx_path)
                patient_folder = os.path.dirname(date_folder)
                hospital_folder = os.path.dirname(patient_folder)
                root = os.path.dirname(hospital_folder)
            else:
                date_folder = os.path.dirname(docx_path)
                patient_folder = os.path.dirname(date_folder)
                root = os.path.dirname(patient_folder)
            root_to_rows[root].append(row)
            all_rows.append(row)
        else:
            # 如果 docx_path 无效，跳过（这种情况极少）
            continue

    if not root_to_rows:
        print(f"⚠️ 患者 {patient_name} 的所有记录都没有有效的文件路径")
        return

    # ---- 根据 aggregate 决定使用哪组数据 ----
    # 如果开启汇总，所有根目录共用 all_rows；否则各自使用自己的 rows_in_root
    for root, rows_in_root in root_to_rows.items():
        # 选择数据源
        data_source = all_rows if aggregate else rows_in_root

        lines = []
        lines.append("患者档案")
        lines.append("")
        lines.append(f"姓名：{patient_name}")
        lines.append(f"性别：{profile[0] if profile else '无'}")
        lines.append(f"出生日期：{profile[1] if profile else '无'}")
        lines.append(f"电话：{profile[2] if profile else '无'}")
        lines.append(f"身份证号：{profile[3] if profile else '无'}")
        lines.append(f"住址：{profile[4] if profile else '无'}")
        if profile and profile[5]:
            lines.append(f"个人信息备注：{profile[5]}")
        lines.append("")
        lines.append("【就诊记录汇总】")

        for row in data_source:
            visit_date, hospital, diagnosis, prescription, remarks, _ = row
            try:
                diag_list = json.loads(diagnosis) if diagnosis else []
                diag_str = '、'.join(diag_list) if diag_list else '待补充'
            except:
                diag_str = diagnosis or '待补充'
            try:
                presc_list = json.loads(prescription) if prescription else []
                presc_str = '、'.join(presc_list) if presc_list else ''
            except:
                presc_str = prescription or ''
            line = f" {hospital} | {visit_date} | 诊断：{diag_str}"
            if presc_str:
                line += f" | 方剂：{presc_str}"
            if remarks:
                line += f" | 备注：{remarks}"
            lines.append(line)

        lines.append("")
        if aggregate:
            lines.append(
                f"共 {len(all_rows)} 次就诊记录（汇总自所有归档目录）| 档案更新于：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        else:
            lines.append(f"共 {len(rows_in_root)} 次就诊记录 | 档案更新于：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        # 找到该患者在该根目录下的所有医院文件夹（通过遍历 rows_in_root）
        for row in rows_in_root:
            _, hospital, _, _, _, docx_path = row
            if docx_path and os.path.exists(docx_path):
                # 根据医院层设置决定档案文件路径
                enable_hospital_layer = get_user_setting('enable_hospital_layer', True)
                if enable_hospital_layer:
                    patient_dir = os.path.join(root, hospital, patient_name)
                else:
                    # 无医院层模式下，档案文件直接放在根目录/患者姓名/下
                    patient_dir = os.path.join(root, patient_name)
                archive_path = os.path.join(patient_dir, "_患者档案.txt")
                os.makedirs(patient_dir, exist_ok=True)
                try:
                    with open(archive_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(lines))
                    print(f"✅ 已更新档案：{archive_path}")
                except Exception as e:
                    print(f"❌ 写入档案失败：{archive_path}, {e}")

def refresh_index_only(src_root: str, aggregate: bool = False) -> str:
    """
    仅刷新数据库索引，不复制任何文件，不创建任何文件夹。
    用于已有的归档结构（医院/患者/日期），将最新文件路径和内容同步到数据库。
    完成后会同步更新所有患者的档案文件。
    """
    if not os.path.exists(src_root):
        return "❌ 源路径不存在，请检查"

    try:
        items = os.listdir(src_root)
        if not items:
            return "⚠️ 源目录为空"
    except PermissionError:
        return "⛔ 没有权限读取源文件夹"

    if not is_archived_structure(src_root):
        return (
            "❌ 检测到未整理病历（日期/患者），请使用主界面的「归档整理」功能进行复制归档。\n"
            "   刷新数据库仅适用于已整理好的归档文件夹（医院/患者/日期）。"
        )

    log_lines = []
    log_lines.append(f"🔄 开始刷新数据库索引（仅更新，不复制文件）...")
    log_lines.append(f"📂 根目录：{src_root}")
    log_lines.append("")

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    total_updated = 0
    total_inserted = 0
    total_errors = 0

    # 这些变量用于统计，但不单独记录日志（统一用日志行体现）
    # total_skipped_no_file, total_skipped_empty 等移除，用日志行本身说明

    for hospital in os.listdir(src_root):
        hospital_path = os.path.join(src_root, hospital)
        if not os.path.isdir(hospital_path):
            continue
        for patient in os.listdir(hospital_path):
            patient_path = os.path.join(hospital_path, patient)
            if not os.path.isdir(patient_path):
                continue
            for date_folder in os.listdir(patient_path):
                date_path = os.path.join(patient_path, date_folder)
                if not os.path.isdir(date_path):
                    continue
                pure_date = normalize_date_str(date_folder)
                if not pure_date:
                    log_lines.append(
                        f"   ⚠️ 患者 {patient} | {date_folder} | 医院 {hospital} ：日期格式无法解析，跳过"
                    )
                    total_errors += 1
                    continue

                docx_file = None
                for f in os.listdir(date_path):
                    f_path = os.path.join(date_path, f)
                    if os.path.isfile(f_path) and f.lower().endswith(('.docx', '.doc', '.txt')):
                        docx_file = f_path
                        break

                # ========== 情况1：无文档文件 ==========
                if not docx_file:
                    cursor.execute(
                        "SELECT id, date_folder_path FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                        (patient, pure_date, hospital)
                    )
                    row = cursor.fetchone()
                    if row:
                        # 记录存在，路径可能变化，但用户不关心路径变化，所以不输出
                        pass
                    else:
                        cursor.execute(
                            "INSERT INTO visits (patient_name, visit_date, hospital, docx_path, full_medical_text, date_folder_path) VALUES (?, ?, ?, NULL, NULL, ?)",
                            (patient, pure_date, hospital, date_path)
                        )
                        total_inserted += 1
                        log_lines.append(
                            f"   ℹ️ 患者 {patient} | {pure_date} | 医院 {hospital} ：无文档文件，已创建空记录")
                    continue

                # ========== 情况2：文件大小为0 ==========
                file_size = os.path.getsize(docx_file)
                if file_size == 0:
                    cursor.execute(
                        "SELECT id, full_medical_text FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                        (patient, pure_date, hospital)
                    )
                    row = cursor.fetchone()
                    if row:
                        existing_id, current_text = row
                        if current_text and current_text.strip():
                            # 以前有内容，现在变成空文件 -> 记录
                            cursor.execute(
                                "UPDATE visits SET docx_path = ?, full_medical_text = NULL, date_folder_path = ? WHERE id = ?",
                                (docx_file, date_path, existing_id)
                            )
                            total_updated += 1
                            log_lines.append(
                                f"   ⚠️ 患者 {patient} | {pure_date} | 医院 {hospital} ：文件已被清空（0字节），已更新为空记录"
                            )
                        else:
                            # 以前就是空，只更新路径，不记日志
                            cursor.execute(
                                "UPDATE visits SET docx_path = ?, date_folder_path = ? WHERE id = ?",
                                (docx_file, date_path, existing_id)
                            )
                            total_updated += 1
                    else:
                        cursor.execute(
                            "INSERT INTO visits (patient_name, visit_date, hospital, docx_path, full_medical_text, date_folder_path) VALUES (?, ?, ?, ?, NULL, ?)",
                            (patient, pure_date, hospital, docx_file, date_path)
                        )
                        total_inserted += 1
                        log_lines.append(
                            f"   ℹ️ 患者 {patient} | {pure_date} | 医院 {hospital} ：文件为空（0字节），已创建空记录")
                    continue

                # ========== 读取文件内容 ==========
                try:
                    content = read_file_content(docx_file)
                except (PermissionError, OSError):
                    log_lines.append(
                        f"   ⚠️ 患者 {patient} | {pure_date} | 医院 {hospital} ：文件被占用（{docx_file}），跳过"
                    )
                    total_errors += 1
                    continue
                except Exception as e:
                    log_lines.append(
                        f"   ❌ 患者 {patient} | {pure_date} | 医院 {hospital} ：读取文件失败（{docx_file}），错误：{e}"
                    )
                    total_errors += 1
                    continue

                # ========== 情况3：文件内容为空（仅有空格/换行） ==========
                if not content or not content.strip():
                    cursor.execute(
                        "SELECT id, full_medical_text FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                        (patient, pure_date, hospital)
                    )
                    row = cursor.fetchone()
                    if row:
                        existing_id, current_text = row
                        if current_text and current_text.strip():
                            # 以前有内容，现在变空了
                            cursor.execute(
                                "UPDATE visits SET docx_path = ?, full_medical_text = NULL, date_folder_path = ? WHERE id = ?",
                                (docx_file, date_path, existing_id)
                            )
                            total_updated += 1
                            log_lines.append(
                                f"   ⚠️ 患者 {patient} | {pure_date} | 医院 {hospital} ：文件内容已被清空（仅空格），已更新为空记录"
                            )
                        else:
                            # 以前就是空，只更新路径，不记日志
                            cursor.execute(
                                "UPDATE visits SET docx_path = ?, date_folder_path = ? WHERE id = ?",
                                (docx_file, date_path, existing_id)
                            )
                            total_updated += 1
                    else:
                        cursor.execute(
                            "INSERT INTO visits (patient_name, visit_date, hospital, docx_path, full_medical_text, date_folder_path) VALUES (?, ?, ?, ?, NULL, ?)",
                            (patient, pure_date, hospital, docx_file, date_path)
                        )
                        total_inserted += 1
                        log_lines.append(
                            f"   ⚠️ 患者 {patient} | {pure_date} | 医院 {hospital} ：文件内容为空（仅空格），已创建空记录"
                        )
                    continue

                # ========== 情况4：正常内容 ==========
                cursor.execute(
                    "SELECT id, full_medical_text FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                    (patient, pure_date, hospital)
                )
                row = cursor.fetchone()
                if row:
                    existing_id, current_text = row
                    # 如果内容没有变化，只更新路径，不记日志
                    if current_text == content:
                        cursor.execute(
                            "UPDATE visits SET docx_path = ?, date_folder_path = ? WHERE id = ?",
                            (docx_file, date_path, existing_id)
                        )
                        total_updated += 1
                        # 内容未变，不记日志（静默更新路径）
                    else:
                        cursor.execute(
                            "UPDATE visits SET docx_path = ?, full_medical_text = ?, date_folder_path = ? WHERE id = ?",
                            (docx_file, content, date_path, existing_id)
                        )
                        total_updated += 1
                        log_lines.append(
                            f"   ✅ 更新记录：患者 {patient} | {pure_date} | 医院 {hospital}"
                        )
                else:
                    cursor.execute(
                        "INSERT INTO visits (patient_name, visit_date, hospital, docx_path, full_medical_text, date_folder_path) VALUES (?, ?, ?, ?, ?, ?)",
                        (patient, pure_date, hospital, docx_file, content, date_path)
                    )
                    total_inserted += 1
                    log_lines.append(
                        f"   ✅ 新增记录：患者 {patient} | {pure_date} | 医院 {hospital}"
                    )

                # ========== 提取诊断（从 session_state 读取用户偏好，即时生效） ==========
                import json
                from aurum_core.text_utils import extract_diagnosis

                diag_mode = get_user_setting('diagnosis_keyword_mode', '中医')
                default_to_tcm = (diag_mode == "中医")
                tcm_list, wm_list = extract_diagnosis(content, default_to_tcm=default_to_tcm)
                if tcm_list:
                    cursor.execute(
                        "UPDATE visits SET diagnosis = ? WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                        (json.dumps(tcm_list, ensure_ascii=False), patient, pure_date, hospital)
                    )
                if wm_list:
                    cursor.execute(
                        "UPDATE visits SET western_diagnosis = ? WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                        (json.dumps(wm_list, ensure_ascii=False), patient, pure_date, hospital)
                    )

    conn.commit()
    conn.close()

    # ---- 简洁总结 ----
    # 先判断整体状态
    if total_errors == 0:
        log_lines.append("")
        log_lines.append("✅ 所有记录已同步完成，索引已重建。")
    else:
        log_lines.append("")
        log_lines.append(f"⚠️ 处理完成，但存在 {total_errors} 条错误。索引已重建。")

    # ---- 自动提取患者档案信息 ----
    try:
        from aurum_core.extract_patient_profiles import update_all_profiles
        update_all_profiles()
    except Exception as e:
        log_lines.append(f"⚠️ 自动提取个人信息失败：{e}")

    # ---- 同步更新患者档案文件（_患者档案.txt） ----
    try:
        from aurum_core.file_processor import update_patient_archive_by_db
        conn2 = sqlite3.connect(db_path)
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT DISTINCT patient_name FROM visits")
        patients = [row[0] for row in cursor2.fetchall()]
        conn2.close()
        if patients:
            for patient in patients:
                try:
                    update_patient_archive_by_db(patient, aggregate=aggregate)
                except Exception as e:
                    log_lines.append(f"⚠️ 生成档案失败（{patient}）：{e}")
            log_lines.append(f"✅ 已同步更新 {len(patients)} 位患者的档案文件")
    except Exception as e:
        log_lines.append(f"⚠️ 更新档案文件失败：{e}")

    return "\n".join(log_lines)