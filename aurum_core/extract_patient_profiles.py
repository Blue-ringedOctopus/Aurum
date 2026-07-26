# ============================================================
# 患者档案信息提取模块
# 功能：
#   - 从初诊病历中提取患者固定信息（性别、出生日期等）
#   - 支持多种日期格式
#   - 纯本地操作
# 调用方式：
#   - 独立运行：python aurum_core/extract_patient_profiles.py
#   - 归档后自动调用：update_all_profiles()
# ============================================================
import sqlite3
import os
import re
from datetime import datetime
from aurum_core.text_utils import read_file_content, normalize_date_str

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "aurum_index.db")


# ==================== 工具函数 ====================
def extract_patient_info(text: str) -> tuple:
    """
    从病历文本中提取患者固定信息。
    返回 (dict, age) ，dict包含 gender, birth_date, phone, id_card, address
    """
    result = {
        'gender': None,
        'birth_date': None,
        'phone': None,
        'id_card': None,
        'address': None
    }
    age = None

    if not text:
        print("⚠️ extract_patient_info 收到空文本")
        return result, age

    # ---- 使用全文搜索，支持有分隔符和无分隔符的情况 ----
    # 1. 性别：支持 "性别：女"、"性别 女"、"性别女"
    gender_match = re.search(r'性别\s*[：:]\s*(男|女)|性别\s*(男|女)', text, re.IGNORECASE)
    if gender_match:
        result['gender'] = gender_match.group(1) or gender_match.group(2)
        print(f"✅ 提取到性别：{result['gender']}")

    # 2. 年龄：支持 "年龄：40岁"、"年龄 40岁"、"年龄40岁"
    age_match = re.search(r'年龄\s*[：:]\s*(\d+)|年龄\s*(\d+)', text, re.IGNORECASE)
    if age_match:
        age = int(age_match.group(1) or age_match.group(2))
        print(f"✅ 提取到年龄：{age}")

    # 3. 出生日期：支持 "出生日期：2006.4.2"、"出生日期2006.4.2"
    birth_match = re.search(r'(?:出生日期|出生年月|生日|出生)\s*[：:]\s*([^\s]+)|(?:出生日期|出生年月|生日|出生)\s*([^\s]+)', text, re.IGNORECASE)
    if birth_match:
        raw = birth_match.group(1) or birth_match.group(2)
        if raw:
            dt = normalize_date_str(raw.strip())
            if dt:
                result['birth_date'] = dt
                print(f"✅ 提取到出生日期：{dt}")

    # 4. 电话：支持 "电话：138xxxx"、"电话138xxxx"
    phone_match = re.search(r'(?:电话|手机|联系电话)\s*[：:]\s*([\d\-]+)|(?:电话|手机|联系电话)\s*([\d\-]+)', text, re.IGNORECASE)
    if phone_match:
        raw = phone_match.group(1) or phone_match.group(2)
        if raw:
            phone_clean = re.sub(r'[^\d]', '', raw)
            if len(phone_clean) >= 7:
                result['phone'] = phone_clean
                print(f"✅ 提取到电话：{result['phone']}")

    # 5. 身份证：支持 "身份证号：310..."、"身份证号310..."
    id_match = re.search(r'(?:身份证|身份证号|证件号|ID)\s*[：:]\s*([^\s]+)|(?:身份证|身份证号|证件号|ID)\s*([^\s]+)', text, re.IGNORECASE)
    if id_match:
        raw = id_match.group(1) or id_match.group(2)
        if raw:
            id_clean = re.sub(r'[^\dXx]', '', raw)
            if len(id_clean) in (15, 18):
                result['id_card'] = id_clean.upper()
                print(f"✅ 提取到身份证：{result['id_card']}")

    # 6. 地址：支持 "地址：花园路"、"地址花园路"
    addr_match = re.search(r'(?:住址|家庭住址|地址|联系地址)\s*[：:]\s*(.+)|(?:住址|家庭住址|地址|联系地址)\s*(.+)', text, re.IGNORECASE)
    if addr_match:
        result['address'] = (addr_match.group(1) or addr_match.group(2)).strip()
        print(f"✅ 提取到地址：{result['address']}")

    # ---- 备选方案（当标签匹配失败时） ----
    # 备选1：直接匹配身份证号码（15或18位）
    if not result.get('id_card'):
        id_raw = re.search(r'\b[1-9]\d{16}[\dXx]\b|\b[1-9]\d{14}\b', text)
        if id_raw:
            result['id_card'] = id_raw.group().upper()
            print(f"✅ 备选提取到身份证：{result['id_card']}")

    # 备选2：从身份证提取出生日期
    if not result.get('birth_date') and result.get('id_card'):
        id_birth = extract_birth_from_id(result['id_card'])
        if id_birth:
            result['birth_date'] = id_birth
            print(f"✅ 从身份证提取出生日期：{id_birth}")

    return result, age

def extract_birth_from_id(id_card: str) -> str:
    """从身份证号中提取出生日期，返回 YYYY-MM-DD 格式，若无效返回空字符串"""
    if not id_card:
        return ""
    id_card = id_card.strip().upper()
    if len(id_card) in (15, 18):
        try:
            if len(id_card) == 15:
                birth_str = id_card[6:12]
                year = 1900 + int(birth_str[:2])
                month = int(birth_str[2:4])
                day = int(birth_str[4:6])
            else:  # 18位
                birth_str = id_card[6:14]
                year = int(birth_str[:4])
                month = int(birth_str[4:6])
                day = int(birth_str[6:8])
            # 简单有效性检查
            if 1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
        except:
            pass
    return ""

def update_patient_profile(patient_name: str, info: dict, first_visit_date: str):
    """插入或更新 patient_profiles 表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM patient_profiles WHERE patient_name = ?", (patient_name,))
    exists = cursor.fetchone()
    if exists:
        cursor.execute('''
            UPDATE patient_profiles SET 
                gender = ?, birth_date = ?, phone = ?, id_card = ?, address = ?, first_visit_date = ?
            WHERE patient_name = ?
        ''', (
            info.get('gender'),
            info.get('birth_date'),
            info.get('phone'),
            info.get('id_card'),
            info.get('address'),
            first_visit_date,
            patient_name
        ))
    else:
        cursor.execute('''
            INSERT INTO patient_profiles 
            (patient_name, gender, birth_date, phone, id_card, address, first_visit_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_name,
            info.get('gender'),
            info.get('birth_date'),
            info.get('phone'),
            info.get('id_card'),
            info.get('address'),
            first_visit_date
        ))
    conn.commit()


# ==================== 核心函数 ====================
def update_all_profiles():
    """供归档调用的入口：遍历所有患者，提取所有就诊记录并合并信息（补空不覆盖）。"""
    print("🔄 开始更新所有患者档案（合并模式）...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT patient_name FROM visits")
    patients = [row[0] for row in cursor.fetchall()]
    if not patients:
        print("⚠️ 数据库为空，无患者可更新。")
        return

    for patient in patients:
        # 获取该患者所有就诊记录（按日期升序）
        cursor.execute(
            "SELECT visit_date, docx_path FROM visits WHERE patient_name = ? ORDER BY visit_date ASC",
            (patient,)
        )
        rows = cursor.fetchall()
        if not rows:
            continue

        merged_info = {
            'gender': None,
            'birth_date': None,
            'phone': None,
            'id_card': None,
            'address': None
        }
        age = None
        first_visit_date = None

        for visit_date, docx_path in rows:
            if not docx_path:
                continue
            if not os.path.exists(docx_path):
                print(f"⚠️ {patient} 文件缺失：{docx_path}，跳过")
                continue
            text = read_file_content(docx_path)
            if not text:
                continue

            info, age_from_this = extract_patient_info(text)
            # 合并信息：只填补空字段
            for key in merged_info:
                if merged_info[key] is None and info.get(key):
                    merged_info[key] = info.get(key)
            if age is None and age_from_this is not None:
                age = age_from_this
            if first_visit_date is None:
                first_visit_date = visit_date

            # 如果所有字段都已填满，可以提前跳出（但年龄和首诊日期可能还需要）
            # 我们保留继续遍历，但若所有个人信息已齐，可考虑 break（可选）
            # 为保持简单，不 break，确保首诊日期为最早日期（已在循环外得到）

        # ---- 补全出生日期（如果仍为空且年龄存在） ----
        if merged_info['birth_date'] is None and age and first_visit_date:
            visit_date_normalized = normalize_date_str(first_visit_date)
            birth_year = None
            if visit_date_normalized:
                try:
                    visit_dt = datetime.strptime(visit_date_normalized, '%Y-%m-%d')
                    birth_year = visit_dt.year - age
                except ValueError:
                    print(f"日期解析失败：{first_visit_date}")
            if birth_year is not None:
                current_year = datetime.now().year
                if 1900 <= birth_year <= current_year + 1:
                    merged_info['birth_date'] = f"{birth_year}-01-01"
                    print(f"   ℹ️ {patient} 根据年龄 {age} 推算出出生年份 {birth_year}")

        # ---- 更新数据库 ----
        # 检查是否存在记录
        cursor.execute("SELECT 1 FROM patient_profiles WHERE patient_name = ?", (patient,))
        exists = cursor.fetchone()
        if exists:
            # 更新（仅当有变化）
            update_fields = []
            update_values = []
            for key in merged_info:
                if merged_info[key] is not None:
                    update_fields.append(f"{key} = ?")
                    update_values.append(merged_info[key])
            if first_visit_date:
                update_fields.append("first_visit_date = ?")
                update_values.append(first_visit_date)
            if update_fields:
                update_values.append(patient)
                query = f"UPDATE patient_profiles SET {', '.join(update_fields)} WHERE patient_name = ?"
                cursor.execute(query, update_values)
                print(f"✅ {patient} 档案已更新（合并后信息）")
        else:
            # 插入
            cursor.execute(
                """INSERT INTO patient_profiles 
                   (patient_name, gender, birth_date, phone, id_card, address, first_visit_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (patient,
                 merged_info.get('gender'),
                 merged_info.get('birth_date'),
                 merged_info.get('phone'),
                 merged_info.get('id_card'),
                 merged_info.get('address'),
                 first_visit_date)
            )
            print(f"✅ {patient} 档案已创建（合并后信息）")

    conn.commit()
    print("✅ 所有患者档案更新完成。")

# ==================== 独立运行入口 ====================
def rebuild_table_and_update():
    """重建 patient_profiles 表并重新提取所有信息（慎用）"""
    print("⚠️ 正在重建 patient_profiles 表...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS patient_profiles")
    cursor.execute('''
        CREATE TABLE patient_profiles (
            patient_name TEXT PRIMARY KEY,
            gender TEXT,
            birth_date TEXT,
            phone TEXT,
            id_card TEXT,
            address TEXT,
            first_visit_date TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    print("✅ 表已重建。")
    update_all_profiles()


if __name__ == "__main__":
    # 独立运行时，默认重建表并更新（适合首次运行或数据修复）
    rebuild_table_and_update()