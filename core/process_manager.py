# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import threading
import time
import base64

class ProcessManager:
    def __init__(self, install_dir, log_callback=None, qr_callback=None):
        self.install_dir = install_dir
        self.log_callback = log_callback
        self.qr_callback = qr_callback
        self.astrbot_proc = None
        self.napcat_proc = None
        self.is_running = False

    def log(self, tag, text):
        if self.log_callback:
            self.log_callback({"tag": tag, "text": text.strip()})

    def check_qr_file(self):
        """定期检测 NapCat 目录下生成的二维码图片"""
        qr_paths = [
            os.path.join(self.install_dir, "NapCat", "qrcode.png"),
            os.path.join(self.install_dir, "NapCat", "config", "qrcode.png")
        ]
        last_mtime = 0
        while self.is_running:
            for p in qr_paths:
                if os.path.exists(p):
                    try:
                        mtime = os.path.getmtime(p)
                        if mtime > last_mtime:
                            last_mtime = mtime
                            with open(p, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("utf-8")
                                if self.qr_callback:
                                    self.qr_callback({"type": "base64", "data": f"data:image/png;base64,{b64}"})
                    except Exception:
                        pass
            time.sleep(1.5)

    def start_astrbot(self):
        astrbot_dir = os.path.join(self.install_dir, "AstrBot")
        # 寻找可执行文件或启动脚本
        exe_candidates = ["AstrBot.exe", "astrbot.exe", "main.py", "run.bat"]
        exe_path = None
        for c in exe_candidates:
            target = os.path.join(astrbot_dir, c)
            if os.path.exists(target):
                exe_path = target
                break

        if not exe_path:
            self.log("AstrBot", "未找到可执行程序，尝试通过 python 启动...")
            cmd = [sys.executable, "-m", "astrbot"]
        elif exe_path.endswith(".py"):
            cmd = [sys.executable, exe_path]
        else:
            cmd = [exe_path]

        try:
            self.log("AstrBot", f"正在启动 AstrBot 服务...")
            self.astrbot_proc = subprocess.Popen(
                cmd,
                cwd=astrbot_dir if os.path.exists(astrbot_dir) else self.install_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1
            )
            threading.Thread(target=self._stream_output, args=("AstrBot", self.astrbot_proc), daemon=True).start()
            return True
        except Exception as e:
            self.log("AstrBot", f"启动失败: {str(e)}")
            return False

    def start_napcat(self, bot_qq=""):
        napcat_dir = os.path.join(self.install_dir, "NapCat")
        exe_candidates = ["napcat.win32.exe", "napcat.bat", "NapCatWinBoot.exe", "NapCat.exe"]
        exe_path = None
        for c in exe_candidates:
            target = os.path.join(napcat_dir, c)
            if os.path.exists(target):
                exe_path = target
                break

        if not exe_path:
            self.log("NapCat", "未找到 NapCat 可执行程序！")
            return False

        cmd = [exe_path]
        if bot_qq:
            cmd.extend(["-q", str(bot_qq)])

        try:
            self.log("NapCat", f"正在启动 NapCat QQ 服务...")
            self.napcat_proc = subprocess.Popen(
                cmd,
                cwd=napcat_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1
            )
            threading.Thread(target=self._stream_output, args=("NapCat", self.napcat_proc), daemon=True).start()
            return True
        except Exception as e:
            self.log("NapCat", f"启动失败: {str(e)}")
            return False

    def _stream_output(self, tag, proc):
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            self.log(tag, line)
            # 捕获控制台打印的二维码链接或登录成功特征
            if "扫码成功" in line or "登录成功" in line or "Login successful" in line:
                if self.qr_callback:
                    self.qr_callback({"type": "status", "status": "success", "message": "登录成功！大肥鱼已激活！"})
            elif "https://qm.qq.com" in line or "https://ssl.ptlogin2.qq.com" in line:
                # 捕获到二维码 URL
                for word in line.split():
                    if word.startswith("http"):
                        if self.qr_callback:
                            self.qr_callback({"type": "url", "data": word})

    def start_all(self, bot_qq=""):
        self.is_running = True
        t_qr = threading.Thread(target=self.check_qr_file, daemon=True)
        t_qr.start()
        
        ok_astr = self.start_astrbot()
        time.sleep(2)
        ok_nap = self.start_napcat(bot_qq=bot_qq)
        return ok_astr and ok_nap

    def stop_all(self):
        self.is_running = False
        if self.napcat_proc:
            try:
                self.napcat_proc.terminate()
            except Exception:
                pass
            self.napcat_proc = None
        if self.astrbot_proc:
            try:
                self.astrbot_proc.terminate()
            except Exception:
                pass
            self.astrbot_proc = None
        self.log("System", "所有服务已停止。")
