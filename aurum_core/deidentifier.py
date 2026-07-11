# ============================================================
# 脱敏模块（基于真实姓名的精确替换 + 标签替换）
# 策略：
#   1. 从数据库读取患者档案（性别、出生日期、年龄、真实姓名、身份证号、电话）
#   2. 对病历全文执行两个层次的替换：
#      a. 直接替换“患者真实姓名”出现的所有位置（连续字符串）
#      b. 替换带有标签的敏感信息（如“电话：139...”等）
#      c. 额外替换身份证号（格式匹配）
#   3. 保留所有行结构，保留医学描述
# ============================================================
import re
import os
import sqlite3
from aurum_core.text_utils import read_file_content

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "aurum_index.db")


def extract_safe_content(file_path: str, patient_name: str, visit_date: str = None) -> str:
    # 1. 获取档案信息（包括真实姓名、身份证号、电话）
    profile = _get_patient_profile(patient_name)
    gender = profile.get('gender', '')
    birth_date = profile.get('birth_date', '')
    real_name = profile.get('real_name', patient_name)
    id_card = profile.get('id_card', '')
    phone = profile.get('phone', '')

    if not visit_date:
        visit_date = _get_latest_visit_date(patient_name)

    # 2. 读取全文
    text = read_file_content(file_path)
    if not text:
        return ""

    # 3. 脱敏处理（传递所有敏感值）
    safe_text = _sanitize_text(text, real_name, id_card, phone)

    if not safe_text.strip():
        return "（该病历未包含可识别的医学描述内容）"

    # 4. 组装输出
    parts = []
    if gender:
        parts.append(f"性别：{gender}")
    if birth_date:
        parts.append(f"出生日期：{birth_date}")
    if visit_date:
        parts.append(f"就诊日期：{visit_date}")

    parts.append("\n" + safe_text)
    return "\n".join(parts).strip()


# ---------- 内部辅助函数 ----------

def _get_patient_profile(patient_name):
    result = {
        'real_name': patient_name,
        'gender': '',
        'birth_date': '',
        'id_card': '',
        'phone': ''
    }
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT patient_name, gender, birth_date, id_card, phone FROM patient_profiles WHERE patient_name = ?",
            (patient_name,)
        )
        row = cursor.fetchone()
        if row:
            result['real_name'] = row[0]
            result['gender'] = row[1] or ''
            result['birth_date'] = row[2] or ''
            result['id_card'] = row[3] or ''
            result['phone'] = row[4] or ''
    except Exception as e:
        print(f"⚠️ 读取患者档案失败：{e}")
    return result


def _get_latest_visit_date(patient_name):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT visit_date FROM visits WHERE patient_name = ? ORDER BY visit_date DESC LIMIT 1",
            (patient_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else ""
    except Exception:
        return ""

def _sanitize_text(text: str, real_name: str, id_card: str = '', phone: str = '') -> str:
    """
    脱敏处理：
    1. 替换患者真实姓名（全局）
    2. 替换身份证号（全局匹配）
    3. 替换手机号（全局匹配）
    4. 替换带标签的敏感信息（电话、住址、身份证等）
    """
    # 1. 替换真实姓名
    if real_name:
        escaped = re.escape(real_name)
        text = re.sub(escaped, '[已脱敏]', text)

    # 2. 替换身份证号（如果提供了）
    if id_card:
        escaped_id = re.escape(id_card)
        text = re.sub(escaped_id, '[已脱敏]', text)
    # 额外匹配标准身份证格式（15或18位，含X）以防数据库未记录但文本中出现
    text = re.sub(r'\b[1-9]\d{16}[\dXx]\b', '[已脱敏]', text)
    text = re.sub(r'\b[1-9]\d{14}\b', '[已脱敏]', text)

    # 3. 替换手机号（如果提供了）
    if phone:
        escaped_phone = re.escape(phone)
        text = re.sub(escaped_phone, '[已脱敏]', text)
    # 额外匹配中国大陆手机号（11位，1开头）
    text = re.sub(r'\b1[3-9]\d{9}\b', '[已脱敏]', text)

    # 4. 替换带标签的敏感信息
    text = re.sub(
        r'(姓名|患者姓名|名字|患者)\s*[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(
        r'(电话|手机|手机号|联系电话)\s*[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(
        r'(住址|家庭住址|地址|联系地址)\s*[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(
        r'(身份证|身份证号|证件号|ID)\s*[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )

    # 5. 删除裸露的邮箱、微信号等
    text = re.sub(r'\b\S+@\S+\.\S+\b', '[已脱敏]', text)
    text = re.sub(r'\b(?:wxid_|wx_|vx_)[a-zA-Z0-9_]+\b', '[已脱敏]', text, flags=re.IGNORECASE)
    text = re.sub(r'\b[1-9]\d{4,10}\b', '[已脱敏]', text)  # QQ号
    text = re.sub(r'\b[GD]?\d{8,18}\b', '[已脱敏]', text)  # 医保卡号常见格式
    text = re.sub(
        r'(住院号|记录册号|医保号|卡号|ID卡号)\s*[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )

    # 新增：工作单位/地址的标签替换
    text = re.sub(
        r'(工作单位|单位|工作地址)\s*[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )
    # 额外匹配裸露的医保号格式（如 GD12345678）
    text = re.sub(r'\b[GD]?\d{8,18}\b', '[已脱敏]', text)

    # 替换医生姓名（按标签）
    text = re.sub(
        r'(主治医师|住院医师|执业医师|处方医师|主诊医师|指导医师|经治医师|医生签名|医师签名|签名|医师|医生|供史者)[：:]\s*[^\n\r，,、；;。]*',
        r'\g<1>：[已脱敏]',
        text,
        flags=re.IGNORECASE
    )

    return text
