# ============================================================
# 【本地操作】智能索引模块 - 创建数据库并扫描归档文件
# 此部分所有操作均在本地硬盘执行，无任何网络请求
# ============================================================
import sqlite3
import os
import json
from pypinyin import pinyin, Style
from typing import List, Dict
import pandas as pd

def get_db_path(db_name="aurum_index.db") -> str:
    """返回项目根目录下的数据库完整路径"""
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, db_name)

def init_database(db_path="aurum_index.db"):
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                hospital TEXT,
                docx_path TEXT,
                images_path TEXT,
                syndrome TEXT,
                prescription TEXT,
                custom_tags TEXT,
                diagnosis TEXT,
                western_diagnosis TEXT, 
                full_medical_text TEXT,
                visit_remarks TEXT,
                UNIQUE(patient_name, visit_date, hospital)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS patient_profiles (
                patient_name TEXT PRIMARY KEY,
                gender TEXT,
                birth_date TEXT,
                phone TEXT,
                id_card TEXT,
                address TEXT,
                personal_remarks TEXT,
                first_visit_date TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # ---- 新增：多标签相关表 ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS patient_group_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS patient_group_links (
                patient_name TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (patient_name, tag_id),
                FOREIGN KEY (patient_name) REFERENCES patient_profiles(patient_name) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES patient_group_tags(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visit_mark_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visit_mark_links (
                visit_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (visit_id, tag_id),
                FOREIGN KEY (visit_id) REFERENCES visits(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES visit_mark_tags(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()

def upgrade_database(db_path="aurum_index.db"):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # ---- 检查并添加新表（如果不存在） ----
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='patient_group_tags'")
        if not cursor.fetchone():
            cursor.execute('''
                CREATE TABLE patient_group_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag_name TEXT UNIQUE NOT NULL
                )
            ''')
            print("✅ 已创建表：patient_group_tags")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='patient_group_links'")
        if not cursor.fetchone():
            cursor.execute('''
                CREATE TABLE patient_group_links (
                    patient_name TEXT NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (patient_name, tag_id),
                    FOREIGN KEY (patient_name) REFERENCES patient_profiles(patient_name) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES patient_group_tags(id) ON DELETE CASCADE
                )
            ''')
            print("✅ 已创建表：patient_group_links")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visit_mark_tags'")
        if not cursor.fetchone():
            cursor.execute('''
                CREATE TABLE visit_mark_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag_name TEXT UNIQUE NOT NULL
                )
            ''')
            print("✅ 已创建表：visit_mark_tags")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visit_mark_links'")
        if not cursor.fetchone():
            cursor.execute('''
                CREATE TABLE visit_mark_links (
                    visit_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (visit_id, tag_id),
                    FOREIGN KEY (visit_id) REFERENCES visits(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES visit_mark_tags(id) ON DELETE CASCADE
                )
            ''')
            print("✅ 已创建表：visit_mark_links")

        # ---- 检查 visits 表的唯一约束是否已改为联合唯一 ----
        # 由于 SQLite 不支持直接修改 UNIQUE 约束，我们需要重建表
        # 但考虑到你已删除旧数据，我们可以直接使用新表结构
        # 如果 visits 表已存在且 docx_path 仍有 UNIQUE 约束，需要处理
        cursor.execute("PRAGMA table_info(visits)")
        columns = [row[1] for row in cursor.fetchall()]
        # <--- 插入检查 western_diagnosis 的代码在此 --->
        if 'western_diagnosis' not in columns:
            cursor.execute("ALTER TABLE visits ADD COLUMN western_diagnosis TEXT")
            print("✅ 已添加列：western_diagnosis")
        if 'docx_path' in columns and 'visit_mark' in columns:
            # 这是旧版本的表，我们需要删除 visit_mark 列（已被标签表替代）
            # 但 SQLite 不支持直接 DROP COLUMN，需要重建
            # 考虑到你已删除旧数据，最简单的方法是删除表重建
            # 但为了安全，我们只做增量添加
            pass

        conn.commit()

def scan_and_index_archived_folder(target_root, db_path="aurum_index.db"):
    """
    扫描已归档的目标文件夹（医院/患者/日期），将文件路径写入 visits 表。
    用于初始化索引或同步新增/变更的文件路径。
    如果记录已存在（基于 docx_path UNIQUE），则忽略重复插入。
    """
    if not os.path.exists(target_root):
        print(f"❌ 路径不存在：{target_root}")
        return

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 遍历第一层：医院文件夹
        for hospital in os.listdir(target_root):
            hospital_path = os.path.join(target_root, hospital)
            if not os.path.isdir(hospital_path):
                continue

            # 遍历第二层：患者文件夹
            for patient in os.listdir(hospital_path):
                patient_path = os.path.join(hospital_path, patient)
                if not os.path.isdir(patient_path):
                    continue

                # 遍历第三层：日期文件夹
                for visit_date in os.listdir(patient_path):
                    date_path = os.path.join(patient_path, visit_date)
                    if not os.path.isdir(date_path):
                        continue

                    # 查找该日期下的病历文件（取第一个 .docx / .doc / .txt）
                    docx_file = None
                    image_files = []
                    for file in os.listdir(date_path):
                        file_path = os.path.join(date_path, file)
                        if os.path.isfile(file_path):
                            if file.lower().endswith(('.docx', '.doc', '.txt')):
                                docx_file = file_path
                                break  # 只取第一个，可根据需要调整
                            elif file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif')):
                                image_files.append(file_path)

                    # 如果找到了病历文档，则写入数据库
                    if docx_file:
                        images_str = ';'.join(image_files) if image_files else ''
                        try:
                            cursor.execute('''
                                INSERT OR IGNORE INTO visits 
                                (patient_name, visit_date, hospital, docx_path, images_path)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (patient, visit_date, hospital, docx_file, images_str))
                        except Exception as e:
                            print(f"⚠️ 写入失败 {docx_file}: {e}")

        conn.commit()
        print(f"✅ 索引扫描完成！数据库已更新：{db_path}")

def search_by_diagnosis(db_path, keyword):
    """按诊断关键词搜索，返回 (patient_name, visit_date, hospital, diagnosis, docx_path)"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT patient_name, visit_date, hospital, diagnosis, docx_path 
            FROM visits 
            WHERE diagnosis LIKE ? 
            ORDER BY patient_name, visit_date
        """, (f'%{keyword}%',))
        results = cursor.fetchall()
        return results

def get_visit_dates_for_patient(patient_name: str, db_path="aurum_index.db") -> List[str]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT visit_date FROM visits WHERE patient_name = ? ORDER BY visit_date ASC", (patient_name,))
        rows = cursor.fetchall()
        return [row[0] for row in rows]

def get_all_patient_names(db_path="aurum_index.db") -> List[str]:
    """获取所有不重复的患者姓名，按拼音升序排列"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT patient_name FROM visits")
        rows = cursor.fetchall()
        names = [row[0] for row in rows]
        # 按拼音排序（先按全拼，再按首字母，确保一致性）
        return sorted(names, key=lambda x: ''.join([p[0] for p in pinyin(x, style=Style.NORMAL)]))

def get_docx_path(patient_name: str, visit_date: str, db_path="aurum_index.db") -> str:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT docx_path FROM visits WHERE patient_name = ? AND visit_date = ?", (patient_name, visit_date))
        row = cursor.fetchone()
        return row[0] if row else None

def get_patient_profile(patient_name: str, db_path="aurum_index.db") -> dict:
    """获取患者档案中的所有敏感信息"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT patient_name, gender, birth_date, id_card, phone, address FROM patient_profiles WHERE patient_name = ?",
            (patient_name,)
        )
        row = cursor.fetchone()
        if row:
            return {
                'real_name': row[0],
                'gender': row[1] or '',
                'birth_date': row[2] or '',
                'id_card': row[3] or '',
                'phone': row[4] or '',
                'address': row[5] or ''
            }
        return {'real_name': patient_name, 'gender': '', 'birth_date': '', 'id_card': '', 'phone': '', 'address': ''}

def check_existing_diagnosis(patient_name: str, visit_date: str, db_path="aurum_index.db") -> tuple:
    """
    检查指定就诊记录是否已有诊断或方剂
    返回: (has_diagnosis, has_prescription, diagnosis_content, prescription_content)
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT diagnosis, prescription FROM visits WHERE patient_name = ? AND visit_date = ?",
            (patient_name, visit_date)
        )
        row = cursor.fetchone()

        if not row:
            return False, False, None, None

        diagnosis = row[0]
        prescription = row[1]

        has_diagnosis = bool(diagnosis and diagnosis != "[]")
        has_prescription = bool(prescription and prescription != "[]")

        # 解析 JSON 为可读字符串（用于提示）
        def parse_json(val):
            if not val:
                return None
            try:
                lst = json.loads(val)
                if isinstance(lst, list) and lst:
                    return '、'.join(lst)
                return val
            except:
                return val

        diag_display = parse_json(diagnosis) if has_diagnosis else None
        presc_display = parse_json(prescription) if has_prescription else None

        return has_diagnosis, has_prescription, diag_display, presc_display

def get_all_visits_for_patient(patient_name: str, db_path="aurum_index.db") -> List[Dict]:
    """获取某患者所有就诊记录，按日期升序排列"""
    import sqlite3
    from typing import List, Dict
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT visit_date, hospital, diagnosis, prescription, full_medical_text, visit_remarks
            FROM visits
            WHERE patient_name = ?
            ORDER BY visit_date ASC
        """, (patient_name,))
        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                'visit_date': row[0],
                'hospital': row[1],
                'diagnosis': row[2] or '',
                'prescription': row[3] or '',
                'full_medical_text': row[4] or '',
                'visit_remarks': row[5] or ''
            })
        return results

def get_patient_folder(patient_name: str, db_path="aurum_index.db") -> str:
    """获取患者档案所在的文件夹路径（例如：.../医院/患者/）"""
    import os
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT docx_path FROM visits WHERE patient_name = ? LIMIT 1", (patient_name,))
        row = cursor.fetchone()
        if row and row[0]:
            # docx_path 格式：医院/患者/日期/病历.docx，向上两级得到医院/患者/
            return os.path.dirname(os.path.dirname(row[0]))
        return None

def get_all_patient_folders(patient_name: str, db_path="aurum_index.db") -> list:
    """获取某患者在所有医院下的文件夹路径列表"""
    import os
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        # 获取该患者所有就诊记录的 docx_path
        cursor.execute("SELECT docx_path FROM visits WHERE patient_name = ?", (patient_name,))
        rows = cursor.fetchall()

        folders = []
        seen = set()
        for row in rows:
            if row[0]:
                # docx_path 格式：医院/患者/日期/病历.docx，向上两级得到医院/患者/
                folder = os.path.dirname(os.path.dirname(row[0]))
                if folder not in seen:
                    folders.append(folder)
                    seen.add(folder)
        return folders

def check_file_validity(db_path="aurum_index.db") -> dict:
    """
    扫描 visits 表中的所有 docx_path，检查文件是否存在。
    返回字典：{'valid': [(id, patient_name, visit_date, path)], 'invalid': [(id, patient_name, visit_date, path)]}
    """
    import os
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, patient_name, visit_date, docx_path FROM visits WHERE docx_path IS NOT NULL")
        rows = cursor.fetchall()

        valid = []
        invalid = []
        for row in rows:
            record_id, patient_name, visit_date, docx_path = row
            if os.path.exists(docx_path):
                valid.append(row)
            else:
                invalid.append(row)
        return {'valid': valid, 'invalid': invalid}

def load_all_visits_with_tags(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)

    # ---- 1. 主查询 ----
    query_visits = """
    SELECT 
        v.id,
        v.patient_name AS 患者姓名,
        p.gender AS 性别,
        p.birth_date AS 出生日期,
        p.phone AS 电话,
        p.id_card AS 身份证号,
        p.address AS 住址,
        p.personal_remarks AS 个人信息备注,
        v.visit_date AS 就诊日期,
        v.hospital AS hospital,
        v.diagnosis AS 中医诊断, 
        v.western_diagnosis AS 西医诊断, 
        v.prescription AS 方剂,
        v.full_medical_text AS 病历,
        v.visit_remarks AS 就诊备注,
        v.docx_path AS 文件路径
    FROM visits v
    LEFT JOIN patient_profiles p ON v.patient_name = p.patient_name
    ORDER BY v.patient_name, v.visit_date
    """
    df = pd.read_sql_query(query_visits, conn)

    # ---- 2. 分组标签字典 ----
    query_groups = """
    SELECT pgl.patient_name, gt.tag_name
    FROM patient_group_links pgl
    JOIN patient_group_tags gt ON pgl.tag_id = gt.id
    """
    df_groups = pd.read_sql_query(query_groups, conn)
    group_dict = {}
    if not df_groups.empty:
        for _, row in df_groups.iterrows():
            group_dict.setdefault(row['patient_name'], []).append(row['tag_name'])
    df['患者分组列表'] = df['患者姓名'].apply(lambda name: group_dict.get(name, []))

    # ---- 3. 就诊标记字典 ----
    query_marks = """
    SELECT vml.visit_id, mt.tag_name
    FROM visit_mark_links vml
    JOIN visit_mark_tags mt ON vml.tag_id = mt.id
    """
    df_marks = pd.read_sql_query(query_marks, conn)
    mark_dict = {}
    if not df_marks.empty:
        for _, row in df_marks.iterrows():
            vid = int(row['visit_id'])
            tag = row['tag_name']
            mark_dict.setdefault(vid, []).append(tag)

    df['id'] = df['id'].astype(int)
    df['就诊标记列表'] = df['id'].apply(lambda vid: mark_dict.get(vid, []))

    conn.close()
    df = df.rename(columns={'hospital': '医院/科室'})
    df.reset_index(drop=True, inplace=True)  # 新增：重置索引
    return df

def clean_orphan_tags(conn=None):
    """
    删除孤儿标签：不再被任何记录引用的标签。
    如果传入 conn，则使用该连接（不自动提交，由调用方控制事务）。
    如果传入 None，则创建新连接并自动提交。
    """
    if conn is None:
        conn = sqlite3.connect(get_db_path())
        should_close = True
    else:
        should_close = False

    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM patient_group_tags 
        WHERE id NOT IN (SELECT tag_id FROM patient_group_links)
    """)
    cursor.execute("""
        DELETE FROM visit_mark_tags 
        WHERE id NOT IN (SELECT tag_id FROM visit_mark_links)
    """)

    if should_close:
        conn.commit()
        conn.close()
