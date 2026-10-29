# -*- coding: utf-8 -*-
import base64
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Optional


def _silent_kwargs():
    """在 Windows 下完全静默执行，禁止弹出任何黑框控制台窗口"""
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return {
            "startupinfo": si,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    return {}


class ProcessManager:
    def __init__(self, install_dir, onebot_port=6199, log_callback=None, qr_callback=None):
        self.install_dir = os.path.abspath(install_dir)
        self.onebot_port = int(onebot_port)
        self.log_callback = log_callback
        self.qr_callback = qr_callback
        self.astrbot_proc = None
        self.napcat_proc = None
        self.is_running = False
        self._starting = False
        self._lock = threading.RLock()
        self._qr_thread = None
        self.last_qr = None
        self.is_logged_in = False
        self._onebot_cache = (0.0, False)

    def is_onebot_connected(self):
        """检查 NapCat 与 AstrBot 之间的 OneBot 11 反向 WebSocket 是否处于已连接状态（纯静默模式）"""
        now = time.time()
        if now - self._onebot_cache[0] < 3.0:
            return self._onebot_cache[1]
        result = False
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                **_silent_kwargs()
            )
            target_port = f":{self.onebot_port}"
            for line in out.splitlines():
                if target_port in line and "ESTABLISHED" in line:
                    result = True
                    break
        except Exception:
            pass
        self.is_logged_in = result
        self._onebot_cache = (now, result)
        return result

    def log(self, tag, text):
        if self.log_callback:
            self.log_callback({"tag": tag, "text": text.strip()})

    def status(self):
        with self._lock:
            connected = self.is_onebot_connected()
            return {
                "running": self.is_running,
                "astrbot": self.astrbot_proc is not None and self.astrbot_proc.poll() is None,
                "napcat": self.napcat_proc is not None and self.napcat_proc.poll() is None,
                "has_qr": bool(self.last_qr),
                "is_logged_in": connected,
            }

    def _clean_old_qr(self):
        """清理历史二维码，确保扫码使用的是最新生成的"""
        napcat_dir = os.path.join(self.install_dir, "NapCat")
        if not os.path.isdir(napcat_dir):
            return
        candidate_paths = [
            os.path.join(napcat_dir, "napcat", "cache", "qrcode.png"),
            os.path.join(napcat_dir, "cache", "qrcode.png"),
            os.path.join(napcat_dir, "qrcode.png"),
            os.path.join(napcat_dir, "config", "qrcode.png"),
        ]
        for p in candidate_paths:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass

    def clean_session(self):
        """清理 NapCat 登录凭证与缓存，强制下次必须重新扫码"""
        napcat_dir = os.path.join(self.install_dir, "NapCat")
        self._clean_old_qr()
        for cdir in (
            os.path.join(napcat_dir, "napcat", "cache"),
            os.path.join(napcat_dir, "cache"),
        ):
            if os.path.isdir(cdir):
                try:
                    shutil.rmtree(cdir, ignore_errors=True)
                except Exception:
                    pass
        # 清除 protocol 缓存凭证，防止旧 Session 锁定
        for cfg_dir in (
            os.path.join(napcat_dir, "napcat", "config"),
            os.path.join(napcat_dir, "config"),
        ):
            if os.path.isdir(cfg_dir):
                for f in os.listdir(cfg_dir):
                    if "protocol" in f.lower() or "cache" in f.lower():
                        try:
                            os.remove(os.path.join(cfg_dir, f))
                        except Exception:
                            pass
        self.is_logged_in = False
        self.last_qr = None

    def check_qr_file(self):
        napcat_dir = os.path.join(self.install_dir, "NapCat")
        last_mtimes = {}
        while self.is_running:
            # 优先检查连接状态：若 NapCat 已经自动快速登录并与 AstrBot 建立了 OneBot 连接，直接触发登录成功
            if self.is_onebot_connected():
                if not self.is_logged_in:
                    self.is_logged_in = True
                    if self.qr_callback:
                        self.qr_callback({"type": "status", "status": "success", "message": "大肥鱼已在线（自动快速登录成功）！"})
                time.sleep(1.5)
                continue

            candidate_paths = [
                os.path.join(napcat_dir, "napcat", "cache", "qrcode.png"),
                os.path.join(napcat_dir, "cache", "qrcode.png"),
                os.path.join(napcat_dir, "qrcode.png"),
                os.path.join(napcat_dir, "config", "qrcode.png"),
            ]
            if os.path.isdir(napcat_dir):
                for root, _, files in os.walk(napcat_dir):
                    for f in files:
                        if "qrcode" in f.lower() and f.lower().endswith(".png"):
                            candidate_paths.append(os.path.join(root, f))

            for path in set(candidate_paths):
                try:
                    if not os.path.isfile(path):
                        continue
                    mtime = os.path.getmtime(path)
                    if mtime > last_mtimes.get(path, 0):
                        last_mtimes[path] = mtime
                        with open(path, "rb") as f:
                            content = f.read()
                        if len(content) > 100 and content.startswith(b"\x89PNG"):
                            b64 = base64.b64encode(content).decode("ascii")
                            qr_data = f"data:image/png;base64,{b64}"
                            self.last_qr = qr_data
                            if self.qr_callback:
                                self.qr_callback({"type": "base64", "data": qr_data})
                except OSError:
                    pass
            time.sleep(1.0)

    @staticmethod
    def _process_is_alive(proc):
        return proc is not None and proc.poll() is None

    @staticmethod
    def _kill_tree(proc):
        """终止进程及其子进程树，避免 cmd/bat 包装启动时残留孤儿进程"""
        if proc is None or not ProcessManager._process_is_alive(proc):
            return
        pid = proc.pid
        if sys.platform.startswith("win"):
            # 先按进程树整棵终止（覆盖 cmd/bat 包装出的子进程），再走常规 terminate 兜底
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                    **_silent_kwargs(),
                )
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
        if ProcessManager._process_is_alive(proc):
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    def _astrbot_command(self):
        astrbot_dir = os.path.join(self.install_dir, "AstrBot")
        # 1. 优先检查虚拟环境中的 Python，并严格验证 import astrbot 成功
        py_candidates = [
            os.path.join(astrbot_dir, ".venv", "python.exe"),
            os.path.join(astrbot_dir, ".venv", "Scripts" if sys.platform.startswith("win") else "bin", "python.exe" if sys.platform.startswith("win") else "python"),
        ]
        for p in py_candidates:
            if os.path.isfile(p):
                try:
                    res = subprocess.run([p, "-c", "import astrbot"], capture_output=True, timeout=5)
                    if res.returncode == 0:
                        return [p, "-m", "astrbot.cli", "run"], astrbot_dir
                except Exception:
                    pass

        # 2. 检查原生 astrbot.exe
        exe_candidates = [
            os.path.join(astrbot_dir, "runtime", "Scripts", "astrbot.exe"),
            os.path.join(astrbot_dir, "Scripts", "astrbot.exe"),
            os.path.join(astrbot_dir, "AstrBot.exe"),
            os.path.join(astrbot_dir, "astrbot.exe"),
            r"C:\Users\qeeyou\Python312\Scripts\astrbot.exe",
            os.path.expandvars(r"%USERPROFILE%\Python312\Scripts\astrbot.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\Scripts\astrbot.exe"),
            r"C:\Python312\Scripts\astrbot.exe",
        ]
        for p in exe_candidates:
            if os.path.isfile(p):
                try:
                    res = subprocess.run([p, "--version"], capture_output=True, timeout=5)
                    if res.returncode == 0:
                        return [p, "run"], astrbot_dir
                except Exception:
                    pass

        which_astr = shutil.which("astrbot")
        if which_astr:
            return [which_astr, "run"], astrbot_dir

        for name in ("main.py", "run.py"):
            target = os.path.join(astrbot_dir, name)
            if os.path.exists(target):
                return [sys.executable, target], astrbot_dir
        return None, astrbot_dir

    def start_astrbot(self, force_restart=False):
        if self._process_is_alive(self.astrbot_proc):
            if not force_restart:
                return True
            self.log("AstrBot", "正在重启 AstrBot 核心引擎以加载最新模型配置...")
            self._kill_tree(self.astrbot_proc)
            self.astrbot_proc = None
        cmd, cwd = self._astrbot_command()
        if not cmd:
            self.log("AstrBot", "🚀 检测到 AstrBot 核心引擎尚未安装，正在全自动拉取装配...")
            try:
                from .downloader import ComponentDownloader
                downloader = ComponentDownloader(self.install_dir, status_callback=lambda s: self.log("下载部署", s.get("message", "")))
                downloader.install_astrbot()
            except Exception as e:
                self.log("AstrBot", f"❌ 自动装配 AstrBot 失败: {e}")
                return False
            cmd, cwd = self._astrbot_command()
            if not cmd:
                self.log("AstrBot", "❌ 未找到就绪的 AstrBot 引擎，请检查网络后重试")
                return False

        try:
            # 针对 Windows 嵌入式/沙箱 Python 环境，彻底注入 pywintypes/pythoncom 完整依赖
            try:
                from .downloader import ComponentDownloader
                astrbot_dir = os.path.join(self.install_dir, "AstrBot")
                venv_dir = os.path.join(astrbot_dir, ".venv")
                ComponentDownloader.fix_windows_pywin32(venv_dir)
            except Exception:
                pass

            self.log("AstrBot", "正在启动 AstrBot 服务...")
            env = os.environ.copy()
            env["ASTRBOT_ROOT"] = os.path.join(self.install_dir, "AstrBot")
            self.astrbot_proc = subprocess.Popen(
                cmd,
                cwd=cwd if os.path.exists(cwd) else self.install_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
                **_silent_kwargs(),
            )
            threading.Thread(
                target=self._stream_output,
                args=("AstrBot", self.astrbot_proc),
                daemon=True,
            ).start()
            return True
        except Exception as exc:
            self.log("AstrBot", f"启动失败: {exc}")
            return False

    @staticmethod
    def _napcat_command(napcat_dir):
        node_exe = os.path.join(napcat_dir, "node.exe")
        index_js = os.path.join(napcat_dir, "index.js")
        if os.path.isfile(node_exe) and os.path.isfile(index_js):
            return [node_exe, index_js]

        napcat_bat = os.path.join(napcat_dir, "napcat.bat")
        if os.path.isfile(napcat_bat):
            return ["cmd.exe", "/c", napcat_bat] if sys.platform.startswith("win") else [napcat_bat]

        candidates = (
            "napcat.bat",
            "napcat.exe",
            "napcat.win32.exe",
            "napcatwinboot.exe",
            "napcatwinbootmain.exe",
        )
        found = []
        for root, _, files in os.walk(napcat_dir):
            for name in files:
                if name.lower() in candidates:
                    found.append(os.path.join(root, name))
        if not found:
            return None
        found.sort(key=lambda path: candidates.index(os.path.basename(path).lower()))
        exe_path = found[0]
        if exe_path.lower().endswith(".bat") and sys.platform.startswith("win"):
            return ["cmd.exe", "/c", exe_path]
        return [exe_path]

    def start_napcat(self, bot_qq=""):
        if self._process_is_alive(self.napcat_proc):
            return True
        napcat_dir = os.path.join(self.install_dir, "NapCat")
        cmd = self._napcat_command(napcat_dir)
        if not cmd:
            self.log("NapCat", "未找到 NapCat 可执行程序！")
            return False
        if bot_qq:
            cmd = [*cmd, "-q", str(bot_qq)]

        try:
            self._clean_old_qr()
            self.log("NapCat", "正在启动 NapCat QQ 服务...")
            self.napcat_proc = subprocess.Popen(
                cmd,
                cwd=napcat_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
                **_silent_kwargs(),
            )
            threading.Thread(
                target=self._stream_output,
                args=("NapCat", self.napcat_proc),
                daemon=True,
            ).start()
            return True
        except Exception as exc:
            self.log("NapCat", f"启动失败: {exc}")
            return False

    def _stream_output(self, tag, proc):
        if not proc.stdout:
            return
        _reconnect_hint_sent = False
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            clean_line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line).strip()
            if not clean_line:
                continue
            # NapCat 先于 AstrBot 启动时，连 OneBot 端口会短暂 CONNREFUSED，属正常启动过程（会自动重连），过滤噪音
            if tag == "NapCat" and self._is_expected_reconnect_noise(clean_line):
                if not _reconnect_hint_sent:
                    self.log("NapCat", "正在等待 AstrBot 的 OneBot 端口就绪（正常启动过程，会自动重连）...")
                    _reconnect_hint_sent = True
                continue
            self.log(tag, clean_line)
            success_keywords = (
                "扫码成功", "登录成功", "快速登录", "Quick Login",
                "Login successful", "login success", "已登录",
                "自动登录", "OneBot11 适配器初始化完成",
                "aiocqhttp(OneBot v11) 适配器已连接",
                "WebSocket反向服务",
            )
            if any(kw in clean_line for kw in success_keywords):
                self.is_logged_in = True
                if self.qr_callback:
                    self.qr_callback({"type": "status", "status": "qq_logged_in", "message": "QQ 登录成功，正在建立 OneBot 通信并唤醒 AI 对话引擎..."})
            elif "https://qm.qq.com" in clean_line or "https://ssl.ptlogin2.qq.com" in clean_line:
                for word in clean_line.split():
                    if word.startswith("http"):
                        self.last_qr = word
                        if self.qr_callback:
                            self.qr_callback({"type": "url", "data": word})

    @staticmethod
    def _is_expected_reconnect_noise(line):
        markers = (
            "CONNREFUSED", "ECONNREFUSED", "TCPConnectWrap", "afterConnect",
            "连接错误", "重新连接",
        )
        return any(m in line for m in markers)

    @staticmethod
    def _wait_for_port(port, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex(("127.0.0.1", int(port))) == 0:
                    return True
            time.sleep(0.5)
        return False

    def start_all(self, bot_qq="", force_restart_astrbot=True):
        with self._lock:
            if self._starting:
                return True
            if not force_restart_astrbot and self.is_running and self._process_is_alive(self.astrbot_proc) and self._process_is_alive(self.napcat_proc):
                if self.last_qr and self.qr_callback:
                    self.qr_callback({"type": "base64", "data": self.last_qr})
                return True
            self._starting = True

        try:
            self.is_running = True
            if not self._qr_thread or not self._qr_thread.is_alive():
                self._qr_thread = threading.Thread(target=self.check_qr_file, daemon=True)
                self._qr_thread.start()

            # 优化 1：优先秒级启动 NapCat！让扫码二维码在 2~3 秒内立刻渲染到前端界面！
            if not self.start_napcat(bot_qq=bot_qq):
                self.stop_all()
                return False

            # 优化 2：同时拉起 AstrBot AI 核心（带配置强制热重载）
            if not self.start_astrbot(force_restart=force_restart_astrbot):
                self.stop_all()
                return False

            # 优化 3：OneBot 通信端口就绪检测移至后台异步守护线程，完全解耦前端响应！
            def _async_wait_port():
                if not self._wait_for_port(self.onebot_port, timeout=45):
                    if not self._process_is_alive(self.astrbot_proc):
                        code = self.astrbot_proc.poll() if self.astrbot_proc else "未知"
                        self.log("AstrBot", f"AstrBot 进程异常退出 (退出代码 {code})，OneBot 端口 {self.onebot_port} 启动失败")
                        if self.qr_callback:
                            self.qr_callback({"type": "status", "status": "failed", "message": f"AstrBot 服务已退出 (代码 {code})"})
                    else:
                        self.log("AstrBot", f"OneBot 端口 {self.onebot_port} 正在准备中...")
                else:
                    self.log("AstrBot", f"✅ OneBot 反向 WebSocket 已成功就绪并监听端口 {self.onebot_port}")

            threading.Thread(target=_async_wait_port, daemon=True).start()
            return True
        finally:
            self._starting = False

    def stop_all(self):
        with self._lock:
            self.is_running = False
            for name, proc in (("NapCat", self.napcat_proc), ("AstrBot", self.astrbot_proc)):
                if not self._process_is_alive(proc):
                    continue
                self._kill_tree(proc)
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass
                self.log(name, "进程已停止。")
            self.napcat_proc = None
            self.astrbot_proc = None
            self.last_qr = None
            self.is_logged_in = False
        self.log("System", "所有服务已停止。")
