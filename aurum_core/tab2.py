# aurum_core/tab2.py
import streamlit as st
import os
import json
import glob
import sqlite3
from aurum_core.llm_tools import identify_prescription, identify_diagnosis, parse_llm_response
from aurum_core.ui_components import patient_selector, visit_date_selector, folder_opener
from aurum_core.text_utils import (
    extract_prescription_from_text,
    merge_patient_visits_text,
    render_sensitive_warning
)
from aurum_core.deidentifier import _sanitize_text
from aurum_core.database import (
    get_docx_path,
    get_patient_profile,
    get_all_visits_for_patient,
    get_all_patient_folders,
    check_existing_diagnosis
)
from aurum_core.utils import open_folder


def render_tab2():
    # ---- 初始化 API 密钥管理折叠状态 ----
    if 'key_expanded' not in st.session_state:
        st.session_state.key_expanded = not bool(st.session_state.get('api_key'))

    col_title, col_icon = st.columns([6, 1], vertical_alignment="bottom")
    with col_title:
        st.header("🤖 智能体功能")
    with col_icon:
        with st.popover("❗", use_container_width=True):
            st.markdown("""
            **⚠️ 数据隐私与法律责任声明**

            本功能涉及将病历文本发送至第三方大模型API（DeepSeek）。
            在使用前，请务必确认：
            - 你已获得患者本人的知情同意，并已对数据完成脱敏。
            - 上传未脱敏的敏感信息至第三方平台，相关法律责任由操作者自行承担。

            **建议流程：**
            - 使用 「自动脱敏导入」 按钮一键脱敏。
            - 检查并手动替换未被自动脱敏敏感信息，补充可能被误删的医学相关信息（如就诊日期、年龄）。
            - 确认内容已脱敏后，再点击 「识别诊断」。

            参考文献：[1]常凯,海佳丽,李金芳,等.基于自适应思维链与模型蒸馏的中医医案按语生成方法研究[J/OL].数据分析与知识发现,1-13[2026-06-28].https://link.cnki.net/urlid/10.1478.G2.20260511.1509.002.
            """)

    # ---- API 密钥管理 ----
    if 'key_expanded' not in st.session_state:
        st.session_state.key_expanded = False

    with st.expander("🔑 账号 API 密钥管理", expanded=st.session_state.key_expanded):
        st.markdown("""
        **使用前须知：**
        - 本网页接入 DeepSeek-V4-Pro 模型。
        - 本工具调用的大模型 API 为付费服务，由 DeepSeek 平台提供，本工具不收取任何额外费用。
        - 您需要自行前往 DeepSeek 平台 注册账号、获取 API 密钥并充值。
        - API密钥以明文存储在 `config.yaml` 中，请确保该文件的安全。
        """)
        st.page_link(
            "https://platform.deepseek.com/",
            label="🚀 前往 DeepSeek 平台注册 / 充值",
            icon="🔗",
            use_container_width=True
        )

        key_input = st.text_input(
            "输入你的 DeepSeek API Key",
            type="password",
            placeholder="sk-...",
            value=st.session_state.get('api_key', '')
        )
        col_key1, col_key2 = st.columns(2)
        with col_key1:
            if st.button("💾 保存账号密钥", use_container_width=True):
                if key_input.strip():
                    st.session_state.api_key = key_input.strip()
                    username = st.session_state['username']
                    with open('config.yaml', 'r', encoding='utf-8') as f:
                        import yaml
                        config = yaml.safe_load(f)
                    config['credentials']['usernames'][username]['api_key'] = key_input.strip()
                    with open('config.yaml', 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
                    st.session_state.key_expanded = False
                    st.rerun()
                else:
                    st.error("❌ 请输入有效的密钥")
        with col_key2:
            if st.button("🗑️ 清除账号密钥", use_container_width=True):
                st.session_state.api_key = None
                username = st.session_state['username']
                with open('config.yaml', 'r', encoding='utf-8') as f:
                    import yaml
                    config = yaml.safe_load(f)
                if 'api_key' in config['credentials']['usernames'][username]:
                    del config['credentials']['usernames'][username]['api_key']
                with open('config.yaml', 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
                st.session_state.key_expanded = True
                st.rerun()

    # ---- 诊断识别 ----
    st.divider()
    st.subheader("🩺 诊断识别")
    st.caption("选择患者和就诊日期，输入或导入脱敏后的病历内容，智能体将给出中医诊断证型。")
    st.warning("⚠️ 发送前请确保内容已脱敏！！")

    patient_name_input_diag, valid_patient_diag = patient_selector(key_prefix="diag")
    selected_visit_date_diag, valid_date_diag = visit_date_selector(patient_name_input_diag, key_prefix="diag")

    if 'last_diag_patient' not in st.session_state:
        st.session_state.last_diag_patient = patient_name_input_diag
        st.session_state.last_diag_date = selected_visit_date_diag

    if (patient_name_input_diag != st.session_state.last_diag_patient or
            selected_visit_date_diag != st.session_state.last_diag_date):
        # 清除输入框内容
        st.session_state.diag_input = ""
        # 清除识别结果和推理过程
        st.session_state.pop('diagnosis_result', None)
        # 重置强制识别状态
        st.session_state.force_diagnosis = False
        # 清除脱敏导入标记
        st.session_state.pop('auto_desensitized', None)
        # 更新 last 记录
        st.session_state.last_diag_patient = patient_name_input_diag
        st.session_state.last_diag_date = selected_visit_date_diag

    # ---- 诊断模式选择（类似按语风格） ----
    col_mode_label, col_mode_radio = st.columns([1, 1], vertical_alignment="bottom")
    with col_mode_label:
        st.write("诊断模式")
    with col_mode_radio:
        diag_mode = st.radio(
            "",
            ["中医诊断", "西医诊断"],
            index=0,
            horizontal=True,
            key="diag_mode",
            label_visibility="collapsed"
        )

    col_diag_text, col_diag_buttons = st.columns([4, 1])
    with col_diag_text:
        diag_text = st.text_area(
            "📄 输入脱敏后的病历内容",
            value=st.session_state.get('diag_input', ''),
            placeholder="点击右侧「📥 自动脱敏导入」按钮，或手动粘贴病历内容并脱敏。",
            height=200
        )
        st.session_state['diag_input'] = diag_text
    with col_diag_buttons:
        st.write("")
        st.write("")
        auto_disabled = not (valid_patient_diag and valid_date_diag)
        if st.button("📥 自动脱敏导入", use_container_width=True, disabled=auto_disabled, key="diag_auto"):
            import traceback
            docx_path = get_docx_path(patient_name_input_diag, selected_visit_date_diag)
            if docx_path and os.path.exists(docx_path):
                try:
                    from aurum_core.deidentifier import extract_safe_content
                    profile = get_patient_profile(patient_name_input_diag)
                    real_name = profile['real_name']
                    safe_text = extract_safe_content(docx_path, real_name, visit_date=selected_visit_date_diag)
                    if safe_text:
                        st.session_state['diag_input'] = safe_text
                        st.session_state['auto_desensitized'] = True
                        st.rerun()
                    else:
                        st.error("❌ 脱敏后返回空内容，请检查文件。")
                except Exception as e:
                    error_msg = f"❌ 自动脱敏失败：{e}\n{traceback.format_exc()}"
                    st.error(error_msg)
                    print(error_msg)
            else:
                st.error("❌ 找不到该就诊记录的原始文件")

        folder_opener(patient_name_input_diag, selected_visit_date_diag, key_prefix="diag")

    # ---- 识别结果框 ----
    if 'diagnosis_result' in st.session_state:
        reasoning, conclusion = parse_llm_response(st.session_state['diagnosis_result'])

        # 显示最终结论
        st.success("✅ 诊断结果：")
        st.code(conclusion, language="text")

        # 显示推理过程（折叠）
        if reasoning:
            with st.expander("📋 查看推理过程", expanded=False):
                st.markdown(reasoning)
        else:
            # 如果LLM没有返回推理过程，显示原结果（兼容旧版）
            st.code(st.session_state['diagnosis_result'], language="text")

    # ---- 敏感信息检测（独立成行） ----
    if not render_sensitive_warning(
            st.session_state.get('diag_input', ''),
            patient_name_input_diag,
            'skip_sensitive_check',
            'force_sensitive_btn'
    ):
        pass

    # ---- 检查是否已有诊断（独立成行） ----
    if 'force_diagnosis' not in st.session_state:
        st.session_state.force_diagnosis = False

    has_diag, has_presc, diag_display, presc_display = check_existing_diagnosis(
        patient_name_input_diag, selected_visit_date_diag
    )
    if has_diag and not st.session_state.force_diagnosis:
        col_warn, col_btn = st.columns([4, 1.5])
        with col_warn:
            st.warning(f"⚠️ 该就诊记录已存在诊断：{diag_display}")
        with col_btn:
            if st.button("🔄 仍要重新识别", key="force_diagnosis_btn", use_container_width=True):
                st.session_state.force_diagnosis = True
                st.rerun()
        st.stop()
    else:
        st.session_state.force_diagnosis = False

    # ---- 识别按钮和保存按钮 ----
    col_diag_btn1, col_diag_btn2 = st.columns(2)
    with col_diag_btn1:
        if st.button("🔍 识别诊断", use_container_width=True, key="diag_identify"):
            current_text = st.session_state.get('diag_input', '')
            if not st.session_state.get('api_key'):
                st.error("❌ 请先保存 API 密钥")
            elif not current_text.strip():
                st.error("❌ 请输入病历内容")
            elif not valid_patient_diag or not valid_date_diag:
                st.error("❌ 请选择有效的患者和就诊日期")
            else:
                # ---- 检查是否已有诊断（已在外部检测，这里不再重复） ----
                # ---- 敏感信息检测已在外部完成 ----
                with st.spinner("⏳ 正在识别诊断..."):
                    result = identify_diagnosis(
                        current_text,
                        api_key=st.session_state.api_key,
                        model="deepseek-v4-pro"
                    )
                    st.session_state['diagnosis_result'] = result
                    st.session_state['diag_patient'] = patient_name_input_diag
                    st.session_state['diag_date'] = selected_visit_date_diag
                    st.session_state.force_diagnosis = False
                    st.rerun()

    with col_diag_btn2:
        if 'diagnosis_result' in st.session_state and st.session_state.diagnosis_result:
            save_disabled = not (valid_patient_diag and valid_date_diag)
            if st.button("💾 保存诊断到数据库", use_container_width=True, disabled=save_disabled):
                try:
                    from aurum_core.llm_tools import parse_llm_response
                    import re

                    patient_to_save = st.session_state['diag_patient']
                    date_to_save = st.session_state['diag_date']

                    # ---- 提取结论 ----
                    _, conclusion = parse_llm_response(st.session_state['diagnosis_result'])
                    if not conclusion:
                        conclusion = st.session_state['diagnosis_result']

                    # ---- 将结论拆分成独立的标签 ----
                    # 支持分隔符：中文顿号、中文逗号、英文逗号、中文分号、英文分号、空格
                    items = re.split(r'[，,、；;]\s*', conclusion)
                    items = [item.strip() for item in items if item.strip()]

                    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aurum_index.db")
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()

                    # ---- 读取已有诊断 ----
                    cursor.execute(
                        "SELECT diagnosis FROM visits WHERE patient_name = ? AND visit_date = ?",
                        (patient_to_save, date_to_save)
                    )
                    row = cursor.fetchone()
                    existing = []
                    if row and row[0]:
                        try:
                            existing = json.loads(row[0])
                            if not isinstance(existing, list):
                                existing = []
                        except:
                            existing = []

                    # ---- 逐个添加独立标签（去重） ----
                    for item in items:
                        if item and item not in existing:
                            existing.append(item)

                    updated = json.dumps(existing, ensure_ascii=False)
                    cursor.execute(
                        "UPDATE visits SET diagnosis = ? WHERE patient_name = ? AND visit_date = ?",
                        (updated, patient_to_save, date_to_save)
                    )
                    conn.commit()
                    conn.close()

                    st.toast(f"✅ 诊断已保存", icon="💾", duration=5)
                    del st.session_state['diagnosis_result']
                except Exception as e:
                    st.error(f"❌ 保存失败: {e}")
        else:
            st.button("💾 保存诊断到数据库", use_container_width=True, disabled=True)

    # ---- 方剂识别 ----
    st.divider()
    st.subheader("🧪 方剂识别")
    st.caption("选择患者和就诊日期，输入药方内容，智能体将识别方剂名。")
    st.warning("⚠️ 发送前请确保内容已脱敏！！")

    patient_name_input, valid_patient = patient_selector(key_prefix="prescription")
    selected_visit_date, valid_date = visit_date_selector(patient_name_input, key_prefix="prescription")

    if 'last_prescription_patient' not in st.session_state:
        st.session_state.last_prescription_patient = patient_name_input
        st.session_state.last_prescription_date = selected_visit_date

    if (patient_name_input != st.session_state.last_prescription_patient or
            selected_visit_date != st.session_state.last_prescription_date):
        # 清除输入框内容
        st.session_state.prescription_input = ""
        # 清除识别结果和推理过程
        st.session_state.pop('prescription_result', None)
        # 重置强制识别状态
        st.session_state.force_prescription = False
        # 更新 last 记录
        st.session_state.last_prescription_patient = patient_name_input
        st.session_state.last_prescription_date = selected_visit_date

    col_prescription, col_buttons = st.columns([4, 1])
    with col_prescription:
        prescription_text = st.text_area(
            "📄 输入药方内容",
            placeholder="点击右侧「📥 自动脱敏导入」按钮，或手动粘贴处方内容。",
            height=150,
            value=st.session_state.get('prescription_input', '')
        )
        st.session_state['prescription_input'] = prescription_text

    with col_buttons:
        st.write("")
        st.write("")
        auto_extract_disabled = not (valid_patient and valid_date)
        if st.button("📥 自动脱敏导入", use_container_width=True, disabled=auto_extract_disabled,
                     key="auto_prescription"):
            docx_path = get_docx_path(patient_name_input, selected_visit_date)
            if docx_path and os.path.exists(docx_path):
                try:
                    from aurum_core.text_utils import read_file_content
                    text = read_file_content(docx_path)
                    if text:
                        extracted = extract_prescription_from_text(text)
                        if extracted:
                            st.session_state['prescription_input'] = extracted
                            st.rerun()
                        else:
                            st.warning("⚠️ 未找到方剂内容，请手动输入。")
                    else:
                        st.error("❌ 无法读取病历文件，请检查文件是否存在。")
                except Exception as e:
                    st.error(f"❌ 自动提取失败：{e}")
            else:
                st.error("❌ 找不到该就诊记录的原始文件。")

        folder_opener(patient_name_input, selected_visit_date, key_prefix="prescription")

    # ---- 方剂识别结果框 ----
    if 'prescription_result' in st.session_state:
        result_text = st.session_state['prescription_result']

        # 尝试解析方名和方解
        import re
        name_match = re.search(r'【方剂名称】\s*(.+?)(?=\n|$)', result_text)
        jie_match = re.search(r'【方解】\s*([\s\S]*)', result_text)

        if name_match:
            prescription_name = name_match.group(1).strip()
            st.success("✅ 方剂名称：")
            st.code(prescription_name, language="text")

            # 如果有方解，用折叠框展示
            if jie_match:
                jie_text = jie_match.group(1).strip()
                with st.expander("📖 查看方解", expanded=False):
                    st.markdown(jie_text)
            # 如果没有方解，但结果中有其他内容（如旧格式），直接显示全文
        else:
            # 兼容旧格式或未按新格式输出的情况
            st.success("✅ 识别结果：")
            st.code(result_text, language="text")

    # ---- 检测是否已有方剂（独立成行） ----
    has_diag, has_presc, diag_display, presc_display = check_existing_diagnosis(
        patient_name_input, selected_visit_date
    )
    if has_presc and not st.session_state.get('force_prescription', False):
        col_warn, col_btn = st.columns([4, 1.5])
        with col_warn:
            st.warning(f"⚠️ 该就诊记录已存在方剂：{presc_display}")
        with col_btn:
            if st.button("🔄 仍要重新识别", key="force_prescription_btn", use_container_width=True):
                st.session_state.force_prescription = True
                st.rerun()
        st.stop()
    else:
        st.session_state.force_prescription = False

    # ---- 识别按钮和保存按钮 ----
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔍 识别方剂", use_container_width=True):
            if not st.session_state.get('api_key'):
                st.error("❌ 请先保存 API 密钥")
            elif not prescription_text.strip():
                st.error("❌ 请输入药方内容")
            elif not valid_patient or not valid_date:
                st.error("❌ 请选择有效的患者和就诊日期")
            else:
                with st.spinner("⏳ 正在识别方剂..."):
                    result = identify_prescription(
                        prescription_text,
                        api_key=st.session_state.api_key,
                        model="deepseek-v4-pro"
                    )
                    st.session_state['prescription_result'] = result
                    st.session_state.force_prescription = False
                    st.rerun()

    with col_btn2:
        if 'prescription_result' in st.session_state and st.session_state.prescription_result:
            save_disabled = not (valid_patient and valid_date)
            if st.button("💾 保存方剂到数据库", use_container_width=True, disabled=save_disabled):
                try:
                    name_match = re.search(r'【方剂名称】\s*(.+?)(?=\n|$)', st.session_state['prescription_result'])
                    if name_match:
                        conclusion = name_match.group(1).strip()
                    else:
                        # 如果无法解析，使用全文作为后备
                        conclusion = st.session_state['prescription_result']

                    # ---- 将结论拆分成独立的标签（方剂可能多个，用顿号分隔） ----
                    items = re.split(r'[，,、；;]\s*', conclusion)
                    items = [item.strip() for item in items if item.strip()]

                    # ---- 读取已有方剂 ----
                    cursor.execute(
                        "SELECT prescription FROM visits WHERE patient_name = ? AND visit_date = ?",
                        (patient_name_input, selected_visit_date)
                    )
                    row = cursor.fetchone()
                    existing = []
                    if row and row[0]:
                        try:
                            existing = json.loads(row[0])
                            if not isinstance(existing, list):
                                existing = []
                        except:
                            existing = []

                    # ---- 逐个添加独立标签（去重） ----
                    for item in items:
                        if item and item not in existing:
                            existing.append(item)

                    updated = json.dumps(existing, ensure_ascii=False)
                    cursor.execute(
                        "UPDATE visits SET prescription = ? WHERE patient_name = ? AND visit_date = ?",
                        (updated, patient_name_input, selected_visit_date)
                    )
                    conn.commit()
                    conn.close()

                    st.toast(f"✅ 方剂已保存", icon="💾", duration=5)
                    del st.session_state['prescription_result']
                except Exception as e:
                    st.error(f"❌ 保存失败: {e}")
        else:
            st.button("💾 保存方剂到数据库", use_container_width=True, disabled=True)

    # ---- 生成按语 ----
    st.divider()
    st.subheader("📝 生成按语")
    st.caption("选择患者，输入或导入该患者全部病历内容，智能体将生成按语。")
    st.warning("⚠️ 发送前请确保内容已脱敏！！")

    # ---- 风格选择 ----
    col_style_label, col_style_radio = st.columns([1, 1], vertical_alignment="bottom")
    with col_style_label:
        st.write("按语风格")
    with col_style_radio:
        style_option = st.radio(
            "",
            ["学生版", "专家版"],
            index=0,
            horizontal=True,
            key="commentary_style",
            label_visibility="collapsed"
        )
    style_map = {"学生版": "student", "专家版": "expert"}

    patient_name_input_comm, valid_patient_comm = patient_selector(key_prefix="commentary")

    if 'last_comm_patient' not in st.session_state:
        st.session_state.last_comm_patient = patient_name_input_comm

    if patient_name_input_comm != st.session_state.last_comm_patient:
        # 清除输入框内容
        st.session_state.comm_input = ""
        # 清除按语结果
        st.session_state.pop('commentary_result', None)
        # 重置强制覆盖状态
        st.session_state.force_overwrite_commentary = False
        # 清除脱敏导入标记
        st.session_state.pop('auto_comm_desensitized', None)
        # 更新 last 记录
        st.session_state.last_comm_patient = patient_name_input_comm

    col_comm_text, col_comm_buttons = st.columns([4, 1])
    with col_comm_text:
        comm_text = st.text_area(
            "📄 合并后的病历内容",
            value=st.session_state.get('comm_input', ''),
            placeholder="点击右侧「📥 自动脱敏导入」按钮，或手动粘贴病历内容并脱敏。",
            height=250
        )
        st.session_state['comm_input'] = comm_text

    with col_comm_buttons:
        st.write("")
        st.write("")
        auto_comm_disabled = not valid_patient_comm
        if st.button("📥 自动脱敏导入", use_container_width=True, disabled=auto_comm_disabled,
                     key="auto_comm"):
            try:
                visits = get_all_visits_for_patient(patient_name_input_comm)
                if visits:
                    combined = merge_patient_visits_text(visits)
                    profile = get_patient_profile(patient_name_input_comm)
                    safe_combined = _sanitize_text(
                        combined,
                        real_name=profile['real_name'],
                        id_card=profile['id_card'],
                        phone=profile['phone']
                    )
                    st.session_state['comm_input'] = safe_combined
                    st.session_state['auto_comm_desensitized'] = True
                    st.rerun()
                else:
                    st.warning("⚠️ 该患者暂无就诊记录，请先归档。")
            except Exception as e:
                st.error(f"❌ 自动导入失败：{e}")

        if valid_patient_comm:
            if st.button("📂 打开文件夹", use_container_width=True, key="open_patient_folder_comm"):
                folders = get_all_patient_folders(patient_name_input_comm)
                if folders:
                    opened = 0
                    failed = 0
                    for folder in folders:
                        try:
                            open_folder(folder)
                            opened += 1
                        except Exception as e:
                            failed += 1
                    if failed == 0:
                        st.toast(f"✅ 已打开 {opened} 个文件夹", icon="📁", duration=5)
                    else:
                        st.warning(f"⚠️ 成功打开 {opened} 个，{failed} 个失败，请检查文件夹是否存在")
                else:
                    st.error("❌ 未找到该患者的文件夹，请先归档。")
        else:
            st.button("📂 打开文件夹", use_container_width=True, disabled=True,
                      key="open_patient_folder_comm_disabled")

    # ---- 按语结果框 ----
    if 'commentary_result' in st.session_state:
        st.success("✅ 按语生成结果：")
        st.markdown(st.session_state['commentary_result'])

    # ================================================================
    # ---- 生成前检测（独立成行，在生成按钮之前） ----
    # ================================================================

    # ---- 1. 敏感信息检测 ----
    if not render_sensitive_warning(
            st.session_state.get('comm_input', ''),
            patient_name_input_comm,
            'skip_sensitive_check_comm',
            'force_sensitive_comm_btn'
    ):
        pass

    # ---- 2. 检测是否已有按语文件 ----
    folders = get_all_patient_folders(patient_name_input_comm)
    existing_commentary_files = []
    for folder in folders:
        pattern = os.path.join(folder, f"按语_{patient_name_input_comm}_*.txt")
        existing_commentary_files.extend(glob.glob(pattern))

    if existing_commentary_files and not st.session_state.get('force_overwrite_commentary', False):
        col_warn, col_btn = st.columns([4, 1.5])
        with col_warn:
            st.warning(
                f"⚠️ 该患者已有 {len(existing_commentary_files)} 个按语文件（{os.path.basename(existing_commentary_files[0])}）"
            )
        with col_btn:
            if st.button("🔄 仍要重新生成", key="force_overwrite_comm_btn", use_container_width=True):
                st.session_state.force_overwrite_commentary = True
                st.rerun()
        st.stop()
    else:
        st.session_state.force_overwrite_commentary = False

    # ================================================================
    # ---- 生成按钮和保存到患者文件夹按钮 ----
    # ================================================================
    col_comm_btn1, col_comm_btn2 = st.columns(2)
    with col_comm_btn1:
        if st.button("🔍 生成按语", use_container_width=True):
            if not st.session_state.get('api_key'):
                st.error("❌ 请先保存 API 密钥")
            elif not valid_patient_comm:
                st.error("❌ 请选择有效的患者")
            elif not st.session_state.get('comm_input', '').strip():
                st.error("❌ 请先导入或输入合并后的病历内容")
            else:
                with st.status("⏳ 正在准备请求...", expanded=True) as status:
                    status.update(label="📤 已发送请求至大模型，正在生成按语...")
                    from aurum_core.llm_tools import generate_commentary
                    try:
                        result = generate_commentary(
                            st.session_state['comm_input'],
                            api_key=st.session_state.api_key,
                            model="deepseek-v4-pro",
                            timeout=120,
                            style=style_map[style_option]
                        )
                        if result:
                            status.update(label="✅ 按语生成完成！", state="complete")
                            st.session_state['commentary_result'] = result
                            st.session_state.force_overwrite_commentary = False
                            st.rerun()
                        else:
                            status.update(label="❌ 生成失败，请重试", state="error")
                            st.error("大模型返回空结果，请检查API密钥或网络。")
                    except Exception as e:
                        status.update(label="❌ 请求异常", state="error")
                        st.error(f"生成按语失败：{e}")

    with col_comm_btn2:
        if 'commentary_result' in st.session_state and valid_patient_comm:
            if st.button("💾 保存到患者文件夹", use_container_width=True):
                folders = get_all_patient_folders(patient_name_input_comm)
                if folders:
                    from datetime import datetime
                    file_name = f"按语_{patient_name_input_comm}_{datetime.now().strftime('%Y%m%d')}.txt"
                    success_count = 0
                    for folder in folders:
                        file_path = os.path.join(folder, file_name)
                        try:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(st.session_state['commentary_result'])
                            success_count += 1
                        except Exception as e:
                            st.warning(f"⚠️ 保存至 {folder} 失败：{e}")
                    if success_count == len(folders):
                        st.toast(f"按语已保存至所有 {len(folders)} 个医院文件夹中！", icon="✅", duration=5)
                    else:
                        st.info(f"⚠️ 按语已保存至 {success_count}/{len(folders)} 个文件夹，请检查警告信息。")
                else:
                    st.error("❌ 未找到该患者的文件夹，请先归档。")
        else:
            st.button("💾 保存到患者文件夹", disabled=True, use_container_width=True)