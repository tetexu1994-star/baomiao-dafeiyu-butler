# -*- coding: utf-8 -*-
import base64
import os
import socket
import subprocess
import sys
import threading
import time


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

    def log(self, tag, text):
        if self.log_callback:
            self.log_callback({"tag": tag, "text": text.strip()})

    def status(self):
        with self._lock:
            return {
                "running": self.is_running,
                "astrbot": self.astrbot_proc is not None and self.astrbot_proc.poll() is None,
                "napcat": self.napcat_proc is not None and self.napcat_proc.poll() is None,
            }

    def check_qr_file(self):
        qr_paths = [
            os.path.join(self.install_dir, "NapCat", "qrcode.png"),
            os.path.join(self.install_dir, "NapCat", "config", "qrcode.png"),
        ]
        last_mtimes = {path: 0 for path in qr_paths}
        while self.is_running:
            for path in qr_paths:
                try:
                    mtime = os.path.getmtime(path)
                    if mtime > last_mtimes[path]:
                        last_mtimes[path] = mtime
                        with open(path, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("ascii")
                        if self.qr_callback:
                            self.qr_callback({"type": "base64", "data": f"data:image/png;base64,{b64}"})
                except OSError:
                    pass
            time.sleep(1.5)

    @staticmethod
    def _process_is_alive(proc):
        return proc is not None and proc.poll() is None

    def _astrbot_command(self):
        venv_python = os.path.join(
            self.install_dir,
            "AstrBot",
            ".venv",
            "Scripts" if sys.platform.startswith("win") else "bin",
            "python.exe" if sys.platform.startswith("win") else "python",
        )
        if os.path.exists(venv_python):
            return [venv_python, "-m", "astrbot", "run"], self.install_dir

        astrbot_dir = os.path.join(self.install_dir, "AstrBot")
        for name in ("AstrBot.exe", "astrbot.exe"):
            target = os.path.join(astrbot_dir, name)
            if os.path.exists(target):
                return [target], astrbot_dir
        for name in ("main.py", "run.py"):
            target = os.path.join(astrbot_dir, name)
            if os.path.exists(target):
                return [sys.executable, target], astrbot_dir
        return [sys.executable, "-m", "astrbot", "run"], astrbot_dir

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
        candidates = (
            "napcatwinbootmain.exe",
            "napcat.win32.exe",
            "napcatwinboot.exe",
            "napcat.exe",
            "napcat.bat",
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
            self.log(tag, line)
            if "扫码成功" in line or "登录成功" in line or "Login successful" in line:
                if self.qr_callback:
                    self.qr_callback({"type": "status", "status": "success", "message": "登录成功！大肥鱼已激活！"})
            elif "https://qm.qq.com" in line or "https://ssl.ptlogin2.qq.com" in line:
                for word in line.split():
                    if word.startswith("http") and self.qr_callback:
                        self.qr_callback({"type": "url", "data": word})

    @staticmethod
    def _wait_for_port(port, timeout=30):
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
                return False
            if self.is_running and self._process_is_alive(self.astrbot_proc) and self._process_is_alive(self.napcat_proc):
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

            if not self._wait_for_port(self.onebot_port):
                self.log("AstrBot", f"OneBot 反向 WebSocket 端口 {self.onebot_port} 启动超时")
                self.stop_all()
                return False

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
        self.log("System", "所有服务已停止。")
