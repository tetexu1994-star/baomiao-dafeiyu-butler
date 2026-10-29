# -*- coding: utf-8 -*-
import hashlib
import os
import secrets
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

BAOMIAO_CDN_BASE = os.environ.get("BAOMIAO_CDN_BASE", "https://cdn.baomiao.com/dafeiyu/").strip()
if BAOMIAO_CDN_BASE and not BAOMIAO_CDN_BASE.endswith("/"):
    BAOMIAO_CDN_BASE += "/"

GH_PROXIES = [
    "https://ghfast.top/",
    "https://mirror.ghproxy.com/",
    "https://ghproxy.net/",
    "",
]

NAPCAT_VERSION = "4.18.41"
ASTRBOT_VERSION = "4.29.3"
NAPCAT_FILENAME = "NapCat.Shell.Windows.Node.zip"
NAPCAT_URL = (
    "https://github.com/NapNeko/NapCatQQ/releases/download/"
    f"{NAPCAT_VERSION}/{NAPCAT_FILENAME}"
)
NAPCAT_CDN_URL = f"{BAOMIAO_CDN_BASE}{NAPCAT_FILENAME}"
NAPCAT_SHA256 = "51fbb10e7bcd56b0c2a6de86c37811e7518330e48a137ac689ab1e4d8627d3f0"
MAX_ARCHIVE_SIZE = 512 * 1024 * 1024
MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024


class ComponentDownloader:
    def __init__(self, install_dir, status_callback=None):
        self.install_dir = os.path.abspath(install_dir)
        self.status_callback = status_callback
        self.is_downloading = False
        os.makedirs(self.install_dir, exist_ok=True)

    def log(self, message, progress=None):
        if self.status_callback:
            self.status_callback({"message": message, "progress": progress})

    def download_file(self, raw_url, dest_path, expected_sha256=None):
        urls_to_try = []
        if BAOMIAO_CDN_BASE and raw_url.endswith(NAPCAT_FILENAME):
            urls_to_try.append(("暴喵官方国内高速节点", NAPCAT_CDN_URL))
        for proxy in GH_PROXIES:
            label = f"镜像通道 {proxy}" if proxy else "GitHub 官方直连"
            urls_to_try.append((label, proxy + raw_url if proxy else raw_url))

        for label, target_url in urls_to_try:
            digest = hashlib.sha256()
            try:
                self.log(f"正在连接下载源 ({label})...")
                req = urllib.request.Request(target_url, headers={"User-Agent": "BaomiaoButler/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    total_size = int(resp.headers.get("content-length", 0))
                    if total_size > MAX_ARCHIVE_SIZE:
                        raise ValueError(f"安装包过大: {total_size} bytes")
                    downloaded = 0
                    with open(dest_path, "wb") as f:
                        while True:
                            chunk = resp.read(64 * 1024)
                            if not chunk:
                                break
                            downloaded += len(chunk)
                            if downloaded > MAX_ARCHIVE_SIZE:
                                raise ValueError("安装包超过大小限制")
                            f.write(chunk)
                            digest.update(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 100)
                                self.log(
                                    f"下载进度: {downloaded // (1024 * 1024)}MB / "
                                    f"{total_size // (1024 * 1024)}MB ({pct}%)",
                                    pct,
                                )
                actual_sha256 = digest.hexdigest()
                if expected_sha256 and actual_sha256 != expected_sha256:
                    raise ValueError(f"SHA-256 校验失败: {actual_sha256}")
                return True
            except Exception as exc:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                self.log(f"源 {label} 下载或校验失败: {exc}")
        return False

    @staticmethod
    def _safe_extract_zip(zip_path, extract_to):
        extract_root = os.path.realpath(extract_to)
        os.makedirs(extract_root, exist_ok=True)
        total_size = 0
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for info in zip_ref.infolist():
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"拒绝解压符号链接: {info.filename}")
                total_size += info.file_size
                if total_size > MAX_EXTRACTED_SIZE:
                    raise ValueError("解压内容超过大小限制")
                target_path = os.path.realpath(os.path.join(extract_root, info.filename))
                if os.path.commonpath([extract_root, target_path]) != extract_root:
                    raise ValueError(f"检测到 ZIP 路径穿越: {info.filename}")
            zip_ref.extractall(extract_root)

    def extract_zip(self, zip_path, extract_to):
        self.log(f"正在解压组件到 {os.path.basename(extract_to)}...")
        self._safe_extract_zip(zip_path, extract_to)
        return True

    @staticmethod
    def _find_napcat_command(napcat_dir):
        if not os.path.isdir(napcat_dir):
            return None
        node_exe = os.path.join(napcat_dir, "node.exe")
        index_js = os.path.join(napcat_dir, "index.js")
        if os.path.isfile(node_exe) and os.path.isfile(index_js):
            return [node_exe, index_js]
        napcat_bat = os.path.join(napcat_dir, "napcat.bat")
        if os.path.isfile(napcat_bat):
            return ["cmd.exe", "/c", napcat_bat] if sys.platform.startswith("win") else [napcat_bat]
        candidates = {
            "napcat.bat",
            "napcat.exe",
            "napcat.win32.exe",
            "napcatwinboot.exe",
            "napcatwinbootmain.exe",
        }
        for root, _, files in os.walk(napcat_dir):
            for name in files:
                if name.lower() in {item.lower() for item in candidates}:
                    return [os.path.join(root, name)]
        return None

    @staticmethod
    def _find_astrbot_command(install_dir):
        astrbot_dir = os.path.join(install_dir, "AstrBot")
        candidates = [
            os.path.join(astrbot_dir, ".venv", "Scripts", "python.exe"),
            os.path.join(astrbot_dir, ".venv", "bin", "python"),
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
            if os.path.exists(p):
                return p
        if shutil.which("astrbot"):
            return shutil.which("astrbot")
        return None

    @staticmethod
    def _python_command():
        # 1. 优先检查打包内置的 Python 环境
        bundled_py = ComponentDownloader._find_bundled_file(os.path.join("python", "python.exe"))
        if bundled_py and os.path.isfile(bundled_py):
            return [bundled_py]

        if sys.platform.startswith("win"):
            win_candidates = [
                r"C:\Users\qeeyou\Python312\python.exe",
                os.path.expandvars(r"%USERPROFILE%\Python312\python.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe"),
                r"C:\Python312\python.exe",
                r"C:\Program Files\Python312\python.exe",
            ]
            for p in win_candidates:
                if os.path.isfile(p):
                    try:
                        res = subprocess.run(
                            [p, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"],
                            capture_output=True,
                            timeout=5
                        )
                        if res.returncode == 0:
                            return [p]
                    except Exception:
                        pass

            if shutil.which("py"):
                for ver in ("-3.13", "-3.12", "-3.11", "-3.10"):
                    try:
                        res = subprocess.run(
                            ["py", ver, "-c", "import sys; print(sys.version_info[:2])"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if res.returncode == 0:
                            return ["py", ver]
                    except Exception:
                        pass
            for candidate in ("python3.12", "python3.13", "python3.11", "python3.10", "python", "python3"):
                path = shutil.which(candidate)
                if path:
                    try:
                        res = subprocess.run(
                            [path, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"],
                            timeout=5
                        )
                        if res.returncode == 0:
                            return [path]
                    except Exception:
                        pass
            return None
        if sys.version_info >= (3, 10) and not getattr(sys, "frozen", False):
            return [sys.executable]
        for candidate in ("python3.12", "python3.11", "python3.10", "python3", "python"):
            path = shutil.which(candidate)
            if path:
                return [path]
        return None

    @staticmethod
    def _venv_python(venv_dir):
        if sys.platform.startswith("win"):
            return os.path.join(venv_dir, "Scripts", "python.exe")
        return os.path.join(venv_dir, "bin", "python")

    @staticmethod
    def _run(command, cwd=None, env=None):
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=1800,
            check=False,
        )

    def _dashboard_password_file(self):
        return os.path.join(os.path.expanduser("~"), ".baomiao_dafeiyu", "astrbot_dashboard_password.txt")

    def _dashboard_password(self):
        password_file = self._dashboard_password_file()
        os.makedirs(os.path.dirname(password_file), exist_ok=True)
        if os.path.exists(password_file):
            with open(password_file, "r", encoding="utf-8") as f:
                password = f.read().strip()
            if password:
                return password
        password = f"Baomiao-{secrets.token_urlsafe(12)}-1a"
        with open(password_file, "w", encoding="utf-8") as f:
            f.write(password)
        if os.name != "nt":
            os.chmod(password_file, 0o600)
        return password

    def install_astrbot(self):
        target_dir = os.path.join(self.install_dir, "AstrBot")
        os.makedirs(target_dir, exist_ok=True)

        # 检查是否已有现成的 AstrBot
        existing_cmd = self._find_astrbot_command(self.install_dir)
        if existing_cmd:
            self.log(f"✅ 检测到已就绪的 AstrBot 环境，跳过安装。", 85)
            env = os.environ.copy()
            env["ASTRBOT_ROOT"] = target_dir
            env["ASTRBOT_DASHBOARD_INITIAL_PASSWORD"] = self._dashboard_password()
            if existing_cmd.lower().endswith("astrbot.exe"):
                self._run([existing_cmd, "init", "--yes"], cwd=target_dir, env=env)
            else:
                self._run([existing_cmd, "-m", "astrbot.cli", "init", "--yes"], cwd=target_dir, env=env)
            return True

        venv_dir = os.path.join(target_dir, ".venv")
        venv_python = self._venv_python(venv_dir)

        if not os.path.exists(venv_python):
            # 检查是否有本地内置 AstrBot 运行环境 (方案一：内置免下载)
            bundle_astrbot_zip = self._find_bundled_file("AstrBot.zip")
            bundle_astrbot_dir = self._find_bundled_file("AstrBot")
            if bundle_astrbot_zip:
                self.log("检测到本地内置 AstrBot 环境，正在解压部署 (0流量)...", 60)
                self.extract_zip(bundle_astrbot_zip, target_dir)
            elif bundle_astrbot_dir and os.path.isdir(bundle_astrbot_dir):
                self.log("检测到本地内置 AstrBot 环境，正在复制装配 (0流量)...", 60)
                shutil.copytree(bundle_astrbot_dir, target_dir, dirs_exist_ok=True)
            else:
                python_command = self._python_command()
                if not python_command:
                    raise RuntimeError("AstrBot 需要 Python 3.10+ 环境，请先安装 Python 并勾选 Add to PATH")
                self.log("正在创建 AstrBot 隔离虚拟环境...")
                result = self._run([*python_command, "-m", "venv", venv_dir])
                if result.returncode != 0:
                    raise RuntimeError(f"创建 Python 环境失败: {result.stdout[-800:]}")

        result = self._run([venv_python, "-c", "import astrbot"])
        if result.returncode != 0:
            self.log(f"正在从国内镜像源安装 AstrBot {ASTRBOT_VERSION}...")
            result = self._run(
                [
                    venv_python, "-m", "pip", "install", "--no-input",
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                    "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
                    f"AstrBot=={ASTRBOT_VERSION}"
                ]
            )
            if result.returncode != 0:
                raise RuntimeError(f"安装 AstrBot 失败: {result.stdout[-800:]}")

        env = os.environ.copy()
        env["ASTRBOT_ROOT"] = target_dir
        env["ASTRBOT_DASHBOARD_INITIAL_PASSWORD"] = self._dashboard_password()
        result = self._run([venv_python, "-m", "astrbot.cli", "init", "--yes"], cwd=target_dir, env=env)
        if result.returncode != 0:
            result = self._run([venv_python, "-m", "astrbot", "init", "--yes"], cwd=target_dir, env=env)
        self.log(f"✅ AstrBot {ASTRBOT_VERSION} 已安装；管理密码文件: {self._dashboard_password_file()}", 85)
        return True
        if result.returncode != 0:
            raise RuntimeError(f"初始化 AstrBot 失败: {result.stdout[-800:]}")
        self.log(f"✅ AstrBot {ASTRBOT_VERSION} 已安装；管理密码文件: {self._dashboard_password_file()}", 85)
        return True

    @staticmethod
    def _find_bundled_file(name):
        candidates = []
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "bundled", name))
            candidates.append(os.path.join(sys._MEIPASS, name))
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(base_dir, "bundled", name))
        candidates.append(os.path.join(base_dir, name))
        # 也可以检查可执行文件同级目录
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            candidates.append(os.path.join(exe_dir, "bundled", name))
            candidates.append(os.path.join(exe_dir, name))
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def check_installed(self):
        napcat_ok = self._find_napcat_command(os.path.join(self.install_dir, "NapCat")) is not None
        astrbot_ok = self._find_astrbot_command(self.install_dir) is not None
        return napcat_ok and astrbot_ok

    def start_setup(self):
        self.is_downloading = True
        try:
            napcat_dir = os.path.join(self.install_dir, "NapCat")
            if self._find_napcat_command(napcat_dir):
                self.log("组件 [NapCat] 已就绪，跳过下载。", 20)
            else:
                if os.path.isdir(napcat_dir):
                    shutil.rmtree(napcat_dir)
                # 检查本地是否有内置 NapCat (方案一：全内置免下载)
                bundle_napcat_zip = self._find_bundled_file("NapCat.zip")
                bundle_napcat_dir = self._find_bundled_file("NapCat")
                if bundle_napcat_zip:
                    self.log("检测到本地内置 NapCat，正在直接解压部署 (0流量)...", 10)
                    self.extract_zip(bundle_napcat_zip, napcat_dir)
                elif bundle_napcat_dir and os.path.isdir(bundle_napcat_dir):
                    self.log("检测到本地内置 NapCat，正在装配 (0流量)...", 10)
                    shutil.copytree(bundle_napcat_dir, napcat_dir, dirs_exist_ok=True)
                else:
                    zip_path = os.path.join(self.install_dir, "NapCat.zip")
                    self.log(f"开始下载 NapCat {NAPCAT_VERSION}...")
                    success = self.download_file(NAPCAT_URL, zip_path, NAPCAT_SHA256)
                    if not success:
                        raise RuntimeError("NapCat 下载失败，请检查网络连接后重试")
                    self.extract_zip(zip_path, napcat_dir)
                    if os.path.exists(zip_path):
                        os.remove(zip_path)

                if not self._find_napcat_command(napcat_dir):
                    raise RuntimeError("NapCat 目录中未找到可执行程序")
                self.log("✅ [NapCat] 部署完成！", 45)

            self.install_astrbot()
            self.log("🎉 全部核心组件已校验完成！", 100)
            self.is_downloading = False
            return True
        except Exception as exc:
            self.log(f"部署异常: {exc}")
            self.is_downloading = False
            return False
