@echo off
chcp 65001 >nul
title 暴喵大肥鱼AI管家 - 启动器
echo ========================================================
echo         正在启动 暴喵大肥鱼一键安装管家...
echo ========================================================
echo.
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境，请先安装 Python 3.12+ 并勾选 Add to PATH！
    pause
    exit /b 1
)

echo 正在启动管理面板并在浏览器打开...
python app.py
pause
