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

    def is_onebot_connected(self):
        """检查 NapCat 与 AstrBot 之间的 OneBot 11 反向 WebSocket 是否处于已连接状态（纯静默模式）"""
        if self.is_logged_in:
            return True
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                errors="ignore",
                **_silent_kwargs()
            )
            target_port = f":{self.onebot_port}"
            for line in out.splitlines():
                if target_port in line and "ESTABLISHED" in line:
                    self.is_logged_in = True
                    return True
        except Exception:
            pass
        return False

    def log(self, tag, text):
        if self.log_callback:
            self.log_callback({"tag": tag, "text": text.strip()})

    def status(self):
        with self._lock:
            return {
                "running": self.is_running,
                "astrbot": self.astrbot_proc is not None and self.astrbot_proc.poll() is None,
                "napcat": self.napcat_proc is not None and self.napcat_proc.poll() is None,
                "has_qr": bool(self.last_qr),
                "is_logged_in": self.is_logged_in or self.is_onebot_connected(),
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

    def _astrbot_command(self):
        astrbot_dir = os.path.join(self.install_dir, "AstrBot")
        candidates = [
            os.path.join(astrbot_dir, "runtime", "Scripts", "astrbot.exe"),
            os.path.join(astrbot_dir, "Scripts", "astrbot.exe"),
            os.path.join(astrbot_dir, "AstrBot.exe"),
            os.path.join(astrbot_dir, "astrbot.exe"),
            r"C:\Users\qeeyou\Python312\Scripts\astrbot.exe",
            os.path.expandvars(r"%USERPROFILE%\Python312\Scripts\astrbot.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\Scripts\astrbot.exe"),
            r"C:\Python312\Scripts\astrbot.exe",
        ]
        for p in candidates:
            if os.path.isfile(p):
                return [p, "run"], astrbot_dir

        venv_python = os.path.join(
            astrbot_dir,
            ".venv",
            "Scripts" if sys.platform.startswith("win") else "bin",
            "python.exe" if sys.platform.startswith("win") else "python",
        )
        if os.path.exists(venv_python):
            return [venv_python, "-m", "astrbot.cli", "run"], astrbot_dir

        which_astr = shutil.which("astrbot")
        if which_astr:
            return [which_astr, "run"], astrbot_dir

        for name in ("main.py", "run.py"):
            target = os.path.join(astrbot_dir, name)
            if os.path.exists(target):
                return [sys.executable, target], astrbot_dir
        return [sys.executable, "-m", "astrbot.cli", "run"], astrbot_dir

    def start_astrbot(self):
        if self._process_is_alive(self.astrbot_proc):
            return True
        cmd, cwd = self._astrbot_command()
        try:
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
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            clean_line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line).strip()
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
                    self.qr_callback({"type": "status", "status": "success", "message": "大肥鱼已激活·在线中！"})
            elif "https://qm.qq.com" in clean_line or "https://ssl.ptlogin2.qq.com" in clean_line:
                for word in clean_line.split():
                    if word.startswith("http"):
                        self.last_qr = word
                        if self.qr_callback:
                            self.qr_callback({"type": "url", "data": word})

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

    def start_all(self, bot_qq=""):
        with self._lock:
            if self._starting:
                return True
            if self.is_running and self._process_is_alive(self.astrbot_proc) and self._process_is_alive(self.napcat_proc):
                if self.last_qr and self.qr_callback:
                    self.qr_callback({"type": "base64", "data": self.last_qr})
                return True
            self._starting = True

        try:
            self.is_running = True
            if not self._qr_thread or not self._qr_thread.is_alive():
                self._qr_thread = threading.Thread(target=self.check_qr_file, daemon=True)
                self._qr_thread.start()

            if not self.start_astrbot():
                self.stop_all()
                return False

            if not self._wait_for_port(self.onebot_port, timeout=45):
                # 检查 AstrBot 进程是否依然存活，如果存活只是端口延迟，给以提示并继续启动 NapCat
                if not self._process_is_alive(self.astrbot_proc):
                    self.log("AstrBot", f"OneBot 反向 WebSocket 端口 {self.onebot_port} 启动失败")
                    self.stop_all()
                    return False
                self.log("AstrBot", f"OneBot 端口 {self.onebot_port} 正在准备中，继续拉起 NapCat...")

            if not self.start_napcat(bot_qq=bot_qq):
                self.stop_all()
                return False
            return True
        finally:
            self._starting = False

    def stop_all(self):
        with self._lock:
            self.is_running = False
            for name, proc in (("NapCat", self.napcat_proc), ("AstrBot", self.astrbot_proc)):
                if not self._process_is_alive(proc):
                    continue
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
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
