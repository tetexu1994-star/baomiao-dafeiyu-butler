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
import atexit
import signal
import urllib.request
import urllib.error
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 确保在 Windows 控制台 (GBK / CP936) 下不会因 emoji 导致 UnicodeEncodeError 崩溃
if sys.platform.startswith("win"):
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("baomiao.dafeiyu.butler.v1")
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
llm_ready_state = {"ready": False, "msg": ""}


def _emergency_cleanup():
    """主程序退出守护：确保 NapCat/AstrBot 子进程树被彻底优雅关闭，不留暗鬼僵尸进程"""
    global process_mgr
    try:
        if process_mgr:
            process_mgr.stop_all()
    except Exception:
        pass


atexit.register(_emergency_cleanup)


def _sig_handler(sig, frame):
    sys.exit(0)


try:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _sig_handler)
except Exception:
    pass


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
    elif data.get("status") in ("success", "qq_logged_in"):
        broadcast_event({"type": "login_success", "message": data.get("message", "")})
    elif data.get("status") == "qr_expired":
        broadcast_event({"type": "qr_expired", "message": data.get("message", "二维码已过期，请点击重新扫码换号")})
    elif data.get("status") == "failed":
        broadcast_event({"type": "service_error", "message": data.get("message", "")})


def test_llm_connection(config):
    """实测一次 LLM API 连通性，返回 (ok, message)。"""
    provider = str(config.get("api_provider", "deepseek")).strip()
    api_base = str(config.get("api_base", "")).strip().rstrip("/")
    if not api_base:
        if provider == "baomiao":
            api_base = "https://open-ai.baomiao.cn/v1"
        else:
            api_base = "https://api.deepseek.com/v1"
    api_key = str(config.get("api_key", "")).strip()
    model = str(config.get("model_name") or "deepseek-flash").strip()

    if not api_key or api_key == "bm-free-token":
        return False, "未配置有效的 API Key，请填写真实 Key 后重试"

    # 针对官方 deepseek.com 与暴喵网关做严格精准模型绑定
    if "deepseek.com" in api_base.lower() or provider == "deepseek":
        model = "deepseek-flash"
    elif "baomiao" in api_base.lower() or provider == "baomiao":
        model = "DeepSeek-V4.1-Flash 1017(1.20x)"
    else:
        model = str(config.get("model_name") or "deepseek-flash").strip()
    config["model_name"] = model

    url = f"{api_base}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "你好"}],
        "max_tokens": 8,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "BaomiaoButler/1.3",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            choices = data.get("choices") or []
            return True, f"LLM API 连通正常（{provider} / {model}）"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        # 兼容全名与简写自动无感回退切换
        if e.code == 400 and ("supported API model names" in detail or "invalid_request_error" in detail):
            alt_model = "deepseek-flash" if "1017" in model else "DeepSeek-V4.1-Flash 1017(1.20x)"
            alt_payload = json.dumps({
                "model": alt_model,
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 8,
                "stream": False,
            }).encode("utf-8")
            alt_req = urllib.request.Request(
                url,
                data=alt_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "BaomiaoButler/1.3",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(alt_req, timeout=20) as alt_resp:
                    config["model_name"] = alt_model
                    with config_lock:
                        user_config["model_name"] = alt_model
                        save_user_config(user_config)
                    return True, f"LLM API 连通正常（已智能适配：{alt_model}）"
            except Exception:
                pass
        if e.code in (401, 403):
            return False, f"LLM API 鉴权失败（HTTP {e.code}），请检查 API Key"
        if e.code == 404:
            return False, f"LLM API 接口不存在（HTTP 404），请检查 API 请求地址：{api_base}"
        return False, f"LLM API 返回 HTTP {e.code}：{detail}"
    except Exception as e:
        return False, f"LLM API 请求失败：{e}"


def fetch_available_models(api_base, api_key):
    """通过 API Key 从 upstream 真实拉取确定可用的模型列表（专注 Flash 极速模型）"""
    api_base = str(api_base or "").strip().rstrip("/")
    api_key = str(api_key or "").strip()
    fallback = [
        {"id": "DeepSeek-V4.1-Flash 1017(1.20x)", "name": "DeepSeek-V4.1-Flash 1017(1.20x)"},
    ]
    if not api_base or not api_key:
        return fallback

    url = f"{api_base}/models"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "BaomiaoButler/1.3",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            raw_models = data.get("data") or []
            models = []
            seen = set()
            for item in raw_models:
                if isinstance(item, dict) and "id" in item:
                    mid = str(item["id"]).strip()
                    mname = str(item.get("name") or mid).strip()
                    if mid and mid not in seen:
                        seen.add(mid)
                        models.append({"id": mid, "name": mname})
                elif isinstance(item, str):
                    mid = item.strip()
                    if mid and mid not in seen:
                        seen.add(mid)
                        models.append({"id": mid, "name": mid})
            # 严格筛选 Flash 系列极速模型，免除多余干扰
            flash_only = [m for m in models if "flash" in m["id"].lower() or "1017" in m["id"]]
            if not any("1017" in m["id"] for m in flash_only):
                flash_only.insert(0, {"id": "DeepSeek-V4.1-Flash 1017(1.20x)", "name": "DeepSeek-V4.1-Flash 1017(1.20x)"})
            return flash_only if flash_only else fallback
    except Exception:
        return fallback


def pick_best_model(models, preferred="DeepSeek-V4.1-Flash 1017(1.20x)"):
    if not models:
        return preferred
    model_ids = [m["id"] if isinstance(m, dict) else str(m) for m in models]
    for mid in model_ids:
        if mid.lower() == preferred.lower():
            return mid
    for mid in model_ids:
        if "1017" in mid:
            return mid
    for mid in model_ids:
        if "flash" in mid.lower():
            return mid
    for mid in model_ids:
        if "deepseek" in mid.lower():
            return mid
    return model_ids[0]


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
            return "API Key 不能为空（若使用暴喵通道请填入暴喵 Key 或下载暴喵 AI 管家）"
    elif master_qq and (not master_qq.isdigit() or len(master_qq) > 12):
        return "主人大号 QQ 格式错误"
    elif bot_qq and (not bot_qq.isdigit() or len(bot_qq) > 12):
        return "机器人小号 QQ 格式错误"

    if api_provider not in {"baomiao", "deepseek"}:
        return "当前仅支持暴喵专属免配通道或 DeepSeek 官方接口"
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

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _is_local_request(self):
        client_ip = getattr(self, "client_address", [None])[0]
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            return False
        host = (self.headers.get("Host") or "").lower().split(":")[0]
        if host and host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                origin_host = urlparse(origin).hostname
            except Exception:
                return False
            if origin_host not in ("127.0.0.1", "localhost", "::1"):
                return False
        return True

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
        elif parsed.path == "/api/qrcode":
            qr_data = process_mgr.last_qr if process_mgr else None
            self._send_json({"success": bool(qr_data), "data": qr_data or ""})
        elif parsed.path == "/api/open_browser":
            query = parse_qs(parsed.query)
            target_url = query.get("url", ["https://ai.baomiao.cn/"])[0]
            if target_url.startswith("https://") or target_url.startswith("http://"):
                try:
                    import webbrowser
                    webbrowser.open(target_url)
                except Exception:
                    pass
            self._send_json({"success": True})
        elif parsed.path == "/api/service/status":
            is_qq_logged_in = bool(process_mgr and process_mgr.is_logged_in)
            is_onebot_connected = bool(process_mgr and process_mgr.is_onebot_connected())
            has_qr = bool(process_mgr and process_mgr.last_qr)
            is_chat_ready = bool(is_qq_logged_in and is_onebot_connected and llm_ready_state.get("ready"))
            log_dir = getattr(process_mgr, "log_dir", "") if process_mgr else os.path.join(user_config.get("install_dir", ""), "logs")
            self._send_json({
                "success": True,
                "running": process_mgr.is_running if process_mgr else False,
                "is_logged_in": is_qq_logged_in,
                "is_onebot_connected": is_onebot_connected,
                "is_chat_ready": is_chat_ready,
                "has_qr": has_qr,
                "qr_data": process_mgr.last_qr if process_mgr else "",
                "log_dir": log_dir,
            })
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
        elif parsed.path == "/api/open_log_dir":
            with config_lock:
                install_dir = user_config.get("install_dir") or DEFAULT_CONFIG["install_dir"]
            log_dir = os.path.join(install_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(log_dir)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", log_dir])
                else:
                    subprocess.Popen(["xdg-open", log_dir])
                self._send_json({"success": True, "log_dir": log_dir})
            except Exception as e:
                self._send_json({"success": False, "message": str(e), "log_dir": log_dir})

        elif parsed.path == "/api/fetch_models":
            query = parse_qs(parsed.query)
            with config_lock:
                cfg_base = user_config.get("api_base", "")
                cfg_key = user_config.get("api_key", "")
                current_model = user_config.get("model_name") or "deepseek-flash"
            api_base = query.get("api_base", [cfg_base])[0]
            api_key = query.get("api_key", [cfg_key])[0]
            models = fetch_available_models(api_base, api_key)
            selected = current_model if any(m["id"] == current_model for m in models) else pick_best_model(models)
            self._send_json({"success": True, "models": models, "selected": selected})
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
                if ok:
                    def _run_llm_test(snapshot):
                        global llm_ready_state
                        time.sleep(2)
                        llm_ok, llm_msg = test_llm_connection(snapshot)
                        llm_ready_state["ready"] = llm_ok
                        llm_ready_state["msg"] = llm_msg
                        broadcast_event({"type": "llm_test", "success": llm_ok, "message": llm_msg})
                    threading.Thread(target=_run_llm_test, args=(config_snapshot,), daemon=True).start()
                self._send_json({"success": ok, "message": "" if ok else "服务启动失败，请查看日志"})
            except Exception as exc:
                self._send_json({"success": False, "message": str(exc)}, 400)

        elif parsed.path == "/api/stop":
            llm_ready_state["ready"] = False
            if process_mgr:
                process_mgr.stop_all()
            self._send_json({"success": True})

        elif parsed.path == "/api/unbind_master":
            with config_lock:
                user_config["master_qq"] = ""
                save_user_config(user_config)
                config_snapshot = dict(user_config)
            install_dir = config_snapshot.get("install_dir")
            if install_dir:
                try:
                    generate_astrbot_config(install_dir, config_snapshot)
                except Exception:
                    pass
            self._send_json({"success": True, "message": "已成功解除主人绑定，大肥鱼现已恢复自由无主身！"})

        elif parsed.path == "/api/launch_pet":
            # 唤起常驻桌面萌宠 (可直接拖拽、悬浮置顶透明伴侣)
            pet_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop_pet.py")
            desktop_pet_exe = os.path.expandvars(r"%USERPROFILE%\Desktop\大肥鱼桌面宠物.exe")
            local_pet_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "大肥鱼桌面宠物.exe")
            launched = False
            launch_msg = ""
            try:
                if os.path.isfile(desktop_pet_exe):
                    subprocess.Popen([desktop_pet_exe], close_fds=True)
                    launched = True
                    launch_msg = "已唤起桌面宠物程序！"
                elif os.path.isfile(local_pet_exe):
                    subprocess.Popen([local_pet_exe], close_fds=True)
                    launched = True
                    launch_msg = "已唤起桌面宠物程序！"
                elif os.path.isfile(pet_script):
                    subprocess.Popen([sys.executable, pet_script], close_fds=True)
                    launched = True
                    launch_msg = "已唤起桌面宠物服务！"
                else:
                    launch_msg = "未找到 desktop_pet.py 或桌面宠物可执行文件"
            except Exception as e:
                self._send_json({"success": False, "message": f"启动桌面宠物失败: {e}"})
                return
            self._send_json({"success": launched, "message": launch_msg})

        elif parsed.path == "/api/relogin":
            body = self._read_json_body() or {}
            new_bot_qq = str(body.get("bot_qq", "")).strip()
            with config_lock:
                if new_bot_qq and new_bot_qq != user_config.get("bot_qq"):
                    user_config["bot_qq"] = new_bot_qq
                    save_user_config(user_config)
                config_snapshot = dict(user_config)
            error = validate_config(config_snapshot, require_complete=True)
            if error:
                self._send_json({"success": False, "message": error}, 400)
                return
            install_dir = config_snapshot["install_dir"]
            try:
                generate_astrbot_config(install_dir, config_snapshot)
                generate_napcat_config(install_dir, config_snapshot)
                if process_mgr:
                    process_mgr.stop_all()
                    process_mgr.clean_session()
                else:
                    process_mgr = ProcessManager(
                        install_dir,
                        onebot_port=int(config_snapshot.get("napcat_port", 6199)),
                        log_callback=on_process_log,
                        qr_callback=on_qr_event,
                    )
                    process_mgr.clean_session()
                ok = process_mgr.start_all(bot_qq=config_snapshot.get("bot_qq", ""))
                self._send_json({"success": ok, "message": "" if ok else "重新启动失败", "bot_qq": config_snapshot.get("bot_qq", "")})
            except Exception as exc:
                self._send_json({"success": False, "message": str(exc)}, 400)

        elif parsed.path == "/api/open_log_dir":
            with config_lock:
                install_dir = user_config.get("install_dir") or DEFAULT_CONFIG["install_dir"]
            log_dir = os.path.join(install_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(log_dir)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", log_dir])
                else:
                    subprocess.Popen(["xdg-open", log_dir])
                self._send_json({"success": True, "log_dir": log_dir})
            except Exception as e:
                self._send_json({"success": False, "message": str(e), "log_dir": log_dir})

        elif parsed.path == "/api/fetch_models":
            with config_lock:
                cfg_base = user_config.get("api_base", "")
                cfg_key = user_config.get("api_key", "")
                current_model = user_config.get("model_name") or "deepseek-flash"
            api_base = body.get("api_base") or cfg_base or "https://api.deepseek.com/v1"
            api_key = body.get("api_key") or cfg_key or ""
            models = fetch_available_models(api_base, api_key)
            selected = current_model if any(m["id"] == current_model for m in models) else pick_best_model(models)
            self._send_json({"success": True, "models": models, "selected": selected})

        else:
            self._send_json({"success": False, "message": "接口不存在"}, 404)

    def do_OPTIONS(self):
        if not self._is_local_request():
            self._reject_local()
            return
        self._send_json({"success": False, "message": "不支持跨域请求"}, 405)


def _existing_instance_at(port):
    """探测指定端口是否已运行本程序的实例"""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/install/status",
            headers={"User-Agent": "BaomiaoButler/1.3"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("success") is True
    except Exception:
        return False


def start_server(port=18999):
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), ButlerHTTPHandler)
    except OSError:
        if port == 0:
            raise
        if _existing_instance_at(port):
            return None
        server = ThreadingHTTPServer(("127.0.0.1", 0), ButlerHTTPHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    server = start_server(18999)
    if server is None:
        print("[系统] 检测到大肥鱼管家已在运行，正在打开现有窗口...")
        webbrowser.open("http://127.0.0.1:18999")
        return
    port = server.server_port
    url = f"http://127.0.0.1:{port}"
    print(f"[一键安装] 本地控制台已启动: {url}")

    # 优先启动原生独立桌面小工具窗口 (pywebview / Edge WebView2)
    use_webview = False
    try:
        import webview
        use_webview = True
    except Exception:
        pass

    if use_webview:
        try:
            print("[大肥鱼一键接入QQ] 正在唤起原生桌面窗口...")
            window = webview.create_window(
                title="大肥鱼一键接入QQ",
                url=url,
                width=1040,
                height=850,
                resizable=True,
                min_size=(920, 680)
            )
            def _apply_windows_icon():
                if not sys.platform.startswith("win"):
                    return
                import ctypes
                candidates = [
                    os.path.join(getattr(sys, "_MEIPASS", ""), "dafeiyu.ico"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dafeiyu.ico"),
                    os.path.join(getattr(sys, "_MEIPASS", ""), "web", "favicon.ico"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "favicon.ico"),
                ]
                icon_path = next((p for p in candidates if os.path.isfile(p)), None)
                if not icon_path:
                    return
                for _ in range(40):
                    time.sleep(0.25)
                    hwnd = ctypes.windll.user32.FindWindowW(None, "大肥鱼一键接入QQ")
                    if hwnd:
                        try:
                            IMAGE_ICON = 1
                            LR_LOADFROMFILE = 0x00000010
                            hicon_big = ctypes.windll.user32.LoadImageW(None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
                            hicon_small = ctypes.windll.user32.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
                            WM_SETICON = 0x0080
                            if hicon_big:
                                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)
                            if hicon_small:
                                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)
                            break
                        except Exception:
                            pass

            threading.Thread(target=_apply_windows_icon, daemon=True).start()
            webview.start()
            if process_mgr:
                process_mgr.stop_all()
            server.shutdown()
            print("[系统] 原生窗口已关闭，大肥鱼一键接入工具安全退出。")
            return
        except Exception as e:
            print(f"[提示] 原生窗口拉起失败，回退至浏览器: {e}")

    # 回退：使用系统浏览器打开
    time.sleep(0.5)
    webbrowser.open(url)

    print("==================================================")
    print(" [大肥鱼一键接入QQ] 已在桌面浏览器运行")
    print(" 如未自动弹出窗口，请手动访问: " + url)
    print(" 按 Ctrl + C 可退出服务")
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
