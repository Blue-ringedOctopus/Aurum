import os
import yaml
import streamlit as st

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")


# ========== 配置结构保证 ==========
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
    """加载 config.yaml 并保证结构完整"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        config = {}
    return ensure_config_structure(config)


def save_config(config):
    """保存 config.yaml"""
    config = ensure_config_structure(config)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


# ========== 用户设置读写 ==========
def get_user_settings(username: str = None) -> dict:
    """获取当前用户的所有偏好设置"""
    if username is None:
        username = st.session_state.get('username', '')
    if not username:
        return {}
    config = load_config()
    settings = config.get('user_settings', {}).get(username, {})
    # 确保返回字典
    if settings is None:
        return {}
    return settings


def get_user_setting(key: str, default=None, username: str = None) -> any:
    """获取当前用户的某个偏好值"""
    settings = get_user_settings(username)
    return settings.get(key, default)


def save_user_settings(settings_dict: dict, username: str = None):
    """保存当前用户的偏好设置（增量更新）"""
    if username is None:
        username = st.session_state.get('username', '')
    if not username:
        return
    config = load_config()
    if 'user_settings' not in config:
        config['user_settings'] = {}
    if username not in config['user_settings'] or config['user_settings'][username] is None:
        config['user_settings'][username] = {}
    config['user_settings'][username].update(settings_dict)
    save_config(config)


def ensure_default_settings(username: str = None):
    """
    确保当前用户的所有高级设置字段在 config.yaml 中存在。
    若缺失则用默认值补全。只补字段，不覆盖已有值。
    """
    if username is None:
        username = st.session_state.get('username', '')
    if not username:
        return

    config = load_config()
    if 'user_settings' not in config:
        config['user_settings'] = {}
    if username not in config['user_settings'] or config['user_settings'][username] is None:
        config['user_settings'][username] = {}

    settings = config['user_settings'][username]
    # 确保 settings 是字典
    if settings is None:
        settings = {}
        config['user_settings'][username] = settings

    defaults = {
        'archive_mode': '复制',
        'aggregate_visits': False,
        'diagnosis_keyword_mode': '中医',
        'sync_delete_enabled': False,
        'enable_hospital_layer': True,
    }

    needs_update = False
    for key, default_value in defaults.items():
        if key not in settings:
            settings[key] = default_value
            needs_update = True

    if needs_update:
        config['user_settings'][username] = settings
        save_config(config)