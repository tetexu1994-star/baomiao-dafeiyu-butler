# -*- coding: utf-8 -*-
"""好感度持久化存储：桌面宠物与 QQ 侧共享同一份好感度数据。

数据保存在 ~/.baomiao_dafeiyu/affinity.json，原子写入，线程安全。
"""

import json
import os
import tempfile
import threading

AFFINITY_PATH = os.path.join(os.path.expanduser("~"), ".baomiao_dafeiyu", "affinity.json")
DEFAULT_AFFINITY = 100

_lock = threading.Lock()

# 好感度等级阶梯（与 persona 模块 04 保持一致）
_LEVELS = [
    (1000, "LV5·暴喵真神"),
    (700, "LV4·誓约"),
    (400, "LV3·心动"),
    (200, "LV2·依赖"),
    (0, "LV1·初识"),
]


def affinity_level(score):
    score = int(score)
    for threshold, name in _LEVELS:
        if score >= threshold:
            return name
    return "LV1·初识"


def _read():
    data = {"affinity": DEFAULT_AFFINITY, "master_qq": ""}
    if os.path.exists(AFFINITY_PATH):
        try:
            with open(AFFINITY_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                if isinstance(saved.get("affinity"), int):
                    data["affinity"] = max(0, saved["affinity"])
                if isinstance(saved.get("master_qq"), str):
                    data["master_qq"] = saved["master_qq"]
        except (OSError, ValueError, TypeError):
            pass
    return data


def _write(data):
    config_dir = os.path.dirname(AFFINITY_PATH)
    os.makedirs(config_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="affinity-", suffix=".json", dir=config_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, AFFINITY_PATH)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def load_affinity():
    """读取当前主人好感度分数"""
    with _lock:
        return _read()["affinity"]


def add_affinity(delta):
    """累加好感度并返回新分数"""
    with _lock:
        data = _read()
        data["affinity"] = max(0, data["affinity"] + int(delta))
        _write(data)
        return data["affinity"]


def set_master(master_qq):
    """记录当前主人 QQ（供后续按主人维度扩展好感度）"""
    with _lock:
        data = _read()
        data["master_qq"] = str(master_qq or "")
        _write(data)


def affinity_snapshot():
    """返回 {affinity, level} 快照"""
    with _lock:
        data = _read()
        return {"affinity": data["affinity"], "level": affinity_level(data["affinity"])}
