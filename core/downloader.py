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

GH_PROXIES = [
    "https://ghfast.top/",
    "https://mirror.ghproxy.com/",
    "https://ghproxy.net/",
    "",
]

NAPCAT_VERSION = "4.18.41"
ASTRBOT_VERSION = "4.29.3"
NAPCAT_URL = (
    "https://github.com/NapNeko/NapCatQQ/releases/download/"
    f"{NAPCAT_VERSION}/NapCat.Shell.Windows.Node.zip"
)
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
        for proxy in GH_PROXIES:
            target_url = proxy + raw_url if proxy else raw_url
            digest = hashlib.sha256()
            try:
                self.log(f"正在连接下载源 ({proxy or '官方直连'})...")
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
                self.log(f"源 {proxy or '官方直连'} 下载或校验失败: {exc}")
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
        candidates = {
            "NapCatWinBootMain.exe",
            "napcat.win32.exe",
            "NapCatWinBoot.exe",
            "NapCat.exe",
            "napcat.bat",
        }
        for root, _, files in os.walk(napcat_dir):
            for name in files:
                if name.lower() in {item.lower() for item in candidates}:
                    return [os.path.join(root, name)]
        return None

    @staticmethod
    def _python_command():
        if sys.platform.startswith("win"):
            if shutil.which("py"):
                try:
                    res = subprocess.run(
                        ["py", "-3.12", "-c", "import sys; print(sys.version_info[:2])"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if res.returncode == 0:
                        return ["py", "-3.12"]
                except Exception:
                    pass
            for candidate in ("python3.12", "python", "python3"):
                path = shutil.which(candidate)
                if path:
                    try:
                        res = subprocess.run(
                            [path, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"],
                            timeout=5
                        )
                        if res.returncode == 0:
                            return [path]
                    except Exception:
                        pass
            return None
        if sys.version_info >= (3, 12) and not getattr(sys, "frozen", False):
            return [sys.executable]
        for candidate in ("python3.12", "python3", "python"):
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
        venv_dir = os.path.join(target_dir, ".venv")
        venv_python = self._venv_python(venv_dir)
        os.makedirs(target_dir, exist_ok=True)

        if not os.path.exists(venv_python):
            python_command = self._python_command()
            if not python_command:
                raise RuntimeError("AstrBot 4.29.3 需要 Python 3.12，请先安装后重试")
            self.log("正在创建 AstrBot Python 3.12 虚拟环境...")
            result = self._run([*python_command, "-m", "venv", venv_dir])
            if result.returncode != 0:
                raise RuntimeError(f"创建 Python 环境失败: {result.stdout[-800:]}")

        result = self._run([venv_python, "-c", "import astrbot"])
        if result.returncode != 0:
            self.log(f"正在安装 AstrBot {ASTRBOT_VERSION}（首次安装可能需要几分钟）...")
            result = self._run(
                [venv_python, "-m", "pip", "install", "--no-input", f"AstrBot=={ASTRBOT_VERSION}"]
            )
            if result.returncode != 0:
                raise RuntimeError(f"安装 AstrBot 失败: {result.stdout[-800:]}")

        env = os.environ.copy()
        env["ASTRBOT_ROOT"] = target_dir
        env["ASTRBOT_DASHBOARD_INITIAL_PASSWORD"] = self._dashboard_password()
        result = self._run([venv_python, "-m", "astrbot", "init", "--yes"], cwd=target_dir, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"初始化 AstrBot 失败: {result.stdout[-800:]}")
        self.log(f"✅ AstrBot {ASTRBOT_VERSION} 已安装；管理密码文件: {self._dashboard_password_file()}", 85)
        return True

    def check_installed(self):
        napcat_ok = self._find_napcat_command(os.path.join(self.install_dir, "NapCat")) is not None
        astrbot_ok = os.path.exists(self._venv_python(os.path.join(self.install_dir, "AstrBot", ".venv")))
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
                zip_path = os.path.join(self.install_dir, "NapCat.zip")
                self.log(f"开始下载 NapCat {NAPCAT_VERSION}...")
                success = self.download_file(NAPCAT_URL, zip_path, NAPCAT_SHA256)
                if not success:
                    raise RuntimeError("NapCat 下载失败，请检查网络连接后重试")
                self.extract_zip(zip_path, napcat_dir)
                os.remove(zip_path)
                if not self._find_napcat_command(napcat_dir):
                    raise RuntimeError("NapCat 压缩包中未找到可执行程序")
                self.log("✅ [NapCat] 部署完成！", 45)

            self.install_astrbot()
            self.log("🎉 全部核心组件已校验完成！", 100)
            self.is_downloading = False
            return True
        except Exception as exc:
            self.log(f"部署异常: {exc}")
            self.is_downloading = False
            return False
