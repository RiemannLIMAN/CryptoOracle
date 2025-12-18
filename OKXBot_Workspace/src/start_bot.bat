@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ===================================================
echo 🤖 CryptoOracle Windows 启动脚本
echo ===================================================

:: 1. 检测虚拟环境
if exist "..\venv\Scripts\activate.bat" (
    echo ✅ 检测到 Python 虚拟环境 (venv)
    echo ⏳ 正在激活环境...
    call "..\venv\Scripts\activate.bat"
) else (
    echo ⚠️ 未检测到 venv，将尝试使用系统 Python
)

:: 2. 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 错误: 未找到 Python，请先安装 Python 并添加到 PATH。
    pause
    exit /b
)

:: 3. 启动机器人
echo.
echo 🚀 正在启动机器人主程序...
echo 💡 提示: 请勿关闭此窗口，否则机器人将停止运行。
echo.

python okx_deepseek.py

if %errorlevel% neq 0 (
    echo.
    echo ❌ 程序异常退出 (Exit Code: %errorlevel%)
    echo 💡 请检查上方报错信息 (通常是 API Key 错误或网络问题)
)

pause
