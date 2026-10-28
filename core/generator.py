# -*- coding: utf-8 -*-
import os
import json
from .persona import DAFEIYU_PROMPT_V36

def generate_astrbot_config(install_dir, user_config):
    """
    生成 AstrBot 的配置文件 (data/config.json)
    """
    data_dir = os.path.join(install_dir, "AstrBot", "data")
    os.makedirs(data_dir, exist_ok=True)
    config_file = os.path.join(data_dir, "config.json")
    
    master_qq = str(user_config.get("master_qq", "")).strip()
    api_key = str(user_config.get("api_key", "")).strip()
    api_base = str(user_config.get("api_base", "https://api.deepseek.com/v1")).strip()
    model_name = str(user_config.get("model_name", "deepseek-chat")).strip()
    napcat_port = user_config.get("napcat_port", 3001)

    admins = [int(master_qq)] if master_qq.isdigit() else []
    
    astrbot_cfg = {
        "version": "v3.4.0",
        "provider": {
            "type": "openai",
            "api_key": api_key,
            "api_base": api_base,
            "model": model_name
        },
        "system_prompt": DAFEIYU_PROMPT_V36,
        "admins": admins,
        "whitelist": admins if user_config.get("whitelist_only", True) else [],
        "platforms": [
            {
                "type": "aiocqhttp",
                "enable": True,
                "ws_reverse_url": f"ws://127.0.0.1:{napcat_port}/event",
                "ws_reverse_api_url": f"ws://127.0.0.1:{napcat_port}/api"
            }
        ],
        "web": {
            "host": "0.0.0.0",
            "port": user_config.get("astrbot_port", 6185)
        }
    }
    
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(astrbot_cfg, f, ensure_ascii=False, indent=2)
    return config_file

def generate_napcat_config(install_dir, user_config):
    """
    生成 NapCat 的 OneBot11 反向 WebSocket 配置文件
    """
    napcat_dir = os.path.join(install_dir, "NapCat")
    config_dir = os.path.join(napcat_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    
    bot_qq = str(user_config.get("bot_qq", "")).strip()
    napcat_port = user_config.get("napcat_port", 3001)
    
    # NapCat 支持默认配置或者以 QQ 命名的配置 onebot11_<qq>.json
    config_filenames = ["onebot11.json"]
    if bot_qq:
        config_filenames.append(f"onebot11_{bot_qq}.json")
        
    onebot_cfg = {
        "http": {
            "enable": False,
            "host": "",
            "port": 3000,
            "secret": "",
            "enableHeartList": False,
            "enablePost": False,
            "postUrls": []
        },
        "ws": {
            "enable": True,
            "host": "127.0.0.1",
            "port": napcat_port,
            "secret": ""
        },
        "reverseWs": {
            "enable": True,
            "urls": [
                f"ws://127.0.0.1:{napcat_port}/event",
                f"ws://127.0.0.1:{napcat_port}/api"
            ]
        },
        "GroupLocalTime": {
            "Record": False,
            "RecordList": []
        },
        "debug": False,
        "heartInterval": 30000,
        "messagePostFormat": "array",
        "enableLocalFile2Url": False,
        "musicSignUrl": "",
        "reportSelfMessage": False,
        "token": ""
    }
    
    for filename in config_filenames:
        target_path = os.path.join(config_dir, filename)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(onebot_cfg, f, ensure_ascii=False, indent=2)
            
    return os.path.join(config_dir, config_filenames[0])
