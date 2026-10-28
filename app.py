# -*- coding: utf-8 -*-
"""
暴喵大肥鱼一键管家 · 主程序入口
支持直接运行，或通过 PyInstaller 打包成单文件 .exe
"""

import os
import sys
import json
import time
import queue
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

# 导入核心模块
from core.config import load_user_config, save_user_config
from core.generator import generate_astrbot_config, generate_napcat_config
from core.downloader import ComponentDownloader
from core.process_manager import ProcessManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

# 全局事件队列，用于 Server-Sent Events (SSE) 推送
event_queue = queue.Queue()
user_config = load_user_config()
downloader = None
process_mgr = None

def broadcast_event(event_dict):
    try:
        event_queue.put_nowait(json.dumps(event_dict, ensure_ascii=False))
    except Exception:
        pass

def on_download_progress(data):
    broadcast_event({
        "type": "progress",
        "message": data.get("message"),
        "progress": data.get("progress")
    })
    broadcast_event({
        "type": "log",
        "tag": "下载部署",
        "text": data.get("message")
    })

def on_process_log(data):
    broadcast_event({
        "type": "log",
        "tag": data.get("tag", "System"),
        "text": data.get("text", "")
    })

def on_qr_event(data):
    if data.get("type") in ("base64", "url"):
        broadcast_event({
            "type": "qr",
            "data": data.get("data")
        })
    elif data.get("status") == "success":
        broadcast_event({
            "type": "login_success"
        })

class ButlerHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(user_config, ensure_ascii=False).encode("utf-8"))
        elif parsed.path == "/api/events":
            # Server-Sent Events (SSE) 长连接
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            while True:
                try:
                    data = event_queue.get(timeout=20)
                    msg = f"data: {data}\n\n"
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # 发送心跳保活
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                except Exception:
                    break
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        
        response_data = {"success": True}
        
        if parsed.path == "/api/config":
            try:
                data = json.loads(body)
                user_config.update(data)
                save_user_config(user_config)
                response_data = {"success": True, "config": user_config}
            except Exception as e:
                response_data = {"success": False, "message": str(e)}

        elif parsed.path == "/api/install":
            global downloader
            install_dir = user_config.get("install_dir")
            downloader = ComponentDownloader(install_dir, status_callback=on_download_progress)
            
            def run_install():
                success = downloader.start_setup()
                if success:
                    # 生成 AstrBot 与 NapCat 配置文件
                    generate_astrbot_config(install_dir, user_config)
                    generate_napcat_config(install_dir, user_config)
                    on_download_progress({"message": "✅ 配置文件写入与人设注入完成！", "progress": 100})
            
            threading.Thread(target=run_install, daemon=True).start()
            response_data = {"success": True, "message": "部署任务已在后台启动"}

        elif parsed.path == "/api/start":
            global process_mgr
            install_dir = user_config.get("install_dir")
            # 确保最新配置写入
            generate_astrbot_config(install_dir, user_config)
            generate_napcat_config(install_dir, user_config)
            
            if process_mgr is None:
                process_mgr = ProcessManager(install_dir, log_callback=on_process_log, qr_callback=on_qr_event)
            
            bot_qq = user_config.get("bot_qq", "")
            ok = process_mgr.start_all(bot_qq=bot_qq)
            response_data = {"success": ok}

        elif parsed.path == "/api/stop":
            if process_mgr:
                process_mgr.stop_all()
            response_data = {"success": True}

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode("utf-8"))

def start_server(port=18999):
    server = ThreadingHTTPServer(("127.0.0.1", port), ButlerHTTPHandler)
    print(f"[暴喵大肥鱼一键管家] 本地控制台已启动: http://127.0.0.1:{port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

def main():
    port = 18999
    start_server(port)
    url = f"http://127.0.0.1:{port}"
    
    # 尝试在桌面打开浏览器窗口
    time.sleep(0.5)
    webbrowser.open(url)
    
    print("==================================================")
    print(" 🐋 暴喵大肥鱼一键管家 · 已在桌面浏览器运行")
    print(" 如未自动弹出窗口，请手动访问: " + url)
    print(" 按 Ctrl + C 可退出管家服务")
    print("==================================================")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if process_mgr:
            process_mgr.stop_all()
        print("\n[系统] 管家已安全退出。")

if __name__ == "__main__":
    main()
