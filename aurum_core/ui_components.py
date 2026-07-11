# aurum_core/ui_components.py
import re
from aurum_core.database import get_all_patient_names, get_visit_dates_for_patient
import sqlite3
import os
import json
import streamlit as st
import pandas as pd

def patient_selector(key_prefix: str = "") -> tuple:
    """
    渲染患者姓名下拉框（支持手动输入）
    返回 (patient_name, 是否有效)
    """
    all_patients = get_all_patient_names()
    # 选项列表：占位 + 手动输入 + 所有患者
    options = ["-- 请选择患者 --", "✏️ 手动输入..."] + all_patients
    # 使用传入的前缀区分不同组件
    selected = st.selectbox("👤 选择或输入患者姓名", options, key=f"{key_prefix}_patient_select")

    if selected == "✏️ 手动输入...":
        patient_name = st.text_input("请输入患者姓名", placeholder="例如：张三", key=f"{key_prefix}_patient_manual")
    elif selected == "-- 请选择患者 --":
        patient_name = ""
    else:
        patient_name = selected

    return patient_name, bool(patient_name)


def visit_date_selector(patient_name: str, key_prefix: str = "") -> tuple:
    """
    渲染就诊日期下拉框
    返回 (selected_date, 是否有效)
    """
    if not patient_name:
        return None, False

    visit_dates = get_visit_dates_for_patient(patient_name)
    if not visit_dates:
        st.warning("⚠️ 该患者暂无就诊记录，请先运行归档和索引。")
        return None, False

    date_options = ["-- 请选择就诊日期 --"] + visit_dates
    selected = st.selectbox("📅 选择就诊日期", date_options, key=f"{key_prefix}_date_select")
    if selected == "-- 请选择就诊日期 --":
        return None, False
    return selected, True

# aurum_core/ui_components.py（追加）

def folder_opener(patient_name: str, visit_date: str, key_prefix: str = ""):
    """
    渲染“打开文件夹”按钮，点击后打开该就诊记录的文件夹。
    如果未选择有效患者和日期，按钮禁用。
    """
    disabled = not (patient_name and visit_date)
    if st.button("📂 打开文件夹", use_container_width=True, disabled=disabled, key=f"{key_prefix}_folder"):
        from aurum_core.database import get_docx_path
        import os
        docx_path = get_docx_path(patient_name, visit_date)
        if docx_path and os.path.exists(docx_path):
            folder_path = os.path.dirname(docx_path)
            try:
                os.startfile(folder_path)
                st.toast(f"已打开文件夹：{folder_path}", icon="📁", duration=5)
            except Exception as e:
                st.error(f"❌ 打开文件夹失败：{e}")
        else:
            st.error("❌ 找不到该就诊记录的文件路径")

def edit_record_ui(patient_name: str = None, visit_date: str = None):
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aurum_index.db")

    # ---- 如果未传入患者姓名，则让用户选择 ----
    if not patient_name:
        patient_name, valid_patient = patient_selector(key_prefix="edit")
        if not valid_patient:
            return
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT visit_date FROM visits WHERE patient_name = ? ORDER BY visit_date ASC",
            (patient_name,)
        )
        dates = [row[0] for row in cursor.fetchall()]
        conn.close()
        if not dates:
            st.warning("该患者暂无就诊记录，无法编辑就诊信息。")
            return
        visit_date = st.selectbox("📅 选择要编辑的就诊日期", dates, key="edit_visit_date_select")
    else:
        if not visit_date:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT visit_date FROM visits WHERE patient_name = ? ORDER BY visit_date ASC",
                (patient_name,)
            )
            dates = [row[0] for row in cursor.fetchall()]
            conn.close()
            if not dates:
                st.warning("该患者暂无就诊记录，无法编辑就诊信息。")
                return
            visit_date = st.selectbox("📅 选择要编辑的就诊日期", dates, key="edit_visit_date_select")

    if not patient_name or not visit_date:
        st.error("患者姓名或就诊日期无效，请重试。")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ---- 选择编辑模式 ----
    edit_type = st.radio(
        "选择编辑类型：",
        options=["个人信息", "就诊信息"],
        horizontal=True,
        key="edit_type_radio"
    )

    # ---- 辅助函数：更新档案 ----
    def update_archive(patient):
        try:
            from aurum_core.file_processor import update_patient_archive_by_db
            aggregate = st.session_state.get('aggregate_visits', False)
            update_patient_archive_by_db(patient, aggregate)
            return True, "档案文件已更新"
        except Exception as e:
            return False, f"更新档案失败：{e}"

    # =========================================================
    # 1. 编辑个人信息
    # =========================================================
    if edit_type == "个人信息":
        cursor.execute(
            "SELECT gender, birth_date, phone, id_card, address, personal_remarks "
            "FROM patient_profiles WHERE patient_name = ?",
            (patient_name,)
        )
        profile = cursor.fetchone()
        if not profile:
            current_gender = current_birth = current_phone = current_id_card = current_address = current_personal_remarks = ""
        else:
            current_gender, current_birth, current_phone, current_id_card, current_address, current_personal_remarks = profile

        with st.form(key="edit_personal_form"):
            st.markdown(f"**编辑 {patient_name} 的个人信息**")
            new_gender = st.text_input("性别", value=current_gender)
            new_birth = st.text_input("出生日期", value=current_birth)
            new_phone = st.text_input("电话", value=current_phone)
            new_id_card = st.text_input("身份证号", value=current_id_card)
            new_address = st.text_input("家庭住址", value=current_address)
            new_personal_remarks = st.text_area("个人信息备注", value=current_personal_remarks, height=80)
            col_btn1, col_btn2 = st.columns([3, 1])
            with col_btn2:
                submitted = st.form_submit_button("💾 更新个人信息", type="primary", use_container_width=True)

        if submitted:
            try:
                cursor.execute("SELECT 1 FROM patient_profiles WHERE patient_name = ?", (patient_name,))
                exists = cursor.fetchone()
                if exists:
                    cursor.execute(
                        """UPDATE patient_profiles 
                           SET gender = ?, birth_date = ?, phone = ?, id_card = ?, address = ?, personal_remarks = ?
                           WHERE patient_name = ?""",
                        (new_gender, new_birth, new_phone, new_id_card, new_address, new_personal_remarks, patient_name)
                    )
                else:
                    cursor.execute(
                        """INSERT INTO patient_profiles 
                           (patient_name, gender, birth_date, phone, id_card, address, personal_remarks)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (patient_name, new_gender, new_birth, new_phone, new_id_card, new_address, new_personal_remarks)
                    )
                conn.commit()
                success, msg = update_archive(patient_name)
                if success:
                    st.session_state.pending_toast = f"个人信息已更新，{msg}"
                else:
                    st.session_state.pending_warning = f"⚠️ 个人信息已更新，但{msg}"
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"❌ 更新失败：{e}")
            finally:
                conn.close()

    # =========================================================
    # 2. 编辑就诊信息（不含标记）
    # =========================================================
    else:
        cursor.execute(
            "SELECT id, diagnosis, prescription, visit_remarks FROM visits WHERE patient_name = ? AND visit_date = ?",
            (patient_name, visit_date)
        )
        row = cursor.fetchone()
        if not row:
            st.error("未找到该就诊记录")
            conn.close()
            return
        visit_id, current_diagnosis, current_prescription, current_visit_remarks = row

        def fmt(val):
            if not val:
                return ""
            try:
                lst = json.loads(val)
                if isinstance(lst, list):
                    return '、'.join(lst)
                return str(val)
            except:
                return str(val)

        display_diagnosis = fmt(current_diagnosis)
        display_prescription = fmt(current_prescription)

        with st.form(key="edit_visit_form"):
            st.markdown(f"**编辑 {patient_name} 于 {visit_date} 的就诊信息**")
            new_diagnosis = st.text_input("诊断（用顿号分隔）", value=display_diagnosis)
            new_prescription = st.text_input("方剂（用顿号分隔）", value=display_prescription)
            new_visit_remarks = st.text_area("就诊备注", value=current_visit_remarks, height=80)

            col_btn1, col_btn2 = st.columns([3, 1])
            with col_btn2:
                submitted = st.form_submit_button("💾 更新就诊信息", type="primary", use_container_width=True)

        if submitted:
            try:
                def to_json_list(text):
                    if not text.strip():
                        return json.dumps([], ensure_ascii=False)
                    items = [item.strip() for item in re.split(r'[、，,]', text) if item.strip()]
                    return json.dumps(items, ensure_ascii=False)

                new_diag_json = to_json_list(new_diagnosis)
                new_presc_json = to_json_list(new_prescription)

                cursor.execute(
                    "UPDATE visits SET diagnosis = ?, prescription = ?, visit_remarks = ? WHERE id = ?",
                    (new_diag_json, new_presc_json, new_visit_remarks, visit_id)
                )
                conn.commit()

                success, msg = update_archive(patient_name)
                if success:
                    st.session_state.pending_toast = f"就诊信息已更新，{msg}"
                else:
                    st.session_state.pending_warning = f"⚠️ 就诊信息已更新，但{msg}"

                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"❌ 更新失败：{e}")
            finally:
                conn.close()

def render_batch_tag_editor(target_df, db_path):
    target_count = len(target_df)
    if target_count == 0:
        st.caption("请先选中记录")
        return

    st.caption(f"已选中 {target_count} 条记录")

    batch_field = st.selectbox(
        "选择修改模式",
        ["🏷️患者分组", "📌就诊标记"],
        key="batch_field_selector"
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if batch_field == "🏷️患者分组":
        cursor.execute("SELECT tag_name FROM patient_group_tags ORDER BY tag_name")
        existing_tags = [row[0] for row in cursor.fetchall()]

        default_groups = []
        if target_count == 1:
            first_row = target_df.iloc[0]
            default_groups = first_row.get('患者分组列表', []) or []

        selected_keys = tuple(sorted(target_df['患者姓名'].tolist()))
        key_suffix = f"_{hash(str(selected_keys))}"

        new_tags = st.multiselect(
            "选择分组标签",
            options=existing_tags,
            default=default_groups,
            key=f"batch_group_tags{key_suffix}"
        )
        new_tag_input = st.text_input("或输入新标签（用顿号分隔）", placeholder="例如：消渴病队列、糖尿病")

        # 按钮右对齐
        col_btn_left, col_btn_right = st.columns([3, 1])
        with col_btn_right:
            if st.button("确认修改", type="primary", use_container_width=True):
                try:
                    all_tags = list(new_tags)
                    if new_tag_input.strip():
                        all_tags.extend([t.strip() for t in new_tag_input.split('、') if t.strip()])

                    patients_updated = set()
                    for idx, row in target_df.iterrows():
                        patient_name = row['患者姓名']
                        cursor.execute("INSERT OR IGNORE INTO patient_profiles (patient_name) VALUES (?)", (patient_name,))
                        cursor.execute("DELETE FROM patient_group_links WHERE patient_name = ?", (patient_name,))
                        for tag in all_tags:
                            if tag:
                                cursor.execute("INSERT OR IGNORE INTO patient_group_tags (tag_name) VALUES (?)", (tag,))
                                cursor.execute("SELECT id FROM patient_group_tags WHERE tag_name = ?", (tag,))
                                tag_id = cursor.fetchone()
                                if tag_id:
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO patient_group_links (patient_name, tag_id) VALUES (?, ?)",
                                        (patient_name, tag_id[0])
                                    )
                        patients_updated.add(patient_name)

                    from aurum_core.database import clean_orphan_tags
                    clean_orphan_tags(conn)
                    conn.commit()
                    st.session_state.pending_toast = f"已更新 {len(patients_updated)} 位患者的 {batch_field}"
                    st.session_state['select_all'] = False
                    st.session_state.pop('selected_all_df', None)
                    st.session_state.manual_selection = []
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ 更新失败：{e}")
                finally:
                    conn.close()

    else:  # 就诊标记
        cursor.execute("SELECT tag_name FROM visit_mark_tags ORDER BY tag_name")
        existing_tags = [row[0] for row in cursor.fetchall()]

        default_marks = []
        if target_count == 1:
            first_row = target_df.iloc[0]
            default_marks = first_row.get('就诊标记列表', []) or []

        selected_keys = tuple(sorted(target_df['患者姓名'].tolist()))
        key_suffix = f"_{hash(str(selected_keys))}"

        new_tags = st.multiselect(
            "选择标记标签",
            options=existing_tags,
            default=default_marks,
            key=f"batch_mark_tags{key_suffix}"
        )
        new_tag_input = st.text_input("或输入新标记（用顿号分隔）", placeholder="例如：胃肠镜拍摄、需要随访")

        col_btn_left, col_btn_right = st.columns([3, 1])
        with col_btn_right:
            if st.button("确认修改", type="primary", use_container_width=True):
                try:
                    all_tags = list(new_tags)
                    if new_tag_input.strip():
                        all_tags.extend([t.strip() for t in new_tag_input.split('、') if t.strip()])
                    all_tags = list(dict.fromkeys(all_tags))

                    records_updated = 0
                    for idx, row in target_df.iterrows():
                        visit_id = row.get('id')
                        if not visit_id:
                            patient_name = row['患者姓名']
                            visit_date = row['就诊日期']
                            cursor.execute(
                                "SELECT id FROM visits WHERE patient_name = ? AND visit_date = ?",
                                (patient_name, visit_date)
                            )
                            result = cursor.fetchone()
                            if not result:
                                continue
                            visit_id = result[0]

                        cursor.execute("DELETE FROM visit_mark_links WHERE visit_id = ?", (visit_id,))

                        for tag in all_tags:
                            if tag:
                                cursor.execute("INSERT OR IGNORE INTO visit_mark_tags (tag_name) VALUES (?)", (tag,))
                                cursor.execute("SELECT id FROM visit_mark_tags WHERE tag_name = ?", (tag,))
                                tag_id = cursor.fetchone()
                                if tag_id:
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO visit_mark_links (visit_id, tag_id) VALUES (?, ?)",
                                        (visit_id, tag_id[0])
                                    )
                        records_updated += 1

                    conn.commit()
                    from aurum_core.database import clean_orphan_tags
                    clean_orphan_tags(conn)
                    conn.commit()

                    st.session_state.pending_toast = f"已更新 {records_updated} 条就诊记录的 {batch_field}"
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ 更新失败：{e}")
                finally:
                    conn.close()