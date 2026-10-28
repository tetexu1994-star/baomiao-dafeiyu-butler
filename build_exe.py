# -*- coding: utf-8 -*-
"""
暴喵大肥鱼一键管家 · 单文件 .exe 打包脚本
在 Windows 环境下运行：python build_exe.py
"""

import os
import sys
import subprocess

def build():
    print("==================================================")
    print(" 开始打包 [暴喵大肥鱼一键管家.exe] ...")
    print("==================================================")

    # 检查是否安装 pyinstaller
    try:
        import PyInstaller
    except ImportError:
        print("[提示] 正在安装 PyInstaller 打包工具...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 确定当前目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(base_dir, "web")
    core_dir = os.path.join(base_dir, "core")

    # 构建参数
    # Windows 下打包加入 web 静态文件
    separator = ";" if sys.platform.startswith("win") else ":"
    add_data_web = f"{web_dir}{separator}web"
    add_data_core = f"{core_dir}{separator}core"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=暴喵大肥鱼一键管家",
        "--onefile",
        "--clean",
        f"--add-data={add_data_web}",
        f"--add-data={add_data_core}",
        os.path.join(base_dir, "app.py")
    ]

    print("执行命令:", " ".join(cmd))
    subprocess.check_call(cmd)
    
    print("\n==================================================")
    print("🎉 打包完成！")
    print(f"生成的单文件程序位于: {os.path.join(base_dir, 'dist', '暴喵大肥鱼一键管家.exe')}")
    print("==================================================")

if __name__ == "__main__":
    build()
