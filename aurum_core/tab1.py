# aurum_core/tab1.py
import streamlit as st
import os
from aurum_core.file_processor import reorganize_files, clean_path, refresh_index_only

def render_tab1():
    col_title, col_icon = st.columns([6, 1], vertical_alignment="bottom")
    with col_title:
        st.header("📂 归档整理")
    with col_icon:
        with st.popover("❓", use_container_width=True):
            st.markdown("""
                **📂 归档整理**
                适用于你手里的**未整理病历**，支持以下两种常见情况：
                - **单次跟诊**：文件夹以日期开头（如 `2025-06-23 曙光医院`），里面直接放患者文件夹。
                - **多次跟诊集合**：一个总文件夹内包含多个日期文件夹（如 `2025-06-23 养和堂`、`2025-06-30 脾胃病科室`）。

                操作方式：选择源目录（日期文件夹或其父目录），设置目标目录（系统会自动生成建议），点击“执行归档整理”。

                **💡 小建议**：文件夹名尽量包含日期和医院/科室（如 `2025-06-23 养和堂`），患者文件夹以姓名命名，这样识别最准确。

                **🔄 刷新数据库**
                适用于你**已经整理好的归档文件夹**（结构为：医院/患者/日期），例如之前用 Aurum 生成的文件夹。
                当你在这个归档文件夹里新增、删除或修改了患者或日期，但不想重新复制全部文件时，使用此功能。

                操作方式：只输入归档根目录路径，点击“执行刷新”。
                系统会**扫描所有子文件夹**，将最新的文件路径和病历内容同步到数据库，**不会创建或修改任何文件夹**。

                **❗ 患者文件夹外的文件不会被归档**

                **📝 病历内容书写建议**
                - 个人信息建议**换行书写**，如：
                  姓名：张三
                  性别：男
                  年龄：45
                - 电话、身份证号等尽量与后续内容**存在换行或间隔**
                - 避免在字段值中使用 `**`（Markdown加粗）等特殊符号，以免干扰识别
                """)
    st.caption("按一定格式识别并整理文件夹，点击❓查看具体内容。")
    source_root = st.text_input(
        "📂 源目录",
        placeholder="例如：D:/患者病历",
        key="source_root_input"
    )
    source_root = clean_path(source_root)

    default_output = ""
    if source_root:
        parent_dir = os.path.dirname(source_root.rstrip("/\\"))
        base_name = os.path.basename(source_root.rstrip("/\\"))
        default_output = os.path.join(parent_dir, f"{base_name}_Aurum归档")

    target_root = st.text_input(
        "📦 目标目录",
        value=default_output,
        placeholder="留空则自动在源目录旁创建",
        key="target_root_input"
    )
    target_root = clean_path(target_root)

    submitted = st.button("🚀 执行归档整理", type="primary", use_container_width=True)

    log_placeholder = st.empty()

    if submitted:
        if not source_root:
            st.error("❌ 请先填写**源目录**路径")
        else:
            final_target = target_root if target_root.strip() else default_output
            if not final_target:
                st.error("❌ 无法自动生成目标路径，请手动填写")
            else:
                from aurum_core.user_settings import get_user_setting
                aggregate = get_user_setting('aggregate_visits', False)
                from aurum_core.user_settings import get_user_setting
                mode = "move" if get_user_setting('archive_mode', '复制') == "移动" else "copy"
                with st.spinner("⏳ 归档整理中..."):
                    result_log = reorganize_files(source_root, final_target, aggregate=aggregate, mode=mode)

                lines = result_log.split('\n')
                placeholder = st.empty()
                error_lines = [l for l in lines if '❌' in l]
                warning_lines = [l for l in lines if '⚠️' in l]
                success_lines = [l for l in lines if '✅' in l and '❌' not in l]

                # 完全失败：只有错误且没有任何成功
                if error_lines and not success_lines:
                    st.error("❌ 归档失败：" + error_lines[0])
                    with st.expander("📋 查看详细错误日志", expanded=True):
                        st.code("\n".join(error_lines), language="text")
                # 有错误（但也有一些成功）
                elif error_lines:
                    st.warning(f"⚠️ 归档完成，但有 {len(error_lines)} 条错误。")
                    with st.expander("📋 查看详细错误日志", expanded=True):
                        st.code("\n".join(error_lines), language="text")
                # 有警告（没有错误）
                elif warning_lines:
                    st.warning(f"⚠️ 归档完成，但有 {len(warning_lines)} 条警告。")
                    with st.expander("📋 查看详细警告日志", expanded=True):
                        st.code("\n".join(warning_lines), language="text")
                else:
                    # 全部成功
                    final_line = next((line for line in lines if line.startswith('🎉')), None)
                    if final_line:
                        st.success(final_line)
                    else:
                        st.success(f"🎉 归档完成！请前往 `{final_target}` 查看整理后的文件。")
                    # 成功时不展开日志（但用户可以手动展开）
                    with st.expander("📋 查看成功日志", expanded=False):
                        st.code("\n".join(success_lines), language="text")

    # ---- 刷新数据库（仅更新索引，不复制文件） ----
    with st.expander("🔄 刷新数据库"):
        st.caption(
            "适用于已经整理好的归档结构（医院/患者/日期），只将最新文件内容同步到数据库，并更新患者档案与文档索引，不会创建或修改任何文件夹。")
        refresh_root = st.text_input("📂 归档根目录", placeholder="例如：D:/MedicalData/test_Aurum归档",
                                     key="refresh_root_input")
        refresh_root = clean_path(refresh_root)
        if st.button("🔄 执行刷新", type="primary", use_container_width=True, key="btn_refresh"):
            if not refresh_root:
                st.error("❌ 请填写归档根目录路径")
            elif not os.path.exists(refresh_root):
                st.error("❌ 路径不存在，请检查")
            else:
                from aurum_core.user_settings import get_user_setting
                aggregate = get_user_setting('aggregate_visits', False)
                with st.spinner("⏳ 正在刷新数据库..."):
                    result_log = refresh_index_only(refresh_root, aggregate=aggregate)

                lines = result_log.split('\n')

                # 检查是否有错误
                has_error = any('❌' in line for line in lines if line.startswith('   '))
                has_warning = any('⚠️' in line for line in lines if line.startswith('   '))

                # 显示顶部状态
                if has_error:
                    st.warning("⚠️ 刷新完成，但存在错误。请查看下方日志。")
                else:
                    # 取最后一条成功消息
                    final_line = next((line for line in reversed(lines) if '✅' in line and '完成' in line),
                                      "✅ 数据库刷新完成！")
                    st.success(final_line)

                # ---- 显示完整日志（统一折叠） ----
                with st.expander("📋 查看更新记录", expanded=False):
                    # 过滤掉空行和纯标题行，显示所有有意义的日志
                    log_content = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('🔄') and not line.startswith('📂'):
                            log_content.append(line)

                    if not log_content:
                        st.caption("无任何变化。")
                    else:
                        st.code("\n".join(log_content), language="text")
