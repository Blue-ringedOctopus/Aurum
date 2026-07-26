import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from aurum_core.ui_components import edit_record_ui, render_batch_tag_editor
from aurum_core.delete_handler import delete_records_clean
from aurum_core.database import load_all_visits_with_tags
from aurum_core.utils import open_folder

def render_tab3():
    import sqlite3
    # ---- 显示挂起的消息（跨 rerun 持久） ----
    if 'pending_toast' in st.session_state and st.session_state.pending_toast:
        st.toast(st.session_state.pending_toast, icon="✅", duration=5)
        del st.session_state.pending_toast
    if 'pending_warning' in st.session_state and st.session_state.pending_warning:
        st.warning(st.session_state.pending_warning)
        del st.session_state.pending_warning
    if 'pending_error' in st.session_state and st.session_state.pending_error:
        st.error(st.session_state.pending_error)
        del st.session_state.pending_error

    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aurum_index.db")

    if 'manual_selection' not in st.session_state:
        st.session_state.manual_selection = []

    # ---- 标题行 ----
    col_title, col_icon = st.columns([6, 1], vertical_alignment="bottom")
    with col_title:
        st.header("📊 数据库浏览")
    with col_icon:
        with st.popover("❓", use_container_width=True):
            st.markdown("""
            **📋 字段说明**
            - **出生日期**：若病历中未直接提供，系统会根据「年龄 与 就诊日期」反推，仅精确到年份（显示为 `xxxx-01-01`）。
            - **性别、电话、身份证号**：从初诊病历中自动提取，未识别到则显示为空。

            **🏷️ 分组与标记筛选**：
            - 可同时选择多个分组和标记，筛选模式可选“交集”或“并集”。
            - 分组作用于患者整体，标记仅作用于单次就诊。

            **✅ 关于全选与跨页选择**
            - 由于技术限制，表格的勾选框仅在当前页有效，翻页后自动取消。
            - 如需选择全部数据，请点击「✅ 全选」
            - 如需跨页选择多条记录，请在每页勾选后点击 「➕ 保留选择」，将当前页的勾选记录加入跨页保留列表。
            - 您可以通过页面下方的 「📌 已选 X 条记录」 按钮随时查看已保留的记录。

            **💡 使用提示与数据刷新**
            - 所有修改请通过本网页界面完成，直接修改本地文件不会同步到数据库。
            - 如需刷新本地修改的内容：选中记录 → 删除 → 重新运行归档整理。
            """)
    st.caption("所有就诊记录及档案信息。支持多选、批量编辑、分组筛选与搜索。")

    # ---- 加载数据 ----
    df = load_all_visits_with_tags(db_path)
    if df.empty:
        st.info("📭 数据库为空，请先运行归档和索引。")
        return

    df = df.fillna('')

    def parse_json_list(val):
        if not val:
            return ""
        try:
            lst = json.loads(val)
            if isinstance(lst, list):
                return '、'.join(lst)
            return str(val)
        except:
            return str(val)

    df['中医诊断'] = df['中医诊断'].apply(parse_json_list)
    df['西医诊断'] = df['西医诊断'].apply(parse_json_list)
    df['方剂'] = df['方剂'].apply(parse_json_list)

    # ---- 准备所有标签选项 ----
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT tag_name FROM patient_group_tags WHERE tag_name != '' ORDER BY tag_name")
    all_groups = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT tag_name FROM visit_mark_tags WHERE tag_name != '' ORDER BY tag_name")
    all_marks = [row[0] for row in cursor.fetchall()]
    conn.close()

    tagged_options = [f"🏷️ {g}" for g in all_groups] + [f"📌 {m}" for m in all_marks]

    # ---- 从 session_state 读取筛选值 ----
    selected_tagged = st.session_state.get('filter_tagged', [])
    search_term = st.session_state.get('search_input', "")
    filter_mode = st.session_state.get('filter_mode', "交集")

    # ---- 强制恢复筛选条件（全选状态丢失时） ----
    if st.session_state.get('select_all', False) and '_saved_filter' in st.session_state:
        saved = st.session_state['_saved_filter']
        if not selected_tagged and saved.get('filter_tagged'):
            st.session_state.filter_tagged = saved['filter_tagged']
            st.session_state.search_input = saved.get('search_input', '')
            st.session_state.filter_mode = saved.get('filter_mode', '交集')
            st.rerun()

    # ---- 解析选中的标签 ----
    selected_groups = []
    selected_marks = []
    for item in selected_tagged:
        if item.startswith("🏷️ ") and item in tagged_options:
            selected_groups.append(item[2:].strip())
        elif item.startswith("📌 ") and item in tagged_options:
            selected_marks.append(item[2:].strip())

    # ---- 强制确保标记列为列表类型 ----
    df['就诊标记列表'] = df['就诊标记列表'].apply(lambda x: x if isinstance(x, list) else [])

    # ---- 筛选逻辑 ----
    has_selection = bool(selected_groups) or bool(selected_marks)

    if has_selection:
        if filter_mode == "交集":
            mask = pd.Series([True] * len(df))
            if selected_groups:
                mask &= df['患者分组列表'].apply(
                    lambda tags: all(g in tags for g in selected_groups) if isinstance(tags, list) else False
                )
            if selected_marks:
                mask &= df['就诊标记列表'].apply(
                    lambda tags: all(m in tags for m in selected_marks) if isinstance(tags, list) else False
                )
        elif filter_mode == "并集":
            mask = pd.Series([False] * len(df))
            if selected_groups:
                mask |= df['患者分组列表'].apply(
                    lambda tags: any(g in tags for g in selected_groups) if isinstance(tags, list) else False
                )
            if selected_marks:
                mask |= df['就诊标记列表'].apply(
                    lambda tags: any(m in tags for m in selected_marks) if isinstance(tags, list) else False
                )
        elif filter_mode == "交集补":
            temp_mask = pd.Series([True] * len(df))
            if selected_groups:
                temp_mask &= df['患者分组列表'].apply(
                    lambda tags: all(g in tags for g in selected_groups) if isinstance(tags, list) else False
                )
            if selected_marks:
                temp_mask &= df['就诊标记列表'].apply(
                    lambda tags: all(m in tags for m in selected_marks) if isinstance(tags, list) else False
                )
            mask = ~temp_mask
        elif filter_mode == "并集补":
            temp_mask = pd.Series([False] * len(df))
            if selected_groups:
                temp_mask |= df['患者分组列表'].apply(
                    lambda tags: any(g in tags for g in selected_groups) if isinstance(tags, list) else False
                )
            if selected_marks:
                temp_mask |= df['就诊标记列表'].apply(
                    lambda tags: any(m in tags for m in selected_marks) if isinstance(tags, list) else False
                )
            mask = ~temp_mask
        else:
            mask = pd.Series([True] * len(df))
        filtered_df = df[mask]
    else:
        filtered_df = df.copy()

    # 搜索
    if search_term:
        search_mask = filtered_df.apply(
            lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1
        )
        filtered_df = filtered_df[search_mask]

    display_df = filtered_df

    # ---- 按拼音排序并重置索引 ----
    if not display_df.empty:
        from pypinyin import pinyin, Style
        def get_pinyin(name):
            return ''.join([p[0] for p in pinyin(name, style=Style.NORMAL)])
        display_df['_pinyin'] = display_df['患者姓名'].apply(get_pinyin)
        display_df = display_df.sort_values('_pinyin').drop('_pinyin', axis=1).reset_index(drop=True)

    # ---- 顶部控制行 ----
    col_all, col_mode, col_tags, col_search = st.columns([1, 1, 2, 2])

    with col_all:
        if st.session_state.get('select_all', False):
            if st.button("❌ 取消全选", use_container_width=True, key="deselect_all_top"):
                # 保存当前的筛选条件，防止 rerun 后被重置
                saved_filter = st.session_state.get('filter_tagged', [])
                st.session_state['select_all'] = False
                st.session_state.pop('selected_all_df', None)
                st.session_state.pop('_saved_filter', None)
                # 显式恢复筛选条件
                st.session_state['filter_tagged'] = saved_filter
                st.rerun()
        else:
            if st.button("✅ 全选", use_container_width=True, key="select_all_top"):
                # 保存当前筛选条件
                st.session_state['_saved_filter'] = {
                    'filter_tagged': selected_tagged,
                    'search_input': search_term,
                    'filter_mode': filter_mode
                }
                st.session_state['select_all'] = True
                st.session_state['selected_all_df'] = display_df.copy()
                st.rerun()

    with col_mode:
        st.selectbox(
            "筛选方式",
            ["交集", "并集", "交集补", "并集补"],
            index=["交集", "并集", "交集补", "并集补"].index(filter_mode),
            key="filter_mode",
            label_visibility="collapsed"
        )

    with col_tags:
        st.multiselect(
            "筛选标签",
            options=tagged_options,
            key="filter_tagged",
            placeholder="选择分组/标记",
            label_visibility="collapsed"
        )

    with col_search:
        st.text_input(
            "搜索",
            placeholder="搜索：心脾两虚、归脾汤",
            key="search_input",
            value=search_term,
            label_visibility="collapsed"
        )

    # ---- 分页 ----
    page_size = st.session_state.get("page_size_control", 20)
    current_page = st.session_state.get("table_pagination", 1)
    total_pages = max(1, (len(display_df) - 1) // page_size + 1) if len(display_df) > 0 else 1
    if current_page > total_pages:
        current_page = 1
        st.session_state.table_pagination = 1

    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, len(display_df)) if len(display_df) > 0 else 0
    page_df = display_df.iloc[start_idx:end_idx] if len(display_df) > 0 else pd.DataFrame(columns=display_df.columns)

    # ---- 显示状态 ----
    filter_info = []
    if selected_groups:
        filter_info.append(f"分组: {'+'.join(selected_groups)}")
    if selected_marks:
        filter_info.append(f"标记: {'+'.join(selected_marks)}")
    filter_str = " | ".join(filter_info) if filter_info else "全部"
    base_info = f"共 {len(display_df)} 条 | 筛选: {filter_str} | 搜索: {search_term if search_term else '无'} | 第 {start_idx + 1}–{end_idx} 条"
    if st.session_state.get('select_all', False):
        total_selected = len(st.session_state.get('selected_all_df', pd.DataFrame()))
        base_info += f" | ✅ 已全选当前结果（{total_selected} 条）"
    st.caption(base_info)

    # ---- 格式化标签 ----
    def format_tags(tag_list):
        if not tag_list or not isinstance(tag_list, list):
            return ""
        return '、'.join(tag_list)

    display_page_df = page_df.copy().fillna('')
    display_cols_with_tags = [
        '患者姓名', '性别', '出生日期', '电话', '身份证号', '住址', '个人信息备注',
        '就诊日期', '医院/科室', '中医诊断', '西医诊断', '方剂', '病历', '就诊备注'
    ]

    # ---- 表格 ----
    selection = st.dataframe(
        display_page_df[display_cols_with_tags],
        use_container_width=True,
        hide_index=True,
        selection_mode="multi-row",
        on_select="rerun",
        height=400
    )

    # ---- 分页控件 ----
    col_size, col_page = st.columns([0.5, 3])
    with col_size:
        st.selectbox(
            "每页行数",
            [10, 20, 50, 100],
            index=[10, 20, 50, 100].index(page_size),
            key="page_size_control",
            label_visibility="collapsed"
        )
    with col_page:
        st.pagination(
            num_pages=total_pages,
            default=current_page,
            key="table_pagination"
        )

    # ---- 获取选中索引 ----
    selected_indices = []
    if selection and selection.selection and selection.selection.rows:
        selected_indices = selection.selection.rows
    selected_count = len(selected_indices)
    has_single_selection = (selected_count == 1)

    # ---- 构建目标数据集 ----
    if st.session_state.get('select_all', False):
        target_df = display_df.copy()
        target_count = len(target_df)
    else:
        target_keys = set(st.session_state.manual_selection)
        for idx in selected_indices:
            row = page_df.iloc[idx]
            target_keys.add((row['患者姓名'], row['就诊日期']))
        if target_keys:
            target_df = display_df[display_df.apply(
                lambda row: (row['患者姓名'], row['就诊日期']) in target_keys, axis=1
            )]
            target_count = len(target_df)
        else:
            target_df = pd.DataFrame()
            target_count = 0

    # ---- 手动选中状态 + 操作按钮 ----
    manual_count = len(st.session_state.manual_selection)

    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns([2.3, 1.5, 1.5, 1.5])
    with col_btn1:
        if manual_count > 0:
            with st.popover(f"📋 已选 {manual_count} 条记录", use_container_width=True):
                st.caption("以下记录已被保留选中")
                selected_records = []
                for patient_name, visit_date in st.session_state.manual_selection:
                    match = display_df[
                        (display_df['患者姓名'] == patient_name) &
                        (display_df['就诊日期'] == visit_date)
                    ]
                    if not match.empty:
                        selected_records.append(match.iloc[0].to_dict())
                if selected_records:
                    df_selected = pd.DataFrame(selected_records)
                    display_cols = ['患者姓名', '性别', '出生日期', '电话', '身份证号', '住址', '个人信息备注',
                                    '就诊日期', '医院/科室', '中医诊断','西医诊断', '方剂', '病历', '就诊备注']
                    st.dataframe(df_selected[display_cols], use_container_width=True, hide_index=True)
                else:
                    st.info("选中的记录在当前筛选条件下未找到")
        else:
            st.button("📋 已选 0 条记录", use_container_width=True, disabled=True)

    with col_btn2:
        if st.session_state.get('select_all', False):
            if st.button("➕ 保留全选", use_container_width=True):
                all_keys = set()
                for _, row in display_df.iterrows():
                    all_keys.add((row['患者姓名'], row['就诊日期']))
                for key in all_keys:
                    if key not in st.session_state.manual_selection:
                        st.session_state.manual_selection.append(key)
                st.session_state['select_all'] = False
                st.session_state.pop('selected_all_df', None)
                st.session_state.pop('_saved_filter', None)
                st.rerun()
        else:
            if selected_indices:
                if st.button("➕ 保留选择", use_container_width=True):
                    for idx in selected_indices:
                        row = page_df.iloc[idx]
                        key = (row['患者姓名'], row['就诊日期'])
                        if key not in st.session_state.manual_selection:
                            st.session_state.manual_selection.append(key)
                    st.rerun()
            else:
                st.button("➕ 保留选择", use_container_width=True, disabled=True)

    with col_btn3:
        if len(display_df) > 0:
            if st.button("🔄 保留反选", use_container_width=True):
                page_keys = set((row['患者姓名'], row['就诊日期']) for _, row in page_df.iterrows())
                selected_page_keys = set()
                for idx in selected_indices:
                    row = page_df.iloc[idx]
                    selected_page_keys.add((row['患者姓名'], row['就诊日期']))
                current_manual = set(st.session_state.manual_selection)
                new_selection = [key for key in current_manual if key not in page_keys]
                for key in page_keys:
                    if key not in selected_page_keys:
                        new_selection.append(key)
                st.session_state.manual_selection = new_selection
                st.session_state['select_all'] = False
                st.session_state.pop('_saved_filter', None)
                st.rerun()
        else:
            st.button("🔄 保留反选", use_container_width=True, disabled=True)

    with col_btn4:
        if manual_count > 0 or st.session_state.get('select_all', False):
            if st.button("❌ 清空选择", use_container_width=True):
                st.session_state.manual_selection = []
                st.session_state['select_all'] = False
                st.session_state.pop('selected_all_df', None)
                st.session_state.pop('_saved_filter', None)
                st.rerun()
        else:
            st.button("❌ 清空选择", use_container_width=True, disabled=True)

    # ---- 操作按钮 ----
    col_open, col_download, col_delete = st.columns([2, 2, 2])
    with col_open:
        if has_single_selection:
            row = page_df.iloc[selected_indices[0]]
            file_path = row.get('文件路径', '')
            date_folder_path = row.get('日期文件夹路径', '')
            # 优先使用 date_folder_path
            if date_folder_path and os.path.exists(date_folder_path):
                folder_path = date_folder_path
            elif file_path and os.path.exists(os.path.dirname(file_path)):
                folder_path = os.path.dirname(file_path)
            else:
                folder_path = None
            if folder_path:
                if st.button("📂 打开文件夹", type="primary", use_container_width=True):
                    try:
                        open_folder(folder_path)
                        st.toast(f"✅ 已打开：{folder_path}", icon="📁", duration=5)
                    except Exception as e:
                        st.error(f"打开失败：{e}")
            else:
                st.button("📂 文件路径无效", disabled=True, use_container_width=True)
        else:
            st.button("📂 打开文件夹", disabled=True, use_container_width=True)

    with col_download:
        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            display_page_df[display_cols_with_tags].to_excel(writer, index=False, sheet_name='数据')
        excel_data = output.getvalue()
        st.download_button(
            label="📥 下载 Excel",
            data=excel_data,
            file_name="filtered_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_filtered_excel"
        )

    with col_delete:
        if target_count > 0:
            if st.button("🗑️ 删除选中", type="secondary", use_container_width=True):
                deleted_records = [(row['患者姓名'], row['就诊日期']) for _, row in target_df.iterrows()]
                with st.spinner("⏳ 正在删除..."):
                    result = delete_records_clean(
                        deleted_records_info=deleted_records,
                        db_path=db_path,
                        sync_enabled=st.session_state.get('sync_delete_enabled', False)
                    )
                if result['success']:
                    if result['deleted_folders'] > 0 or result.get('_deleted_hospitals'):
                        msg_parts = []
                        if result['deleted_folders'] > 0:
                            msg_parts.append(f"已同步删除 {result['deleted_folders']} 个文件夹")
                        if result.get('_deleted_hospitals'):
                            msg_parts.append(f"已清理 {len(result['_deleted_hospitals'])} 个空的医院文件夹")
                        st.session_state.pending_toast = "✅ " + "；".join(msg_parts)
                    else:
                        error_msg = f"❌ {result['message']}"
                        if result['errors']:
                            error_msg += "\n" + "\n".join([f"⚠️ {err}" for err in result['errors']])
                        st.session_state.pending_error = error_msg
                st.session_state['select_all'] = False
                st.session_state.pop('selected_all_df', None)
                st.session_state.manual_selection = []
                st.session_state.pop('_saved_filter', None)
                for key in ['search_results', 'search_term', 'group']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
        else:
            st.button("🗑️ 删除选中", disabled=True, use_container_width=True)

    # ---- 批量编辑 ----
    with st.expander("🏷️ 分组与标记", expanded=False):
        render_batch_tag_editor(target_df, db_path)

    # ---- 编辑就诊记录 ----
    with st.expander("✏️ 编辑就诊记录"):
        selected_patient = None
        selected_visit_date = None
        if has_single_selection:
            row = page_df.iloc[selected_indices[0]]
            selected_patient = row['患者姓名']
            selected_visit_date = row['就诊日期']
        edit_record_ui(
            patient_name=selected_patient,
            visit_date=selected_visit_date
        )

    # ---- 文件有效性检测 ----
    with st.expander("🔍 文件有效性检测", expanded=False):
        st.caption("扫描数据库中的文件路径，标记已被删除或移动的文件。")
        if st.button("🔍 扫描失效文件", use_container_width=True, key="scan_invalid_files"):
            from aurum_core.database import check_file_validity
            result = check_file_validity()
            valid_count = len(result['valid'])
            invalid_count = len(result['invalid'])
            if invalid_count == 0:
                st.success(f"✅ 所有 {valid_count} 条记录的文件均存在，无失效文件。")
                if 'invalid_files' in st.session_state:
                    del st.session_state['invalid_files']
            else:
                st.warning(f"⚠️ 发现 {invalid_count} 条失效记录，其文件已被删除或移动。")
                st.session_state['invalid_files'] = result['invalid']
                df_invalid = pd.DataFrame(
                    result['invalid'],
                    columns=['记录ID', '患者姓名', '就诊日期', '文件路径']
                )
                st.dataframe(df_invalid, use_container_width=True, hide_index=True)
        if 'invalid_files' in st.session_state and st.session_state['invalid_files']:
            if st.button("🗑️ 删除所有失效记录", type="primary", use_container_width=True):
                import sqlite3
                conn = sqlite3.connect(db_path)
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                ids_to_delete = [row[0] for row in st.session_state['invalid_files']]
                if ids_to_delete:
                    placeholders = ','.join(['?'] * len(ids_to_delete))
                    cursor.execute(f"DELETE FROM visits WHERE id IN ({placeholders})", ids_to_delete)
                    deleted_count = cursor.rowcount

                    from aurum_core.database import clean_orphan_tags
                    clean_orphan_tags(conn)

                    cursor.execute("SELECT DISTINCT patient_name FROM visits")
                    active_patients = [row[0] for row in cursor.fetchall()]
                    if active_patients:
                        placeholders_profiles = ','.join(['?'] * len(active_patients))
                        cursor.execute(
                            f"DELETE FROM patient_profiles WHERE patient_name NOT IN ({placeholders_profiles})",
                            active_patients)
                    else:
                        cursor.execute("DELETE FROM patient_profiles")
                    conn.commit()
                    conn.close()
                    st.session_state.pending_toast = f"已删除 {deleted_count} 条失效记录"
                    del st.session_state['invalid_files']
                    st.rerun()
                else:
                    st.info("没有失效记录需要删除。")
