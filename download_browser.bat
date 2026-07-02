@echo off
chcp 65001 >nul

echo 正在启动下载脚本...

:: 检查是否有 python 命令
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [错误] 未检测到 Python 环境！
    echo 请确保已安装 Python 并添加到系统 PATH 中。
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 运行 Python 脚本
python download_browser.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 脚本执行失败，请查看上方错误信息。
    pause
    exit /b 1
)
