# -*- coding: utf-8 -*-
import os
import json
import tempfile

DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".baomiao_dafeiyu", "config.json")

DEFAULT_CONFIG = {
    "master_qq": "",
    "bot_qq": "",
    "api_provider": "deepseek",  # deepseek / custom
    "api_key": "",
    "api_base": "https://api.deepseek.com/v1",
    "model_name": "deepseek-chat",
    "install_dir": os.path.join(os.path.expanduser("~"), "BaomiaoDaFeiYu"),
    "napcat_port": 6199,
    "astrbot_port": 6185,
    "auto_launch": True,
    "enable_tts": False,
    "whitelist_only": False,
}

ALLOWED_CONFIG_KEYS = frozenset(DEFAULT_CONFIG)


def load_user_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(DEFAULT_CONFIG_PATH):
        try:
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                config.update({key: value for key, value in saved.items() if key in ALLOWED_CONFIG_KEYS})
        except (OSError, ValueError, TypeError):
            pass
    if not str(config.get("install_dir", "")).strip():
        config["install_dir"] = DEFAULT_CONFIG["install_dir"]
    config["whitelist_only"] = False
    return config


def save_user_config(config_data):
    config_dir = os.path.dirname(DEFAULT_CONFIG_PATH)
    os.makedirs(config_dir, exist_ok=True)
    payload = {key: config_data.get(key, DEFAULT_CONFIG[key]) for key in ALLOWED_CONFIG_KEYS}
    fd, temp_path = tempfile.mkstemp(prefix="config-", suffix=".json", dir=config_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, DEFAULT_CONFIG_PATH)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return True


def public_user_config(config_data):
    public = {key: config_data.get(key, DEFAULT_CONFIG[key]) for key in ALLOWED_CONFIG_KEYS}
    public["api_key"] = ""
    public["api_key_set"] = bool(str(config_data.get("api_key", "")).strip())
    return public
