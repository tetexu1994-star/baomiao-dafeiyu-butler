# -*- coding: utf-8 -*-
import copy
import json
import os
import subprocess
import tempfile

from .persona import DAFEIYU_PROMPT_V36

ASTRBOT_PROVIDER_ID = "baomiao-deepseek"
ASTRBOT_PLATFORM_ID = "baomiao-qq"
DAFEIYU_PERSONA_ID = "dafeiyu_v36"

_PERSONA_BOOTSTRAP = """
import asyncio
import os

from astrbot.core import db_helper

async def main():
    await db_helper.initialize()
    try:
        await db_helper.get_persona_by_id(os.environ["BAOMIAO_PERSONA_ID"])
    except Exception:
        await db_helper.insert_persona(
            os.environ["BAOMIAO_PERSONA_ID"],
            os.environ["BAOMIAO_PERSONA_PROMPT"],
        )

asyncio.run(main())
"""


def _read_json(path, default):
    if not os.path.exists(path):
        return copy.deepcopy(default)
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else copy.deepcopy(default)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="config-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _upsert_by_id(items, item):
    result = [copy.deepcopy(entry) for entry in items if isinstance(entry, dict)]
    for index, entry in enumerate(result):
        if entry.get("id") == item["id"]:
            result[index] = copy.deepcopy(item)
            return result
    result.append(copy.deepcopy(item))
    return result


def build_astrbot_config(existing, user_config):
    config = copy.deepcopy(existing)
    master_qq = str(user_config.get("master_qq", "")).strip()
    api_provider = str(user_config.get("api_provider", "deepseek")).strip()
    api_key = str(user_config.get("api_key", "")).strip()
    api_base = str(user_config.get("api_base", "https://api.deepseek.com/v1")).strip()
    model_name = str(user_config.get("model_name", "deepseek-chat")).strip()
    onebot_port = int(user_config.get("napcat_port", 6199))

    if api_provider == "baomiao":
        api_base = str(user_config.get("api_base") or "https://api.baomiao.com/v1").strip()
        if not api_key:
            raise ValueError("请填入暴喵专属 API Key（若未持有，可点击下方按钮下载暴喵AI管家免费领取）")
    elif api_provider == "deepseek":
        api_base = str(user_config.get("api_base") or "https://api.deepseek.com/v1").strip()
        if not api_key:
            raise ValueError("DeepSeek API Key 不能为空")
    else:
        raise ValueError(f"不支持的模型通道: {api_provider}")

    provider = {
        "id": ASTRBOT_PROVIDER_ID,
        "provider": "openai" if api_provider == "baomiao" else "deepseek",
        "type": "openai_chat_completion",
        "provider_type": "chat_completion",
        "enable": True,
        "key": [api_key],
        "model": model_name,
        "api_base": api_base,
        "timeout": 120,
        "proxy": "",
        "custom_headers": {},
    }
    platform = {
        "id": ASTRBOT_PLATFORM_ID,
        "type": "aiocqhttp",
        "enable": True,
        "ws_reverse_host": "127.0.0.1",
        "ws_reverse_port": onebot_port,
        "ws_reverse_token": "",
    }

    config["config_version"] = 5
    config["provider"] = _upsert_by_id(config.get("provider", []), provider)
    config["platform"] = _upsert_by_id(config.get("platform", []), platform)

    provider_settings = config.setdefault("provider_settings", {})
    provider_settings["enable"] = True
    provider_settings["default_provider_id"] = ASTRBOT_PROVIDER_ID
    provider_settings["default_personality"] = DAFEIYU_PERSONA_ID

    platform_settings = config.setdefault("platform_settings", {})
    platform_settings["enable_id_white_list"] = bool(user_config.get("whitelist_only", True))
    platform_settings["id_whitelist"] = (
        [f"aiocqhttp:FriendMessage:{master_qq}"] if master_qq else []
    )
    platform_settings["wl_ignore_admin_on_group"] = True
    platform_settings["wl_ignore_admin_on_friend"] = True

    config["admins_id"] = [master_qq] if master_qq else []
    config["persona"] = [
        {
            "name": DAFEIYU_PERSONA_ID,
            "prompt": DAFEIYU_PROMPT_V36,
            "begin_dialogs": [],
            "mood_imitation_dialogs": [],
        }
    ]

    dashboard = config.setdefault("dashboard", {})
    dashboard["enable"] = True
    dashboard["host"] = "127.0.0.1"
    dashboard["port"] = int(user_config.get("astrbot_port", 6185))
    dashboard["password_change_required"] = True
    return config


def _venv_python(install_dir):
    if os.name == "nt":
        return os.path.join(install_dir, "AstrBot", ".venv", "Scripts", "python.exe")
    return os.path.join(install_dir, "AstrBot", ".venv", "bin", "python")


def inject_astrbot_persona(install_dir):
    python_path = _venv_python(install_dir)
    if not os.path.exists(python_path):
        raise RuntimeError("AstrBot Python 环境不存在")
    env = os.environ.copy()
    env["ASTRBOT_ROOT"] = os.path.join(install_dir, "AstrBot")
    env["BAOMIAO_PERSONA_ID"] = DAFEIYU_PERSONA_ID
    env["BAOMIAO_PERSONA_PROMPT"] = DAFEIYU_PROMPT_V36
    result = subprocess.run(
        [python_path, "-c", _PERSONA_BOOTSTRAP],
        cwd=env["ASTRBOT_ROOT"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"注入大肥鱼人设失败: {result.stdout[-800:]}")


def generate_astrbot_config(install_dir, user_config):
    config_file = os.path.join(install_dir, "AstrBot", "data", "cmd_config.json")
    existing = _read_json(config_file, {})
    config = build_astrbot_config(existing, user_config)
    _write_json(config_file, config)
    inject_astrbot_persona(install_dir)
    return config_file


def build_napcat_config(existing, user_config):
    config = copy.deepcopy(existing)
    onebot_port = int(user_config.get("napcat_port", 6199))
    config["ws"] = {
        "enable": False,
        "host": "127.0.0.1",
        "port": onebot_port,
        "secret": "",
    }
    config["reverseWs"] = {
        "enable": True,
        "urls": [f"ws://127.0.0.1:{onebot_port}/ws"],
        "messagePostFormat": "array",
        "reportSelfMessage": False,
        "reconnectInterval": 5000,
        "heartbeatInterval": 10000,
        "token": "",
    }
    return config


def generate_napcat_config(install_dir, user_config):
    napcat_dir = os.path.join(install_dir, "NapCat")
    config_dir = os.path.join(napcat_dir, "config")
    os.makedirs(config_dir, exist_ok=True)

    bot_qq = str(user_config.get("bot_qq", "")).strip()
    config_filenames = ["onebot11.json"]
    if bot_qq:
        config_filenames.append(f"onebot11_{bot_qq}.json")

    for filename in config_filenames:
        target_path = os.path.join(config_dir, filename)
        existing = _read_json(target_path, {})
        _write_json(target_path, build_napcat_config(existing, user_config))

    return os.path.join(config_dir, config_filenames[0])
