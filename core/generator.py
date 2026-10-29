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
    config["wake_prefix"] = []
    config["provider"] = _upsert_by_id(config.get("provider", []), provider)
    config["platform"] = _upsert_by_id(config.get("platform", []), platform)

    # AstrBot 4.x Agent Runner 核心架构绑定（缺少此项会导致 LLM 模型无法调度，无回复）
    runner = config.setdefault("agent_runner", {})
    runner["runner_type"] = "local"
    runner_cfg = runner.setdefault("config", {})
    model_cfg = runner_cfg.setdefault("model", {})
    model_cfg["provider_id"] = ASTRBOT_PROVIDER_ID
    model_cfg["fallback_provider_ids"] = []
    model_cfg["request_max_retries"] = 5

    persona_cfg = runner_cfg.setdefault("persona", {})
    persona_cfg["persona_id"] = DAFEIYU_PERSONA_ID
    persona_cfg["safety_mode"] = False

    comp_cfg = runner_cfg.setdefault("compression", {})
    comp_cfg["provider_id"] = ASTRBOT_PROVIDER_ID

    provider_settings = config.setdefault("provider_settings", {})
    provider_settings["enable"] = True
    provider_settings["default_provider_id"] = ASTRBOT_PROVIDER_ID
    provider_settings["default_personality"] = DAFEIYU_PERSONA_ID
    provider_settings["wake_prefix"] = ""

    platform_settings = config.setdefault("platform_settings", {})
    # 默认关闭白名单拦截，确保用户与机器人无论是私聊还是群聊均能立即得到大肥鱼回复
    platform_settings["enable_id_white_list"] = bool(user_config.get("whitelist_only", False))
    platform_settings["id_whitelist"] = (
        [f"aiocqhttp:FriendMessage:{master_qq}"] if master_qq else []
    )
    platform_settings["wl_ignore_admin_on_group"] = True
    platform_settings["wl_ignore_admin_on_friend"] = True
    platform_settings["friend_message_needs_wake_prefix"] = False
    platform_settings["ignore_bot_self_message"] = False

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


def _silent_kwargs():
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def inject_astrbot_persona(install_dir):
    # 1. 直接更新 SQLite 数据库中的 default 和 dafeiyu_v36，彻底保证对话时人设100%生效
    db_paths = [
        os.path.join(install_dir, "AstrBot", "data", "data_v4.db"),
        os.path.join(os.path.expanduser("~"), "data", "data_v4.db"),
    ]
    for db_path in db_paths:
        if os.path.isfile(db_path):
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                conn.execute("UPDATE personas SET system_prompt = ? WHERE persona_id = 'default'", (DAFEIYU_PROMPT_V36,))
                conn.execute("INSERT OR REPLACE INTO personas (persona_id, system_prompt) VALUES (?, ?)", (DAFEIYU_PERSONA_ID, DAFEIYU_PROMPT_V36))
                conn.execute("INSERT OR REPLACE INTO personas (persona_id, system_prompt) VALUES ('default', ?)", (DAFEIYU_PROMPT_V36,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    python_path = _venv_python(install_dir)
    if not os.path.exists(python_path):
        return
    env = os.environ.copy()
    env["ASTRBOT_ROOT"] = os.path.join(install_dir, "AstrBot")
    env["BAOMIAO_PERSONA_ID"] = DAFEIYU_PERSONA_ID
    env["BAOMIAO_PERSONA_PROMPT"] = DAFEIYU_PROMPT_V36
    subprocess.run(
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
        **_silent_kwargs(),
    )


def generate_astrbot_config(install_dir, user_config):
    config_file = os.path.join(install_dir, "AstrBot", "data", "cmd_config.json")
    existing = _read_json(config_file, {})
    config = build_astrbot_config(existing, user_config)
    _write_json(config_file, config)

    # 同步写入外部根目录 data，避免无论哪个路径解析都能100%命中正确模型配置
    extra_cfg = os.path.join(os.path.expanduser("~"), "data", "cmd_config.json")
    try:
        if os.path.isdir(os.path.dirname(extra_cfg)):
            _write_json(extra_cfg, config)
    except Exception:
        pass

    inject_astrbot_persona(install_dir)
    return config_file


def build_napcat_config(existing, user_config):
    config = copy.deepcopy(existing)
    onebot_port = int(user_config.get("napcat_port", 6199))
    ws_url = f"ws://127.0.0.1:{onebot_port}/ws"

    # NapCat 4.x (新网络适配架构)
    network = config.setdefault("network", {})
    network.setdefault("httpServers", [])
    network.setdefault("httpSseServers", [])
    network.setdefault("httpClients", [])
    network.setdefault("websocketServers", [])
    network.setdefault("plugins", [])

    ws_client = {
        "name": "AstrBot",
        "enable": True,
        "url": ws_url,
        "messagePostFormat": "array",
        "reportSelfMessage": False,
        "reconnectInterval": 3000,
        "token": "",
        "debug": False,
        "heartInterval": 30000,
    }

    ws_clients = network.get("websocketClients", [])
    found = False
    for idx, client in enumerate(ws_clients):
        if isinstance(client, dict) and (client.get("name") == "AstrBot" or str(onebot_port) in client.get("url", "")):
            ws_clients[idx] = ws_client
            found = True
            break
    if not found:
        ws_clients.append(ws_client)
    network["websocketClients"] = ws_clients

    # 兼容 NapCat 2.x/3.x 旧架构
    config["ws"] = {
        "enable": False,
        "host": "127.0.0.1",
        "port": onebot_port,
        "secret": "",
    }
    config["reverseWs"] = {
        "enable": True,
        "urls": [ws_url],
        "messagePostFormat": "array",
        "reportSelfMessage": False,
        "reconnectInterval": 3000,
        "heartbeatInterval": 10000,
        "token": "",
    }
    return config


def generate_napcat_config(install_dir, user_config):
    napcat_dir = os.path.join(install_dir, "NapCat")
    config_dirs = [
        os.path.join(napcat_dir, "config"),
        os.path.join(napcat_dir, "napcat", "config"),
    ]
    bot_qq = str(user_config.get("bot_qq", "")).strip()
    config_filenames = ["onebot11.json"]
    if bot_qq:
        config_filenames.append(f"onebot11_{bot_qq}.json")

    for cdir in config_dirs:
        os.makedirs(cdir, exist_ok=True)
        for filename in config_filenames:
            target_path = os.path.join(cdir, filename)
            existing = _read_json(target_path, {})
            _write_json(target_path, build_napcat_config(existing, user_config))

    return os.path.join(config_dirs[0], config_filenames[0])
