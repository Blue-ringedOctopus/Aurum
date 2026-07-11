# aurum_core/text_utils.py
import re
import os
import sqlite3
import json
from docx import Document
from typing import List, Dict
import streamlit as st

def read_file_content(file_path: str) -> str:
    """读取 docx/txt 文件内容，返回文本字符串"""
    if not os.path.exists(file_path):
        return ""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.docx':
            doc = Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs])
        elif ext == '.doc':
            import platform
            if platform.system() == 'Windows':
                import win32com.client
                import pythoncom
                pythoncom.CoInitialize()
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                doc = word.Documents.Open(file_path)
                content = doc.Content.Text
                doc.Close()
                word.Quit()
                return content
        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            # Mac/Linux：使用系统命令 textutil（Mac 自带）
            import subprocess
            try:
                result = subprocess.run(
                    ['textutil', '-convert', 'txt', '-output', '-', file_path],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    return result.stdout
                else:
                    return ""
            except:
                return ""
    except Exception:
        return ""

def extract_prescription_from_text(text: str) -> str:
    """
    从病历文本中自动提取方剂内容（规则提取，非AI）
    支持：
    1. 标准起始词：药方、方药、处方、方剂、拟方、治以
    2. 日期+方模式：如“3/27方-滑石-通草+生龙牡30 灵芝9 合欢皮15*7”
    """
    # 1. 尝试标准起始词
    start_pattern = re.compile(
        r'(?:药方|方药|处方|方剂|拟方|治以|草药)\s*[：:]?\s*',
        re.IGNORECASE
    )
    match = start_pattern.search(text)
    if match:
        start_pos = match.end()
        remaining = text[start_pos:]

        # 结束词截断
        end_keywords = [
            r'嘱(?:其)?(?!咐)',
            r'忌(?:食)?',
            r'注意',
            r'随访',
            r'继服',
            r'巩固',
            r'再进',
            r'另服',
            r'按语',
            r'反馈',
            r'复诊',
            r'(\n\s*[【\[])',
            r'[\n\r]{2,}',
        ]
        end_pattern = re.compile('|'.join(end_keywords), re.IGNORECASE)
        end_match = end_pattern.search(remaining)
        if end_match:
            extracted = remaining[:end_match.start()]
        else:
            lines = remaining.split('\n')
            extracted = lines[0] if lines else remaining

        extracted = extracted.strip()
        extracted = re.sub(r'^[：:、，,]+', '', extracted)
        extracted = re.sub(r'[；;，,]\s*$', '', extracted)
        return extracted

    # 2. 尝试日期+方模式（如“3/27方-xxx”）
    date_pattern = re.compile(
        r'(\d{1,2}/\d{1,2}|\d{4}-\d{1,2}-\d{1,2})\s*方\s*([^\n\r]+)',
        re.IGNORECASE
    )
    match = date_pattern.search(text)
    if match:
        # 返回整个匹配内容（包括日期和药物）
        full_match = match.group(0).strip()
        return full_match

    # 3. 都匹配不到，返回空
    return ""


def extract_diagnosis(text: str, default_to_tcm: bool = True) -> tuple:
    if not text:
        return [], []

    # ---- 所有边界关键词（每个词都支持带冒号和不带冒号） ----
    boundary_keywords = [
        '主诉', '现病史', '既往史', '过敏史', '个人史', '家族史', '婚育史', '月经史',
        '舌脉', '脉象', '舌象', '中医四诊', '望诊', '闻诊', '问诊', '切诊',
        '体格检查', '辅助检查', '实验室检查', '影像学检查',
        '方药', '处方', '药方', '治则', '治法', '按语', '备注', '诊断依据',
        '医师签名', '医生', '医师', '随访', '复诊', '处理意见', '诊疗意见',
        '处理', '草药',  # 这两个作为独立边界
        '西医诊断', '中医诊断', '中医诊断及证型', '初步诊断', '出院诊断', '入院诊断',
        '鉴别诊断'
    ]

    # ---- 构建边界模式：每个关键词后可选冒号 ----
    boundary_pattern = '|'.join([kw + r'(?:[：:]?)' for kw in boundary_keywords])
    next_field_pattern = r'\s*(?:' + boundary_pattern + r')'

    tcm_items = []
    wm_items = []

    # 中医诊断
    pattern_tcm = re.compile(
        r'(?:中医诊断|辨证|证型|中医诊断及证型)\s*[：:]\s*([\s\S]*?)(?=' + next_field_pattern + r'|$)',
        re.IGNORECASE
    )
    for match in pattern_tcm.findall(text):
        cleaned = _clean_diagnostic_match(match)
        if cleaned:
            tcm_items.extend(_split_diagnosis_items(cleaned))

    # 西医诊断
    wm_keywords = r'(?:西医诊断|西医诊断及鉴别诊断|疾病诊断|临床诊断|初步诊断|出院诊断|入院诊断|最后诊断|最终诊断|主要诊断)'
    pattern_wm = re.compile(
        wm_keywords + r'\s*[：:]\s*([\s\S]*?)(?=' + next_field_pattern + r'|$)',
        re.IGNORECASE
    )
    for match in pattern_wm.findall(text):
        cleaned = _clean_diagnostic_match(match)
        if cleaned:
            wm_items.extend(_split_diagnosis_items(cleaned))

    # 通用“诊断”
    pattern_generic = re.compile(
        r'(?:^|\n)\s*诊断\s*[：:]\s*([\s\S]*?)(?=' + next_field_pattern + r'|$)',
        re.IGNORECASE
    )
    for match in pattern_generic.findall(text):
        cleaned = _clean_diagnostic_match(match)
        if cleaned:
            items = _split_diagnosis_items(cleaned)
            if default_to_tcm:
                tcm_items.extend(items)
            else:
                wm_items.extend(items)

    tcm_items = _deduplicate(tcm_items)
    wm_items = _deduplicate(wm_items)
    return tcm_items, wm_items


def _clean_diagnostic_match(raw: str) -> str:
    """清理提取到的诊断内容（移除多余空白）"""
    if not raw:
        return ""
    return raw.strip()


def _split_diagnosis_items(raw: str) -> list:
    if not raw:
        return []
    raw = raw.strip()
    # 只使用中英文标点作为分隔符（不把换行/制表符当分隔符）
    items = re.split(r'[，,、；;]\s*', raw)
    cleaned = []
    for item in items:
        item = item.strip()
        item = re.sub(r'^\d+[.、)）]\s*', '', item)
        item = item.strip('，,、；;。.')
        if item and len(item) >= 2:
            cleaned.append(item)
    return cleaned


def _deduplicate(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def check_sensitive_info(text: str, patient_name: str, db_path="aurum_index.db") -> tuple:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # 查询所有可能敏感的字段（根据实际表结构扩展）
    cursor.execute(
        "SELECT patient_name, id_card, phone, address FROM patient_profiles WHERE patient_name = ?",
        (patient_name,)
    )
    row = cursor.fetchone()
    if not row:
        return False, []
    real_name, id_card, phone, address = row  # 这里改为4个变量
    sensitive_data = []
    if real_name and real_name in text:
        sensitive_data.append("姓名")
    if id_card and id_card in text:
        sensitive_data.append("身份证号")
    if phone and phone in text:
        sensitive_data.append("电话")
    if address and address in text:
        sensitive_data.append("住址")
    if sensitive_data:
        return True, sensitive_data
    return False, []

def merge_patient_visits_text(visits: List[Dict]) -> str:
    """将多次就诊记录合并为一段文本，用于按语生成"""
    parts = []
    for i, v in enumerate(visits, 1):
        part = f"【第{i}次就诊】\n"
        part += f"日期：{v['visit_date']}\n"
        part += f"医院：{v['hospital']}\n"
        if v['diagnosis']:
            part += f"诊断：{v['diagnosis']}\n"
        if v['prescription']:
            part += f"方剂：{v['prescription']}\n"
        if v['full_medical_text']:
            # 只取前1500字符防止过长，可按需调整
            full_text = v['full_medical_text'][:3000] + ('...' if len(v['full_medical_text']) > 3000 else '')
            part += f"病历内容：\n{full_text}\n"
        if v['visit_remarks']:
            part += f"备注：{v['visit_remarks']}\n"
        parts.append(part)
    return "\n".join(parts)

def parse_json_list(val):
    """解析 JSON 列表字段，返回中文顿号分隔的字符串"""
    if not val:
        return ""
    try:
        lst = json.loads(val)
        if isinstance(lst, list):
            return '、'.join(lst)
        return str(val)
    except:
        return str(val)

from pypinyin import pinyin, Style

def get_pinyin(name):
    return ''.join([p[0] for p in pinyin(name, style=Style.NORMAL)])

def render_sensitive_warning(text: str, patient_name: str, session_key: str, button_key: str) -> bool:
    """
    显示敏感信息警告并处理“已手动处理”按钮。
    返回 True 表示已通过检测（无敏感信息或用户已忽略），返回 False 表示触发了警告并停止。
    """
    from aurum_core.text_utils import check_sensitive_info
    if session_key not in st.session_state:
        st.session_state[session_key] = False
    has_sensitive = False
    if not st.session_state[session_key]:
        has_sensitive, fields = check_sensitive_info(text, patient_name)
    if has_sensitive and not st.session_state[session_key]:
        col_warn, col_btn = st.columns([4, 1.5])
        with col_warn:
            st.error(f"⛔ 检测到输入文本中包含患者的敏感信息（{', '.join(fields)}），请先脱敏！")
        with col_btn:
            if st.button("⚠️ 已手动处理敏感信息", key=button_key, use_container_width=True):
                st.session_state[session_key] = True
                st.rerun()
        st.stop()
        return False
    else:
        st.session_state[session_key] = False
        return True

# 在 aurum_core/text_utils.py 末尾添加
def normalize_date_str(date_str: str) -> str:
    """
    将多种日期格式标准化为 YYYY-MM-DD
    支持的格式：YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYY年MM月DD日
    """
    from datetime import datetime
    if not date_str:
        return date_str
    date_str = date_str.strip()
    for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d', '%Y年%m月%d日', '%Y年%m月%d'):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    return date_str  # 如果无法解析，返回原字符串
