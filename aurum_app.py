import streamlit as st
import yaml
import bcrypt
import os
import platform

from aurum_core.tab1 import render_tab1
from aurum_core.tab2 import render_tab2
from aurum_core.tab3 import render_tab3
from aurum_core.user_settings import get_user_setting, save_user_settings
from aurum_core.database import init_database, upgrade_database
from aurum_core.utils import open_folder

# 当前版本号（每次发布新版本时手动更新）
CURRENT_VERSION = "1.0.0"  # 请根据实际版本修改

# 你的 GitHub 用户名和仓库名
GITHUB_REPO = "Blue-ringedOctopus/Aurum"  # 替换为你的用户名和仓库名

# 确保 config.yaml 存在，若不存在则创建默认结构
if not os.path.exists('config.yaml'):
    default_config = {
        'credentials': {'usernames': {}},
        'user_settings': {},
        'cookie': {
            'expiry_days': 30,
            'key': 'HelloAurum!',
            'name': 'HapalochlaenaMaculosa'
        }
    }
    with open('config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)

def get_cert_path():
    """返回可用的 CA 证书路径，用于 requests 的 verify 参数"""
    import os
    import sys

    # 打包环境：one-dir 模式下，exe 所在目录即为根目录
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath('.')

    # 优先使用打包时一起发布的 cacert.pem
    cert_path = os.path.join(base, 'cacert.pem')
    if os.path.exists(cert_path):
        return cert_path

    # 备选：使用 certifi 库提供的证书（如果环境中存在）
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None

def check_for_updates(show_ignore: bool = True):
    """
    检查 GitHub 最新版本，显示提示并提供手动下载链接。
    出错时显示明确的错误信息。
    """
    import platform
    import webbrowser
    import requests
    import urllib3

    # macOS 特殊处理
    if platform.system() == 'Darwin':
        st.info(f"📢 发现新版本 **{latest_version}** (当前版本 v{CURRENT_VERSION})")
        st.markdown("[🌐 前往下载](https://github.com/Blue-ringedOctopus/Aurum/releases/latest)")
        return

    # 禁用 SSL 警告（因为 verify=False）
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    api_url = "https://api.github.com/repos/Blue-ringedOctopus/Aurum/releases/latest"

    try:
        # 请求最新 Release 信息
        resp = requests.get(api_url, timeout=10, verify=False)
        resp.raise_for_status()  # 如果状态码不是 200，抛出异常
        release = resp.json()
        latest_version = release.get("tag_name", "").lstrip('v')

        if not latest_version:
            st.error("无法解析版本信息，请稍后重试或手动访问 GitHub Releases。")
            return

        # 比较版本
        if latest_version <= CURRENT_VERSION:
            st.success(f"✅ 您已是最新版本 (v{CURRENT_VERSION})")
            return

        # 有新版本
        st.info(f"📢 发现新版本 **{latest_version}** (当前版本 v{CURRENT_VERSION})")
        st.markdown("[🌐 前往下载](https://github.com/Blue-ringedOctopus/Aurum/releases/latest)")

    except requests.exceptions.RequestException as e:
        st.error(f"网络请求失败：{e}\n请检查网络连接后重试，或手动访问 GitHub Releases。")
    except ValueError as e:
        st.error(f"解析版本信息失败：{e}\n请稍后重试，或手动访问 GitHub Releases。")
    except Exception as e:
        st.error(f"检查更新时发生未知错误：{e}\n请手动访问 GitHub Releases 查看最新版本。")

def perform_update(download_url):
    """
    下载新版本的 .zip 压缩包，解压并覆盖旧文件（保留 config.yaml 和 aurum_index.db）。
    增加详细的状态反馈。
    """
    import os
    import sys
    import tempfile
    import zipfile
    import shutil
    import subprocess
    import time
    import requests
    import webbrowser
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        # 开始提示
        st.toast("🚀 开始更新...", icon="⬇️")

        PROXY_LIST = [
            "https://ghproxy.com/",
            "https://ghproxy.net/",
            "https://gitproxy.click/",
        ]
        urls_to_try = [download_url] + [proxy + download_url for proxy in PROXY_LIST]

        temp_zip = os.path.join(tempfile.gettempdir(), "Aurum_update.zip")
        downloaded = False

        # 下载
        with st.spinner("正在下载更新包..."):
            for url in urls_to_try:
                try:
                    response = requests.get(url, stream=True, timeout=30, verify=False)
                    if response.status_code == 200:
                        total_size = int(response.headers.get('content-length', 0))
                        progress_bar = st.progress(0, text="下载进度")
                        downloaded_bytes = 0
                        with open(temp_zip, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                                if total_size > 0:
                                    progress_bar.progress(min(downloaded_bytes / total_size, 1.0))
                        progress_bar.empty()
                        downloaded = True
                        break
                except Exception:
                    continue

        if not downloaded:
            st.error("下载失败，请检查网络或前往 GitHub Releases 手动下载。")
            st.markdown("[🌐 前往下载](https://github.com/Blue-ringedOctopus/Aurum/releases/latest)")
            return

        st.success("下载完成，正在解压...")

        # 解压
        extract_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # 获取当前程序所在目录
        if getattr(sys, 'frozen', False):
            current_dir = os.path.dirname(sys.executable)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))

        st.info("正在替换文件（保留您的配置和数据库）...")

        # 复制文件
        for root, dirs, files in os.walk(extract_dir):
            rel_path = os.path.relpath(root, extract_dir)
            if rel_path == '.':
                target_dir = current_dir
            else:
                target_dir = os.path.join(current_dir, rel_path)
                os.makedirs(target_dir, exist_ok=True)

            for file in files:
                if file in ['config.yaml', 'aurum_index.db']:
                    continue
                src_file = os.path.join(root, file)
                dst_file = os.path.join(target_dir, file)
                try:
                    shutil.copy2(src_file, dst_file)
                except Exception as e:
                    st.warning(f"⚠️ 无法复制 {file}：{e}")

        # 清理临时文件
        shutil.rmtree(extract_dir, ignore_errors=True)
        os.remove(temp_zip)

        # 显示成功并延迟退出
        st.success("🎉 更新完成！程序将自动重启。")
        time.sleep(3)

        # 重启程序
        if getattr(sys, 'frozen', False):
            subprocess.Popen([sys.executable])
        else:
            subprocess.Popen([sys.executable, __file__])
        sys.exit(0)

    except Exception as e:
        st.error(f"❌ 更新失败：{e}")
        # 清理临时文件
        try:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
        except:
            pass

def ensure_config_structure(config: dict) -> dict:
    """确保 config 中的 credentials 和 user_settings 始终为字典，且不为 None"""
    if 'credentials' not in config or config['credentials'] is None:
        config['credentials'] = {'usernames': {}}
    if 'usernames' not in config['credentials'] or config['credentials']['usernames'] is None:
        config['credentials']['usernames'] = {}

    if 'user_settings' not in config or config['user_settings'] is None:
        config['user_settings'] = {}
    return config


def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
    return ensure_config_structure(config)


def save_config(config):
    config = ensure_config_structure(config)
    with open('config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

# --- 页面配置 ---
st.set_page_config(page_title="Aurum", page_icon="📜")

# --- 预先设置 SSL 证书环境变量（解决打包后 SSL 验证问题） ---
cert_path = get_cert_path()
if cert_path:
    os.environ['SSL_CERT_FILE'] = cert_path

# --- 数据库初始化 ---
db_path = "aurum_index.db"
init_database(db_path)
upgrade_database(db_path)

# ===== 持久化 Session 状态（解决刷新退出问题） =====
@st.cache_resource
def get_persistent_state():
    """返回一个跨刷新持久化的状态字典"""
    return {
        "authenticated": False,
        "username": "",
    }

# 初始化 st.session_state 中的持久化引用
if "persistent_state" not in st.session_state:
    st.session_state.persistent_state = get_persistent_state()

# 从持久化状态恢复登录信息
persistent = st.session_state.persistent_state
if persistent["authenticated"] and not st.session_state.get("authenticated"):
    st.session_state.authenticated = True
    st.session_state.username = persistent["username"]

# --- 登录逻辑 ---
def login():
    st.subheader("🔐 登录 Aurum")
    with st.form("login_form"):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        col1, col2, col3 = st.columns([3, 2, 1])
        with col3:
            submitted = st.form_submit_button("登录", type="primary", use_container_width=True)

        if submitted:
            if not username or not password:
                st.error("请输入用户名和密码")
            else:
                config = load_config()
                users = config.get('credentials', {}).get('usernames', {})
                if username not in users:
                    st.error("用户名不存在")
                else:
                    stored_hash = users[username]['password']
                    if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                        # 登录成功：更新持久化状态
                        persistent = st.session_state.persistent_state
                        persistent["authenticated"] = True
                        persistent["username"] = username
                        st.session_state.authenticated = True
                        st.session_state.username = username
                        st.rerun()
                    else:
                        st.error("密码错误")

# --- 注册功能 ---
def render_register():
    st.subheader("注册新账号")
    with st.form("register_form"):
        new_username = st.text_input("用户名")
        new_password = st.text_input("密码", type="password")
        confirm = st.text_input("确认密码", type="password")
        col1, col2, col3 = st.columns([3, 2, 1])
        with col3:
            submitted = st.form_submit_button("注册", type="primary", use_container_width=True)
        if submitted:
            if not new_username or not new_password:
                st.error("请填写完整")
            elif new_password != confirm:
                st.error("两次密码不一致")
            elif len(new_password) < 6:
                st.error("密码至少6位")
            else:
                config = load_config()
                if 'credentials' not in config:
                    config['credentials'] = {'usernames': {}}
                usernames = config['credentials']['usernames']
                if new_username in usernames:
                    st.error("用户名已存在")
                else:
                    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    usernames[new_username] = {
                        'password': hashed,
                        'api_key': ''
                    }
                    save_config(config)
                    st.session_state.register_success = "注册成功！请登录。"
                    st.session_state.show_register = False
                    st.rerun()

# --- 重置密码功能 ---
def render_reset_password():
    st.subheader("重置密码")
    reset_username = st.text_input("用户名", key="reset_username_external").strip()

    if reset_username:
        config = load_config()
        users = config.get('credentials', {}).get('usernames', {})
        if reset_username not in users:
            st.error("❌ 用户名不存在")

    with st.form("reset_form"):
        new_pass = st.text_input("新密码", type="password")
        confirm_pass = st.text_input("确认新密码", type="password")
        col1, col2, col3 = st.columns([3, 2, 1])
        with col3:
            submitted = st.form_submit_button("重置", type="primary", use_container_width=True)

        if submitted:
            if not reset_username:
                st.error("请输入用户名")
            else:
                config = load_config()
                users = config.get('credentials', {}).get('usernames', {})
                if reset_username not in users:
                    st.error("用户名不存在")
                elif new_pass != confirm_pass:
                    st.error("两次密码不一致")
                elif len(new_pass) < 6:
                    st.error("密码至少6位")
                else:
                    hashed = bcrypt.hashpw(new_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    config['credentials']['usernames'][reset_username]['password'] = hashed
                    save_config(config)
                    st.session_state.reset_success = "✅ 密码已重置！请使用新密码登录。"
                    st.session_state.show_reset = False
                    st.rerun()

# --- 登出函数 ---
def logout():
    # 清除持久化状态
    persistent = st.session_state.persistent_state
    persistent["authenticated"] = False
    persistent["username"] = ""
    # 清除 session_state 中的临时状态
    for key in ['authenticated', 'username', 'api_key']:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# --- 页面主逻辑 ---
# 检查是否已登录（已从持久化状态恢复）
if not st.session_state.get('authenticated'):
    login()
    # 显示各种成功消息
    if st.session_state.get("reset_success"):
        st.success(st.session_state.reset_success)
        del st.session_state.reset_success
    elif st.session_state.get("logout_success"):
        st.success(st.session_state.logout_success)
        del st.session_state.logout_success
    elif st.session_state.get("register_success"):
        st.success(st.session_state.register_success)
        del st.session_state.register_success
    else:
        st.info("新用户请注册。若忘记密码，可重置密码。")

    # 注册/重置密码按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📝 注册新账号", use_container_width=True):
            st.session_state.show_register = not st.session_state.get('show_register', False)
            st.session_state.show_reset = False
    with col2:
        if st.button("🔑 忘记密码", use_container_width=True):
            st.session_state.show_reset = not st.session_state.get('show_reset', False)
            st.session_state.show_register = False

    if st.session_state.get('show_register'):
        render_register()
    if st.session_state.get('show_reset'):
        render_reset_password()
else:
    # 已登录：显示主界面
    username = st.session_state['username']
    config = load_config()
    user_config = config['credentials']['usernames'][username]
    if user_config.get('api_key'):
        st.session_state.api_key = user_config['api_key']

    # 统一 tab 宽度
    st.markdown("""
    <style>
    div[data-testid="stTabs"] button {
        flex: 1 1 0%;
        min-width: 0;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("📜 Aurum - 中医病历智能整理")
    st.write(f"欢迎, **{username}**! 你已成功登录。")

    # 启动时自动检查更新（仅一次）
    if 'checked_update' not in st.session_state:
        check_for_updates(show_ignore=True)
        st.session_state.checked_update = True

    tab1, tab2, tab3 = st.tabs(["📂 归档整理", "📊 数据库浏览", "🤖 智能体"])
    with tab1:
        render_tab1()
    with tab2:
        render_tab3()
    with tab3:
        render_tab2()

    # 侧边栏
    with st.sidebar:
        st.write(f"已登录: **{username}**")
        if st.session_state.get('api_key'):
            st.success("🔑 API 密钥已关联")
            if st.checkbox("显示完整 API 密钥"):
                st.code(st.session_state.api_key, language="text")
            else:
                st.info("密钥已隐藏")
        else:
            st.warning("⚠️ 未关联 API 密钥")

        col_logout1, col_logout2 = st.columns(2)
        with col_logout1:
            if st.button("🚪 登出", use_container_width=True):
                logout()
        with col_logout2:
            if st.button("🚫 注销账号", use_container_width=True):
                username = st.session_state['username']
                config = load_config()
                if username in config['credentials']['usernames']:
                    del config['credentials']['usernames'][username]
                    # 同时删除 user_settings
                    if 'user_settings' in config and username in config['user_settings']:
                        del config['user_settings'][username]
                    save_config(config)
                    st.session_state.logout_success = "✅ 账号已注销！"
                    logout()
                    st.rerun()
                else:
                    st.error("用户不存在")
        # 自定义设置区
        st.sidebar.divider()
        st.sidebar.subheader("⚙️ 设置")

        # 第一行：删除同步开关
        col1, col2 = st.sidebar.columns([2, 0.5])
        with col1:
            st.write("🗑️ 同步删除归档文件夹")
        with col2:
            st.toggle(
                "",
                value=st.session_state.get('sync_delete_enabled', get_user_setting('sync_delete_enabled', False)),
                key="sync_delete_enabled",
                on_change=lambda: save_user_settings({'sync_delete_enabled': st.session_state.sync_delete_enabled}),
                label_visibility="collapsed"
            )

        # 第二行：汇总开关 + 诊断下拉框（同行）
        col1, col2 = st.sidebar.columns([2, 0.5])
        with col1:
            st.write("📄 汇总所有就诊记录")
        with col2:
            st.toggle(
                "",
                value=st.session_state.get('aggregate_visits', get_user_setting('aggregate_visits', False)),
                key="aggregate_visits",
                on_change=lambda: save_user_settings({'aggregate_visits': st.session_state.aggregate_visits}),
                label_visibility="collapsed"
            )

        # 第三行：诊断关键词归属（单独一行）
        col1, col2 = st.sidebar.columns([2, 2])
        with col1:
            st.write("📋 “诊断”作为")
        with col2:
            st.selectbox(
                "",
                ["中医诊断", "西医诊断"],
                index=0 if st.session_state.get('diagnosis_keyword_mode', '中医诊断') == '中医诊断' else 1,
                key="diagnosis_keyword_mode",
                on_change=lambda: save_user_settings(
                    {'diagnosis_keyword_mode': st.session_state.diagnosis_keyword_mode}),
                label_visibility="collapsed"
            )

        # 数据存储位置
        st.sidebar.divider()
        st.sidebar.subheader("📁 数据存储位置")
        db_path = os.path.abspath("aurum_index.db")
        st.sidebar.write(f"**数据库文件**：`{db_path}`")
        if st.sidebar.button("📂 打开数据库所在文件夹", key="open_db_folder"):
            try:
                open_folder(db_path)
            except Exception as e:
                st.sidebar.error(f"打开失败：{e}")
        st.sidebar.caption("💡 请不要移动数据库文件，以免程序出错。")

        # ---- 版本号 + 联系方式 ----
        st.sidebar.divider()
        # 在侧边栏合适位置（比如在设置区域后面）
        if st.sidebar.button("🔍 检查更新", use_container_width=True):
            check_for_updates(show_ignore=False)
        st.sidebar.caption(f"版本 v{CURRENT_VERSION}")
        st.sidebar.caption("联系我们：aurumdeveloper@yeah.net")

#启动代码：streamlit run aurum_app.py