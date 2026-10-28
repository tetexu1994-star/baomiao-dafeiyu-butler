# -*- coding: utf-8 -*-
import os
import json

DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".baomiao_dafeiyu", "config.json")

DEFAULT_CONFIG = {
    "master_qq": "",
    "bot_qq": "",
    "api_provider": "deepseek",  # deepseek / baomiao / custom
    "api_key": "",
    "api_base": "https://api.deepseek.com/v1",
    "model_name": "deepseek-chat",
    "install_dir": os.path.join(os.path.expanduser("~"), "BaomiaoDaFeiYu"),
    "napcat_port": 3001,
    "astrbot_port": 6185,
    "auto_launch": True,
    "enable_tts": False,
    "whitelist_only": True
}

def load_user_config():
    if os.path.exists(DEFAULT_CONFIG_PATH):
        try:
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(saved)
                return config
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_user_config(config_data):
    os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)
    return True
