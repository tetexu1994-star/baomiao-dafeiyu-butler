# -*- coding: utf-8 -*-
"""
大肥鱼桌面萌宠 (Cyber Desktop Pet)
轻量、透明、无边框、可拖拽的桌面常驻二次元陪伴萌宠
支持直接对话 DeepSeek、傲娇交互、投喂大白饭、形态切换
"""

import os
import sys
import json
import urllib.request
import urllib.error
import threading
import time

try:
    import webview
except ImportError:
    webview = None

from core.config import load_user_config
from core.persona import DAFEIYU_PROMPT_MAX
from core import affinity

PET_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "pet.html")


class DesktopPetAPI:
    def __init__(self):
        self.window = None
        self.config = load_user_config()
        self.chat_history = []
        self.mode = "loli"  # loli / elder / battle
        self.affinity = affinity.load_affinity()

    def set_window(self, window):
        self.window = window

    def get_init_data(self):
        self.config = load_user_config()
        return {
            "mode": self.mode,
            "affinity": self.affinity,
            "level": affinity.affinity_level(self.affinity),
            "has_api_key": bool(self.config.get("api_key", "").strip()) and self.config.get("api_key", "").strip() != "bm-free-token",
            "master_qq": self.config.get("master_qq", ""),
        }

    def feed_food(self):
        self.affinity = affinity.add_affinity(10)
        return {
            "success": True,
            "affinity": self.affinity,
            "level": affinity.affinity_level(self.affinity),
            "reply": "嗷呜！大白饭真香～(鼓起腮帮子嚼嚼) 谢谢主人投喂，好感度 +10 喵！🍚✨"
        }

    def set_mode(self, mode):
        self.mode = mode
        replies = {
            "elder": "变大好了。(挑眉浅笑) 小家伙，今天需要姐姐帮你做什么？",
            "loli": "变小啦～(扑进怀里) 还是小小只最舒服了，主人摸摸头喵！",
            "battle": "满血战斗军师态已就绪！DeepSeek-R1 算力全开，随时执行复杂推理与代码任务。"
        }
        return {
            "mode": self.mode,
            "reply": replies.get(mode, "形态已切换！")
        }

    def chat(self, user_text):
        user_text = str(user_text).strip()
        if not user_text:
            return {"reply": "主人怎么什么都没说呀？(歪头)"}

        # 本地快捷响应彩蛋
        lower_txt = user_text.lower()
        if "变大" in user_text:
            return self.set_mode("elder")
        if "变小" in user_text:
            return self.set_mode("loli")
        if "暴走" in user_text or "军师" in user_text:
            return self.set_mode("battle")
        if "投喂" in user_text or user_text == "🍚":
            return self.feed_food()
        if "好感" in user_text:
            return {"reply": f"当前好感度为 【{self.affinity} 点 · {affinity.affinity_level(self.affinity)}】！大肥鱼正全力守护主人喵～✨"}

        self.config = load_user_config()
        api_key = self.config.get("api_key", "").strip()
        api_base = self.config.get("api_base", "https://api.deepseek.com/v1").rstrip("/")
        model_name = self.config.get("model_name", "deepseek-chat")

        if not api_key or api_key == "bm-free-token":
            return {
                "reply": "主人还没有配置可用的 API Key 呢喵～请右键点击本鱼选择【打开领养舱】填一下 Key 就能畅聊啦！"
            }

        # 调用 DeepSeek API
        try:
            self.chat_history.append({"role": "user", "content": user_text})
            # 保留最近 8 轮历史
            if len(self.chat_history) > 16:
                self.chat_history = self.chat_history[-16:]

            messages = [{"role": "system", "content": DAFEIYU_PROMPT_MAX}] + self.chat_history

            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.85,
                "max_tokens": 150 if self.mode != "battle" else 800,
            }

            req = urllib.request.Request(
                f"{api_base}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "Baomiao-DaFeiYu-DesktopPet/1.0",
                },
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply_content = data["choices"][0]["message"]["content"].strip()
                # 过滤可能存在的前置隐形标记
                if reply_content.startswith("✦") and "✦" in reply_content[1:]:
                    reply_content = reply_content.split("✦", 2)[-1].strip()
                self.chat_history.append({"role": "assistant", "content": reply_content})
                self.affinity = affinity.add_affinity(2)
                return {"reply": reply_content, "affinity": self.affinity, "level": affinity.affinity_level(self.affinity)}

        except Exception as exc:
            return {"reply": f"呜…网络开小差了喵：{exc}"}

    def open_main_app(self):
        """唤起主领养舱程序"""
        try:
            import subprocess
            app_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
            if os.path.exists(app_py):
                subprocess.Popen([sys.executable, app_py], close_fds=True)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def close_pet(self):
        if self.window:
            self.window.destroy()

    def set_on_top(self, on_top):
        if self.window:
            self.window.on_top = bool(on_top)
        return {"on_top": bool(on_top)}


def launch_pet():
    if not webview:
        print("[错误] 未安装 pywebview，无法启动桌面萌宠！")
        return

    api = DesktopPetAPI()

    # 计算右下角位置 (避开任务栏)
    init_x = 1000
    init_y = 500
    try:
        screens = webview.screens
        if screens:
            primary = screens[0]
            init_x = max(100, primary.width - 320)
            init_y = max(100, primary.height - 440)
    except Exception:
        pass

    window = webview.create_window(
        title="大肥鱼桌面萌宠",
        url=f"file://{PET_HTML_PATH}" if os.path.exists(PET_HTML_PATH) else "about:blank",
        width=290,
        height=380,
        x=init_x,
        y=init_y,
        resizable=False,
        frameless=True,
        transparent=True,
        on_top=True,
        js_api=api,
    )
    api.set_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    launch_pet()
