# -*- coding: utf-8 -*-
"""
暴喵大肥鱼一键管家 · 主程序入口
支持直接运行，或通过 PyInstaller 打包成单文件 .exe
"""

import json
import os
import queue
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# 确保在 Windows 控制台 (GBK / CP936) 下不会因 emoji 导致 UnicodeEncodeError 崩溃
if sys.platform.startswith("win"):
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 在 Windows GUI (PyInstaller --windowed) 模式下，stdout 和 stderr 为 None，重定向防止 print 或 log 崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from core.config import load_user_config, public_user_config, save_user_config
from core.downloader import ComponentDownloader
from core.generator import generate_astrbot_config, generate_napcat_config
from core.process_manager import ProcessManager

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_DIR = os.path.join(BASE_DIR, "web")


class EventBroker:
    def __init__(self):
        self._subscribers = set()
        self._lock = threading.Lock()

    def subscribe(self):
        subscriber = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event_dict):
        payload = json.dumps(event_dict, ensure_ascii=False)
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                pass


event_broker = EventBroker()
user_config = load_user_config()
config_lock = threading.Lock()
install_lock = threading.Lock()
install_state = {
    "state": "idle",
    "progress": 0,
    "message": "等待部署",
    "error": "",
}
downloader = None
process_mgr = None


def broadcast_event(event_dict):
    event_broker.publish(event_dict)


def set_install_state(state, message="", progress=None, error=""):
    with install_lock:
        install_state["state"] = state
        install_state["message"] = message or install_state["message"]
        install_state["error"] = error
        if progress is not None:
            install_state["progress"] = max(0, min(100, int(progress)))


def get_install_state():
    with install_lock:
        return dict(install_state)


def on_download_progress(data):
    message = data.get("message", "")
    progress = data.get("progress")
    if get_install_state()["state"] == "running":
        set_install_state("running", message=message, progress=progress)
    broadcast_event({"type": "progress", "message": message, "progress": progress})
    if message:
        broadcast_event({"type": "log", "tag": "下载部署", "text": message})


def on_process_log(data):
    broadcast_event({
        "type": "log",
        "tag": data.get("tag", "System"),
        "text": data.get("text", ""),
    })


def on_qr_event(data):
    if data.get("type") in ("base64", "url"):
        broadcast_event({"type": "qr", "data": data.get("data")})
    elif data.get("status") == "success":
        broadcast_event({"type": "login_success"})


def validate_config(data, require_complete=False):
    if not isinstance(data, dict):
        return "配置格式错误"

    master_qq = str(data.get("master_qq", "")).strip()
    bot_qq = str(data.get("bot_qq", "")).strip()
    api_provider = str(data.get("api_provider", "")).strip()
    api_key = str(data.get("api_key", "")).strip()
    api_base = str(data.get("api_base", "")).strip()
    model_name = str(data.get("model_name", "")).strip()

    if require_complete:
        if not master_qq.isdigit() or len(master_qq) > 12:
            return "主人大号 QQ 格式错误"
        if not bot_qq.isdigit() or len(bot_qq) > 12:
            return "机器人小号 QQ 格式错误"
        if not api_key:
            return "DeepSeek API Key 不能为空"
    elif master_qq and (not master_qq.isdigit() or len(master_qq) > 12):
        return "主人大号 QQ 格式错误"
    elif bot_qq and (not bot_qq.isdigit() or len(bot_qq) > 12):
        return "机器人小号 QQ 格式错误"

    if api_provider not in {"deepseek", "custom"}:
        return "当前版本仅支持 DeepSeek 或自定义 OpenAI 兼容接口"
    if len(api_key) > 512:
        return "API Key 过长"
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "API Base URL 格式错误"
    if len(model_name) > 100:
        return "模型名称过长"
    for key in ("napcat_port", "astrbot_port"):
        try:
            default_port = 6199 if key == "napcat_port" else 6185
            port = int(data.get(key, default_port))
        except (TypeError, ValueError):
            return f"{key} 必须是端口号"
        if not 1 <= port <= 65535:
            return f"{key} 必须在 1-65535 之间"
    return ""


class ButlerHTTPHandler(SimpleHTTPRequestHandler):
    server_version = "BaomiaoButler/1.3"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        # 禁用默认的 stderr 打印，避免在 Windows 无窗口模式 (--windowed) 下抛出 NoneType 错误导致连接重置
        pass

    def _is_local_request(self):
        client_ip = getattr(self, "client_address", [None])[0]
        if client_ip in ("127.0.0.1", "::1", "localhost"):
            return True
        host = (self.headers.get("Host") or "").lower().split(":")[0]
        if host in ("127.0.0.1", "localhost"):
            return True
        return False

    def _send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _reject_local(self):
        self._send_json({"success": False, "message": "仅允许本机访问"}, 403)

    def _read_json_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("Content-Length 无效")
        if content_length > 1024 * 1024:
            raise ValueError("请求体过大")
        content_type = self.headers.get("Content-Type", "")
        if content_length and not content_type.startswith("application/json"):
            raise ValueError("请求体必须使用 application/json")
        body = self.rfile.read(content_length) if content_length > 0 else b""
        return json.loads(body.decode("utf-8")) if body else {}

    def do_GET(self):
        if not self._is_local_request():
            self._reject_local()
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            with config_lock:
                self._send_json(public_user_config(user_config))
        elif parsed.path == "/api/install/status":
            self._send_json({"success": True, **get_install_state()})
        elif parsed.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            subscriber = event_broker.subscribe()
            try:
                while True:
                    try:
                        data = subscriber.get(timeout=20)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                event_broker.unsubscribe(subscriber)
        elif parsed.path.startswith("/api/"):
            self._send_json({"success": False, "message": "接口不存在"}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        if not self._is_local_request():
            self._reject_local()
            return

        global downloader, process_mgr, user_config
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body()
        except Exception as exc:
            self._send_json({"success": False, "message": str(exc)}, 400)
            return

        if parsed.path == "/api/config":
            allowed = {
                "master_qq", "bot_qq", "api_provider", "api_key",
                "api_base", "model_name", "napcat_port", "astrbot_port",
                "auto_launch", "enable_tts", "whitelist_only",
            }
            data = {key: value for key, value in body.items() if key in allowed}
            with config_lock:
                candidate = dict(user_config)
                candidate.update(data)
                error = validate_config(candidate, require_complete=False)
                if not error:
                    user_config = candidate
                    save_user_config(user_config)
            if error:
                self._send_json({"success": False, "message": error}, 400)
            else:
                with config_lock:
                    self._send_json({"success": True, "config": public_user_config(user_config)})

        elif parsed.path == "/api/install":
            if get_install_state()["state"] == "running":
                self._send_json({"success": False, "message": "部署任务正在进行中"}, 409)
                return
            with config_lock:
                config_snapshot = dict(user_config)
            error = validate_config(config_snapshot, require_complete=True)
            if error:
                self._send_json({"success": False, "message": error}, 400)
                return

            install_dir = config_snapshot.get("install_dir")
            downloader = ComponentDownloader(install_dir, status_callback=on_download_progress)
            set_install_state("running", "部署任务已启动", 0)

            def run_install():
                try:
                    if not downloader.start_setup():
                        raise RuntimeError(get_install_state()["message"] or "组件部署失败")
                    generate_astrbot_config(install_dir, config_snapshot)
                    generate_napcat_config(install_dir, config_snapshot)
                    set_install_state("completed", "全部组件与配置已准备完成", 100)
                    broadcast_event({"type": "install_complete"})
                except Exception as exc:
                    set_install_state("failed", "部署失败", error=str(exc))
                    broadcast_event({"type": "log", "tag": "下载部署", "text": f"部署失败: {exc}"})
                    broadcast_event({"type": "install_failed", "message": str(exc)})

            threading.Thread(target=run_install, daemon=True).start()
            self._send_json({"success": True, "message": "部署任务已在后台启动"})

        elif parsed.path == "/api/start":
            with config_lock:
                config_snapshot = dict(user_config)
            error = validate_config(config_snapshot, require_complete=True)
            if error:
                self._send_json({"success": False, "message": error}, 400)
                return
            install_dir = config_snapshot["install_dir"]
            try:
                generate_astrbot_config(install_dir, config_snapshot)
                generate_napcat_config(install_dir, config_snapshot)
                if process_mgr and process_mgr.install_dir != os.path.abspath(install_dir):
                    process_mgr.stop_all()
                    process_mgr = None
                if process_mgr is None:
                    process_mgr = ProcessManager(
                        install_dir,
                        onebot_port=int(config_snapshot.get("napcat_port", 6199)),
                        log_callback=on_process_log,
                        qr_callback=on_qr_event,
                    )
                ok = process_mgr.start_all(bot_qq=config_snapshot.get("bot_qq", ""))
                self._send_json({"success": ok, "message": "" if ok else "服务启动失败，请查看日志"})
            except Exception as exc:
                self._send_json({"success": False, "message": str(exc)}, 400)

        elif parsed.path == "/api/stop":
            if process_mgr:
                process_mgr.stop_all()
            self._send_json({"success": True})

        else:
            self._send_json({"success": False, "message": "接口不存在"}, 404)

    def do_OPTIONS(self):
        if not self._is_local_request():
            self._reject_local()
            return
        self._send_json({"success": False, "message": "不支持跨域请求"}, 405)


def start_server(port=18999):
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), ButlerHTTPHandler)
    except OSError:
        if port == 0:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), ButlerHTTPHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    server = start_server(18999)
    port = server.server_port
    url = f"http://127.0.0.1:{port}"
    print(f"[暴喵大肥鱼一键管家] 本地控制台已启动: {url}")

    # 优先启动原生独立桌面小工具窗口 (pywebview / Edge WebView2)
    use_webview = False
    try:
        import webview
        use_webview = True
    except Exception:
        pass

    if use_webview:
        try:
            print("[暴喵大肥鱼一键管家] 正在唤起原生桌面窗口...")
            window = webview.create_window(
                title="暴喵大肥鱼一键管家",
                url=url,
                width=980,
                height=720,
                resizable=True,
                min_size=(800, 600)
            )
            webview.start()
            if process_mgr:
                process_mgr.stop_all()
            server.shutdown()
            print("[系统] 原生窗口已关闭，管家服务安全退出。")
            return
        except Exception as e:
            print(f"[提示] 原生窗口拉起失败，回退至浏览器: {e}")

    # 回退：使用系统浏览器打开
    time.sleep(0.5)
    webbrowser.open(url)

    print("==================================================")
    print(" [暴喵大肥鱼一键管家] 已在桌面浏览器运行")
    print(" 如未自动弹出窗口，请手动访问: " + url)
    print(" 按 Ctrl + C 可退出管家服务")
    print("==================================================")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if process_mgr:
            process_mgr.stop_all()
        server.shutdown()
        print("\n[系统] 管家已安全退出。")


if __name__ == "__main__":
    main()
