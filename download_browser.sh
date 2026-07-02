#!/bin/bash

echo "正在启动下载脚本..."

# 检查是否有 python3 命令
if ! command -v python3 &> /dev/null; then
    echo ""
    echo "[错误] 未检测到 Python3 环境！"
    echo "请确保已安装 Python3。"
    echo "在 Ubuntu/Debian 上可以使用: sudo apt install python3"
    echo "在 CentOS/RHEL 上可以使用: sudo yum install python3"
    echo ""
    exit 1
fi

# 运行 Python 脚本
python3 download_browser.py

# 检查脚本执行结果
if [ $? -ne 0 ]; then
    echo ""
    echo "[错误] 脚本执行失败，请查看上方错误信息。"
    exit 1
fi
