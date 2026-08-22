#!/bin/bash
# SillyTavern 一键下载脚本(release 稳定版)

URL="https://github.com/SillyTavern/SillyTavern/archive/refs/heads/release.zip"
ZIPFILE="st-release.zip"
EXTRACTED_DIR="SillyTavern-release"
TARGET_DIR="SillyTavern"
BACKUP_DIR="st_data_backup"
CONFIG_BAK="config.yaml.bak"

echo ""
echo "============================================================"
echo "    SillyTavern 一键下载脚本(release 稳定版)"
echo "============================================================"
echo ""

# ==================== 工具检测 ====================
download() {
    if command -v curl &> /dev/null; then
        if curl -fSL --retry 3 --retry-delay 5 -o "$ZIPFILE" "$URL"; then return 0; fi
        echo "[警告] curl 下载失败,尝试 wget..."
    fi
    if command -v wget &> /dev/null; then
        if wget -q --tries=3 -O "$ZIPFILE" "$URL"; then return 0; fi
        echo "[警告] wget 下载失败"
    fi
    return 1
}

extract() {
    if command -v unzip &> /dev/null; then
        if unzip -q "$ZIPFILE"; then return 0; fi
        echo "[警告] unzip 失败,尝试 python3..."
    fi
    if command -v python3 &> /dev/null; then
        if python3 -c "import zipfile; zipfile.ZipFile('$ZIPFILE').extractall('.')"; then return 0; fi
        echo "[警告] python3 解压失败"
    fi
    return 1
}

read_local_version() {
    if [ -f "$TARGET_DIR/package.json" ]; then
        if command -v python3 &> /dev/null; then
            python3 -c "import json; print(json.load(open('$TARGET_DIR/package.json'))['version'])" 2>/dev/null
        else
            grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$TARGET_DIR/package.json" 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1
        fi
    fi
}

read_remote_version() {
    if command -v curl &> /dev/null; then
        curl -fsSL https://api.github.com/repos/SillyTavern/SillyTavern/releases/latest 2>/dev/null | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '[0-9][0-9.]*' | head -1
    elif command -v wget &> /dev/null; then
        wget -qO- https://api.github.com/repos/SillyTavern/SillyTavern/releases/latest 2>/dev/null | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '[0-9][0-9.]*' | head -1
    fi
}

print_node_manual() {
    echo ""
    echo "请手动安装 Node.js LTS (18 或更高版本):"
    echo "  方式一(推荐): 使用 nvm"
    echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash"
    echo "    source ~/.bashrc && nvm install --lts"
    echo "  方式二: 官网下载安装包 https://nodejs.org/"
}

print_guide() {
    echo ""
    echo "============================================================"
    echo "  SillyTavern 使用指南"
    echo "============================================================"
    echo ""
    echo "  1. 进入目录:   cd $TARGET_DIR"
    echo "  2. 安装依赖:   npm install"
    echo "  3. 启动服务:   bash start.sh (或 node server.js)"
    echo ""
    echo "  启动成功后默认地址为: http://127.0.0.1:8000"
    echo ""
    echo "  请在本插件(调酒师)的配置中设置:"
    echo "    browser_ip   = http://127.0.0.1"
    echo "    browser_port = 8000"
    echo ""
    echo "  说明:本脚本通过下载 Release 源码包安装,更新时重新下载替换,"
    echo "        用户数据(data 目录与 config.yaml)会自动保留."
    echo "============================================================"
}

# ==================== 已存在则检查更新,否则全新下载 ====================
if [ -d "$TARGET_DIR" ]; then
    echo "检测到已存在 SillyTavern,正在检查版本更新..."
    echo ""

    LOCAL_VER=$(read_local_version)
    if [ -z "$LOCAL_VER" ]; then
        echo "[警告] 无法读取本地版本信息."
        read -rp "   是否删除并重新下载最新版?(y/n): " REINSTALL
        if [ "$REINSTALL" = "y" ]; then goto="DO_REPLACE"; fi
        if [ "${goto:-}" = "DO_REPLACE" ]; then :; else echo "已跳过更新."; GUIDE_ONLY=1; fi
    else
        echo "正在查询远端最新版本(需要联网)..."
        REMOTE_VER=$(read_remote_version)
        if [ -z "$REMOTE_VER" ]; then
            echo "[警告] 无法获取远端最新版本(网络问题),无法判断是否需要更新."
            read -rp "   是否删除并重新下载最新版?(y/n): " REINSTALL
            if [ "$REINSTALL" = "y" ]; then goto="DO_REPLACE"; fi
            if [ "${goto:-}" = "DO_REPLACE" ]; then :; else GUIDE_ONLY=1; fi
        else
            echo "  本地版本: $LOCAL_VER"
            echo "  最新版本: $REMOTE_VER"
            echo ""
            if [ "$LOCAL_VER" = "$REMOTE_VER" ]; then
                echo "已是最新版本,无需更新."
                GUIDE_ONLY=1
            else
                echo "发现版本不同,可更新到 $REMOTE_VER."
                read -rp "   是否更新?(y/n): " DO_UPDATE
                if [ "$DO_UPDATE" = "y" ]; then
                    goto="DO_REPLACE"
                else
                    GUIDE_ONLY=1
                fi
            fi
        fi
    fi
else
    echo "未检测到 SillyTavern,将进行全新下载安装."
    echo ""
    goto="DO_FRESH"
fi

# ==================== 全新下载 ====================
if [ "${goto:-}" = "DO_FRESH" ]; then
    if ! download; then goto="DOWNLOAD_FAIL"; else
        if ! extract; then goto="DOWNLOAD_FAIL_CLEAN"; else
            if ! mv "$EXTRACTED_DIR" "$TARGET_DIR"; then goto="RENAME_FAIL"; else
                rm -f "$ZIPFILE"
                echo ""
                echo "[成功] SillyTavern 下载完成!"
                goto="ASK_INSTALL"
            fi
        fi
    fi
fi

# ==================== 替换更新(保留用户数据)====================
if [ "${goto:-}" = "DO_REPLACE" ]; then
    HAS_CONFIG=0
    echo ""
    echo "正在备份用户数据(data 目录与 config.yaml)..."
    if [ -d "$TARGET_DIR/data" ]; then
        mv "$TARGET_DIR/data" "$BACKUP_DIR" 2>/dev/null
    fi
    if [ -f "$TARGET_DIR/config.yaml" ]; then
        HAS_CONFIG=1
        mv "$TARGET_DIR/config.yaml" "$CONFIG_BAK" 2>/dev/null
    fi

    echo "正在删除旧版本代码..."
    rm -rf "$TARGET_DIR"

    echo "正在下载新版..."
    if ! download; then goto="DOWNLOAD_FAIL"; else
        if ! extract; then goto="DOWNLOAD_FAIL_CLEAN"; else
            if ! mv "$EXTRACTED_DIR" "$TARGET_DIR"; then goto="RENAME_FAIL"; else
                echo "正在还原用户数据..."
                if [ -d "$BACKUP_DIR" ]; then
                    mv "$BACKUP_DIR" "$TARGET_DIR/data" 2>/dev/null
                fi
                if [ "$HAS_CONFIG" = "1" ]; then
                    mv "$CONFIG_BAK" "$TARGET_DIR/config.yaml" 2>/dev/null
                fi
                rm -f "$ZIPFILE"
                echo ""
                echo "[成功] SillyTavern 更新完成!"
                echo "提示:代码已更新,建议重新执行依赖安装(node_modules 已被替换)."
                goto="ASK_INSTALL"
            fi
        fi
    fi
fi

# ==================== 失败分支 ====================
if [ "${goto:-}" = "DOWNLOAD_FAIL" ]; then
    echo ""
    echo "[错误] 下载失败!请检查网络连接或代理设置后重试."
    echo "备用方案 - 浏览器手动下载并解压:"
    echo "  $URL"
    echo ""
    read -rp "按回车键退出..."
    exit 1
fi

if [ "${goto:-}" = "DOWNLOAD_FAIL_CLEAN" ]; then
    echo ""
    echo "[错误] 解压失败!"
    echo ""
    read -rp "按回车键退出..."
    exit 1
fi

if [ "${goto:-}" = "RENAME_FAIL" ]; then
    echo ""
    echo "[错误] 重命名 $EXTRACTED_DIR 为 $TARGET_DIR 失败!"
    echo "可能 $TARGET_DIR 目录已被占用,请手动处理."
    echo ""
    read -rp "按回车键退出..."
    exit 1
fi

# ==================== 依赖安装询问 ====================
if [ "${goto:-}" = "ASK_INSTALL" ] || [ "${GUIDE_ONLY:-0}" = "1" ]; then
    echo ""
    read -rp "   是否现在自动执行依赖安装 (npm install)?(y/n): " INSTALL_DEPS
    if [ "$INSTALL_DEPS" != "y" ]; then
        echo "已跳过依赖安装,可稍后参考文末指南手动执行."
        print_guide
        echo ""
        read -rp "按回车键退出..."
        exit 0
    fi

    # ==================== Node.js 检查 ====================
    node_major() { node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1; }
    node_ok() { command -v node &> /dev/null && [ "$(node_major)" -ge 18 ] 2>/dev/null; }

    if ! node_ok; then
        if command -v node &> /dev/null; then
            echo "[警告] 当前 Node.js 版本过低(检测到主版本 $(node_major),要求大于等于 18)."
        else
            echo "[警告] 未检测到 Node.js(SillyTavern 要求 Node.js 18 或更高版本)."
        fi

        read -rp "   是否尝试自动安装 Node.js?(y/n): " AUTO_INSTALL_NODE
        if [ "$AUTO_INSTALL_NODE" = "y" ]; then
            if command -v apt-get &> /dev/null; then
                if ! command -v curl &> /dev/null; then
                    echo "正在安装 curl ..."
                    sudo apt-get update && sudo apt-get install -y curl || { echo "[错误] curl 安装失败"; print_node_manual; read -rp "按回车键退出..."; exit 1; }
                fi
                echo "正在通过 NodeSource 安装 Node.js 22 LTS(需要 sudo 权限)..."
                if curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs; then
                    NODE_INSTALLED=1
                fi
            elif command -v dnf &> /dev/null; then
                if ! command -v curl &> /dev/null; then
                    sudo dnf install -y curl || { echo "[错误] curl 安装失败"; print_node_manual; read -rp "按回车键退出..."; exit 1; }
                fi
                echo "正在通过 NodeSource 安装 Node.js 22 LTS(需要 sudo 权限)..."
                if curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash - && sudo dnf install -y nodejs; then
                    NODE_INSTALLED=1
                fi
            else
                echo "[提示] 未识别到受支持的包管理器(apt/dnf)."
            fi

            if [ "${NODE_INSTALLED:-0}" = "1" ] && node_ok; then
                echo ""
                echo "[成功] Node.js 安装完成!"
            else
                echo ""
                echo "[错误] 自动安装未成功."
                print_node_manual
                echo ""
                echo "安装完成后重新运行本脚本即可继续."
                read -rp "按回车键退出..."
                exit 1
            fi
        else
            print_node_manual
            echo ""
            echo "安装完成后重新运行本脚本即可继续."
            read -rp "按回车键退出..."
            exit 1
        fi
    fi

    echo "[信息] 检测到 Node.js 版本符合要求 ($(node -v))."

    # ==================== 安装依赖 ====================
    cd "$TARGET_DIR" || exit 1
    echo ""
    echo "正在安装依赖(可能需要几分钟,取决于网络速度)..."
    echo ""
    if ! npm install --no-audit --no-fund; then
        echo ""
        echo "[错误] 依赖安装失败!请检查上方报错信息."
        echo "常见原因:网络问题,可尝试配置镜像后重试:"
        echo "  npm config set registry https://registry.npmmirror.com"
        cd ..
        read -rp "按回车键退出..."
        exit 1
    fi

    echo ""
    echo "[成功] SillyTavern 依赖安装完成!"
    cd ..
fi

print_guide
echo ""
read -rp "按回车键退出..."
