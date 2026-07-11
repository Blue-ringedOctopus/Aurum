import os
import yaml
import streamlit as st

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def save_config(config):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

def get_user_settings(username: str = None) -> dict:
    """获取当前用户的所有偏好设置"""
    if username is None:
        username = st.session_state.get('username', '')
    if not username:
        return {}
    config = load_config()
    return config.get('user_settings', {}).get(username, {})

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
    if username not in config['user_settings']:
        config['user_settings'][username] = {}
    # 增量更新
    config['user_settings'][username].update(settings_dict)
    save_config(config)