# -*- coding: utf-8 -*-
import os
import sys
import zipfile
import urllib.request
import threading
import time

# 高速镜像源列表
GH_PROXIES = [
    "https://ghfast.top/",
    "https://mirror.ghproxy.com/",
    "https://ghproxy.net/",
    ""
]

COMPONENTS = {
    "NapCat": {
        "url": "https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.win32.zip",
        "fallback_url": "https://github.com/NapNeko/NapCatQQ/releases/download/v2.5.1/NapCat.win32.zip",
        "archive_name": "NapCat.zip",
        "extract_folder": "NapCat"
    },
    "AstrBot": {
        "url": "https://github.com/AstrBotDevs/AstrBot/releases/latest/download/AstrBot-Windows.zip",
        "fallback_url": "https://github.com/AstrBotDevs/AstrBot/releases/download/v3.4.0/AstrBot-Windows.zip",
        "archive_name": "AstrBot.zip",
        "extract_folder": "AstrBot"
    }
}

class ComponentDownloader:
    def __init__(self, install_dir, status_callback=None):
        self.install_dir = install_dir
        self.status_callback = status_callback
        self.is_downloading = False
        os.makedirs(self.install_dir, exist_ok=True)

    def log(self, message, progress=None):
        if self.status_callback:
            self.status_callback({"message": message, "progress": progress})

    def download_file(self, raw_url, dest_path):
        for proxy in GH_PROXIES:
            target_url = proxy + raw_url if proxy else raw_url
            try:
                self.log(f"正在连接下载源 ({proxy or 'Direct'})...")
                req = urllib.request.Request(target_url, headers={"User-Agent": "BaomiaoButler/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    total_size = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    chunk_size = 64 * 1024
                    with open(dest_path, "wb") as f:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 100)
                                self.log(f"下载进度: {downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB ({pct}%)", pct)
                    return True
            except Exception as e:
                self.log(f"源 {proxy} 连接超时或失败，尝试下一节点...")
                continue
        return False

    def extract_zip(self, zip_path, extract_to):
        self.log(f"正在解压组件到 {os.path.basename(extract_to)}...")
        os.makedirs(extract_to, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        return True

    def check_installed(self):
        napcat_ok = os.path.exists(os.path.join(self.install_dir, "NapCat"))
        astrbot_ok = os.path.exists(os.path.join(self.install_dir, "AstrBot"))
        return napcat_ok and astrbot_ok

    def start_setup(self):
        self.is_downloading = True
        try:
            for name, comp in COMPONENTS.items():
                target_dir = os.path.join(self.install_dir, comp["extract_folder"])
                if os.path.exists(target_dir) and len(os.listdir(target_dir)) > 0:
                    self.log(f"组件 [{name}] 已就绪，跳过下载。")
                    continue
                
                zip_path = os.path.join(self.install_dir, comp["archive_name"])
                self.log(f"开始准备组件 [{name}]...")
                success = self.download_file(comp["url"], zip_path)
                if not success:
                    # 尝试备用链接
                    self.log(f"切换备用链接下载 [{name}]...")
                    success = self.download_file(comp["fallback_url"], zip_path)
                
                if success:
                    self.extract_zip(zip_path, target_dir)
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
                    self.log(f"✅ [{name}] 部署完成！")
                else:
                    self.log(f"❌ [{name}] 下载失败，请检查网络连接后重试！")
                    self.is_downloading = False
                    return False

            self.log("🎉 全部核心组件已校验完成！", 100)
            self.is_downloading = False
            return True
        except Exception as e:
            self.log(f"部署异常: {str(e)}")
            self.is_downloading = False
            return False
