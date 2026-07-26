import sqlite3
import json
import os
from datetime import datetime
from aurum_core.database import get_db_path

def export_database(db_path=None):
    """导出数据库为JSON格式（与之前相同）"""
    if db_path is None:
        db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    data = {
        "export_time": datetime.now().isoformat(),
        "version": "1.0",
        "patient_profiles": [],
        "visits": [],
        "patient_group_tags": [],
        "patient_group_links": [],
        "visit_mark_tags": [],
        "visit_mark_links": []
    }

    cursor.execute("SELECT * FROM patient_profiles")
    for row in cursor.fetchall():
        data["patient_profiles"].append(dict(row))

    cursor.execute("SELECT * FROM visits")
    for row in cursor.fetchall():
        data["visits"].append(dict(row))

    cursor.execute("SELECT * FROM patient_group_tags")
    for row in cursor.fetchall():
        data["patient_group_tags"].append(dict(row))

    cursor.execute("SELECT * FROM patient_group_links")
    for row in cursor.fetchall():
        data["patient_group_links"].append(dict(row))

    cursor.execute("SELECT * FROM visit_mark_tags")
    for row in cursor.fetchall():
        data["visit_mark_tags"].append(dict(row))

    cursor.execute("SELECT * FROM visit_mark_links")
    for row in cursor.fetchall():
        data["visit_mark_links"].append(dict(row))

    conn.close()
    return json.dumps(data, ensure_ascii=False, indent=2)


def import_database(json_str, mode="overwrite", db_path=None):
    if db_path is None:
        db_path = get_db_path()
    data = json.loads(json_str)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        conn.execute("BEGIN TRANSACTION")

        if mode == "overwrite":
            # 清空所有表
            cursor.execute("DELETE FROM visit_mark_links")
            cursor.execute("DELETE FROM visit_mark_tags")
            cursor.execute("DELETE FROM patient_group_links")
            cursor.execute("DELETE FROM patient_group_tags")
            cursor.execute("DELETE FROM visits")
            cursor.execute("DELETE FROM patient_profiles")

            # 1. 插入 patient_profiles（主键是 patient_name，无需映射）
            for row in data["patient_profiles"]:
                cursor.execute(
                    """INSERT INTO patient_profiles 
                       (patient_name, gender, birth_date, phone, id_card, address, personal_remarks, first_visit_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["patient_name"], row.get("gender"), row.get("birth_date"), row.get("phone"),
                     row.get("id_card"), row.get("address"), row.get("personal_remarks"), row.get("first_visit_date"))
                )

            # 2. 处理分组标签映射
            group_tag_map = {}
            for row in data["patient_group_tags"]:
                cursor.execute("INSERT INTO patient_group_tags (tag_name) VALUES (?)", (row["tag_name"],))
                group_tag_map[row["id"]] = cursor.lastrowid

            # 3. 处理就诊标记标签映射
            mark_tag_map = {}
            for row in data["visit_mark_tags"]:
                cursor.execute("INSERT INTO visit_mark_tags (tag_name) VALUES (?)", (row["tag_name"],))
                mark_tag_map[row["id"]] = cursor.lastrowid

            # 4. 插入 visits，并建立 visit_id 映射
            visit_id_map = {}
            for row in data["visits"]:
                cursor.execute(
                    """INSERT INTO visits 
                       (patient_name, visit_date, hospital, docx_path, images_path, syndrome, prescription,
                        custom_tags, diagnosis, western_diagnosis, full_medical_text, visit_remarks)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["patient_name"], row["visit_date"], row.get("hospital"), row.get("docx_path"),
                     row.get("images_path"), row.get("syndrome"), row.get("prescription"), row.get("custom_tags"),
                     row.get("diagnosis"), row.get("western_diagnosis"), row.get("full_medical_text"),
                     row.get("visit_remarks"))
                )
                visit_id_map[row["id"]] = cursor.lastrowid

            # 5. 插入关联
            for row in data["patient_group_links"]:
                patient_name = row["patient_name"]
                orig_tag_id = row["tag_id"]
                new_tag_id = group_tag_map.get(orig_tag_id)
                if new_tag_id is not None:
                    cursor.execute(
                        "INSERT INTO patient_group_links (patient_name, tag_id) VALUES (?, ?)",
                        (patient_name, new_tag_id)
                    )

            for row in data["visit_mark_links"]:
                orig_visit_id = row["visit_id"]
                orig_tag_id = row["tag_id"]
                new_visit_id = visit_id_map.get(orig_visit_id)
                new_tag_id = mark_tag_map.get(orig_tag_id)
                if new_visit_id is not None and new_tag_id is not None:
                    cursor.execute(
                        "INSERT INTO visit_mark_links (visit_id, tag_id) VALUES (?, ?)",
                        (new_visit_id, new_tag_id)
                    )

        else:  # append 模式
            # ---------- 1. 插入或更新 patient_profiles（补空不覆盖） ----------
            for row in data["patient_profiles"]:
                patient_name = row["patient_name"]
                # 检查是否已存在
                cursor.execute("SELECT * FROM patient_profiles WHERE patient_name = ?", (patient_name,))
                existing = cursor.fetchone()
                if existing:
                    # 构建更新字段（只更新空字段）
                    update_fields = []
                    update_values = []
                    # 字段映射：数据库列名 -> JSON键名
                    field_map = {
                        'gender': 'gender',
                        'birth_date': 'birth_date',
                        'phone': 'phone',
                        'id_card': 'id_card',
                        'address': 'address',
                        'personal_remarks': 'personal_remarks',
                        'first_visit_date': 'first_visit_date'
                    }
                    # 将 existing 转为字典（便于按列名取值）
                    existing_dict = dict(zip([desc[0] for desc in cursor.description], existing))
                    for db_col, json_key in field_map.items():
                        current_val = existing_dict.get(db_col)
                        # 如果当前值为空（None 或空字符串），且导入数据有值，则更新
                        if (current_val is None or current_val == '') and row.get(json_key):
                            update_fields.append(f"{db_col} = ?")
                            update_values.append(row[json_key])
                    if update_fields:
                        update_values.append(patient_name)
                        query = f"UPDATE patient_profiles SET {', '.join(update_fields)} WHERE patient_name = ?"
                        cursor.execute(query, update_values)
                else:
                    # 不存在则插入
                    cursor.execute(
                        """INSERT INTO patient_profiles 
                           (patient_name, gender, birth_date, phone, id_card, address, personal_remarks, first_visit_date)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (patient_name, row.get("gender"), row.get("birth_date"), row.get("phone"),
                         row.get("id_card"), row.get("address"), row.get("personal_remarks"),
                         row.get("first_visit_date"))
                    )

            # ---------- 2. 处理标签映射 ----------
            # 2.1 分组标签映射 {原tag_id: 新tag_id}
            group_tag_map = {}
            for row in data["patient_group_tags"]:
                tag_name = row["tag_name"]
                # 查询是否存在
                cursor.execute("SELECT id FROM patient_group_tags WHERE tag_name = ?", (tag_name,))
                existing = cursor.fetchone()
                if existing:
                    group_tag_map[row["id"]] = existing[0]
                else:
                    # 插入新标签
                    cursor.execute("INSERT INTO patient_group_tags (tag_name) VALUES (?)", (tag_name,))
                    new_id = cursor.lastrowid
                    group_tag_map[row["id"]] = new_id

            # 2.2 就诊标记标签映射
            mark_tag_map = {}
            for row in data["visit_mark_tags"]:
                tag_name = row["tag_name"]
                cursor.execute("SELECT id FROM visit_mark_tags WHERE tag_name = ?", (tag_name,))
                existing = cursor.fetchone()
                if existing:
                    mark_tag_map[row["id"]] = existing[0]
                else:
                    cursor.execute("INSERT INTO visit_mark_tags (tag_name) VALUES (?)", (tag_name,))
                    new_id = cursor.lastrowid
                    mark_tag_map[row["id"]] = new_id

            # ---------- 3. 插入 visits（跳过已存在的） ----------
            # 记录新插入的 visit_id 映射（原visit_id -> 新visit_id）
            visit_id_map = {}
            for row in data["visits"]:
                # 检查是否已存在（基于唯一约束）
                cursor.execute(
                    "SELECT id FROM visits WHERE patient_name = ? AND visit_date = ? AND hospital = ?",
                    (row["patient_name"], row["visit_date"], row.get("hospital"))
                )
                existing = cursor.fetchone()
                if existing:
                    visit_id_map[row["id"]] = existing[0]   # 使用已有的id
                else:
                    # 插入新记录（不指定id，让数据库自动生成）
                    cursor.execute(
                        """INSERT INTO visits 
                           (patient_name, visit_date, hospital, docx_path, images_path, syndrome, prescription,
                            custom_tags, diagnosis, western_diagnosis, full_medical_text, visit_remarks)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (row["patient_name"], row["visit_date"], row.get("hospital"), row.get("docx_path"),
                         row.get("images_path"), row.get("syndrome"), row.get("prescription"), row.get("custom_tags"),
                         row.get("diagnosis"), row.get("western_diagnosis"), row.get("full_medical_text"),
                         row.get("visit_remarks"))
                    )
                    new_id = cursor.lastrowid
                    visit_id_map[row["id"]] = new_id

            # ---------- 4. 插入关联（使用映射后的ID） ----------
            # 4.1 patient_group_links
            for row in data["patient_group_links"]:
                patient_name = row["patient_name"]
                orig_tag_id = row["tag_id"]
                # 检查该患者是否已存在（若不存在，可能是本次导入的，但patient_name已存在则跳过）
                # 但我们需要确定 patient_name 是否已存在，如果存在才插入关联
                cursor.execute("SELECT 1 FROM patient_profiles WHERE patient_name = ?", (patient_name,))
                if cursor.fetchone():
                    new_tag_id = group_tag_map.get(orig_tag_id)
                    if new_tag_id is not None:
                        cursor.execute(
                            "INSERT OR IGNORE INTO patient_group_links (patient_name, tag_id) VALUES (?, ?)",
                            (patient_name, new_tag_id)
                        )

            # 4.2 visit_mark_links
            for row in data["visit_mark_links"]:
                orig_visit_id = row["visit_id"]
                orig_tag_id = row["tag_id"]
                new_visit_id = visit_id_map.get(orig_visit_id)
                new_tag_id = mark_tag_map.get(orig_tag_id)
                if new_visit_id is not None and new_tag_id is not None:
                    cursor.execute(
                        "INSERT OR IGNORE INTO visit_mark_links (visit_id, tag_id) VALUES (?, ?)",
                        (new_visit_id, new_tag_id)
                    )

        conn.commit()
        return True, "导入成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()