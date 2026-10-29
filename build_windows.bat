@echo off
chcp 65001 >nul
echo ==================================================
echo       一键安装 · Windows 自动化编译脚本
echo ==================================================
echo.

python -V >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境，请先安装 Python 并勾选 Add to PATH！
    pause
    exit /b
)

echo [1/2] 正在安装打包环境...
pip install -r requirements-build.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo [2/2] 开始编译单文件 exe...
python build_exe.py

echo.
echo 编译完成！程序已生成至 dist\一键安装.exe
pause
