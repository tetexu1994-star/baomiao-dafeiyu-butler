# -*- coding: utf-8 -*-
"""
一键安装 · 单文件 .exe 打包脚本
在 Windows 环境下运行：python build_exe.py
"""

import os
import sys
import subprocess

# 确保 UTF-8 编码输出
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def build():
    print("==================================================")
    print(" 开始打包 [一键安装.exe] ...")
    print("==================================================")

    print("[提示] 正在安装打包依赖...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "-r", os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements-build.txt"),
    ])

    # 确定当前目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(base_dir, "web")

    # 构建参数
    separator = ";" if sys.platform.startswith("win") else ":"
    add_data_web = f"{web_dir}{separator}web"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=一键安装",
        "--onefile",
        "--clean",
        "--windowed",
        f"--add-data={add_data_web}",
        "--hidden-import=webview",
        os.path.join(base_dir, "app.py")
    ]

    print("执行命令:", " ".join(cmd))
    subprocess.check_call(cmd)
    
    print("\n==================================================")
    print("🎉 打包完成！")
    print(f"生成的单文件程序位于: {os.path.join(base_dir, 'dist', '一键安装.exe')}")
    print("==================================================")

if __name__ == "__main__":
    build()
