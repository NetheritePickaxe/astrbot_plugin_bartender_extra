# -*- coding: utf-8 -*-
"""
SillyTavern 一键下载/更新脚本（release 稳定版）
纯标准库实现，跨平台通用。功能与 download_sillytavern.bat/.sh 对等。

用法:
    python download_sillytavern.py        (Windows)
    python3 download_sillytavern.py       (Linux/macOS)
"""

import os
import sys
import json
import shutil
import zipfile
import subprocess
import urllib.request
import urllib.error

# ======================== 配置区 ========================
URL = "https://github.com/SillyTavern/SillyTavern/archive/refs/heads/release.zip"
ZIPFILE = "st-release.zip"
EXTRACTED_DIR = "SillyTavern-release"
TARGET_DIR = sys.argv[1] if len(sys.argv) > 1 else "SillyTavern"
BACKUP_DIR = "st_data_backup"
CONFIG_BAK = "config.yaml.bak"

TIMEOUT_DOWNLOAD = 60
TIMEOUT_API = 15
MAX_NODES = 100
# ========================================================


def read_local_version():
    """读取本地 SillyTavern/package.json 中的 version 字段"""
    pkg_path = os.path.join(TARGET_DIR, "package.json")
    if not os.path.isfile(pkg_path):
        return None
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("version", "").strip() or None
    except Exception:
        return None


def read_remote_version():
    """通过 GitHub API 查询最新 release 的 tag_name"""
    api_url = "https://api.github.com/repos/SillyTavern/SillyTavern/releases/latest"
    try:
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT_API) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "").strip().lstrip("v")
        return tag or None
    except Exception:
        return None


def do_download():
    """下载 release.zip，返回 True/False"""
    print(f"  正在下载: {URL}")
    try:
        req = urllib.request.Request(URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT_DOWNLOAD) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(ZIPFILE, "wb") as f:
                while True:
                    buf = resp.read(65536)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if total > 0:
                        pct = downloaded * 100 // total
                        bar_len = 40
                        filled = bar_len * downloaded // total
                        bar = "=" * filled + "-" * (bar_len - filled)
                        sys.stdout.write(f"\r  |{bar}| {pct}% ({downloaded // 1048576}MB/{total // 1048576}MB)")
                        sys.stdout.flush()
                    else:
                        sys.stdout.write(f"\r  已下载 {downloaded // 1048576}MB")
                        sys.stdout.flush()
        print()
        if os.path.getsize(ZIPFILE) < 1024:
            print("  [错误] 下载文件过小，可能不是有效压缩包")
            return False
        return True
    except Exception as e:
        print(f"\n  [错误] 下载失败: {e}")
        return False


def do_extract():
    """解压 ZIPFILE 到当前目录，返回 True/False"""
    print("  正在解压...")
    try:
        with zipfile.ZipFile(ZIPFILE, "r") as zf:
            members = zf.namelist()
            count = len(members)
            for i, m in enumerate(members, 1):
                zf.extract(m, ".")
                if i % 50 == 0 or i == count:
                    pct = i * 100 // count
                    sys.stdout.write(f"\r  解压进度: {pct}% ({i}/{count})")
                    sys.stdout.flush()
        print()
        if not os.path.isdir(EXTRACTED_DIR):
            print(f"  [错误] 解压后未找到 {EXTRACTED_DIR} 目录")
            return False
        return True
    except zipfile.BadZipFile:
        print("  [错误] 压缩包已损坏或不完整")
        return False
    except Exception as e:
        print(f"  [错误] 解压失败: {e}")
        return False


def fresh_install():
    """全新下载安装"""
    print("未检测到 SillyTavern，将进行全新下载安装。")
    print()
    if not do_download():
        return False
    if not do_extract():
        return False
    if os.path.isdir(TARGET_DIR):
        shutil.rmtree(TARGET_DIR, ignore_errors=True)
    try:
        os.rename(EXTRACTED_DIR, TARGET_DIR)
    except Exception as e:
        print(f"  [错误] 重命名 {EXTRACTED_DIR} 为 {TARGET_DIR} 失败: {e}")
        return False
    _cleanup_zip()
    print()
    print("[成功] SillyTavern 下载完成！")
    return True


def do_replace():
    """备份用户数据 → 删旧 → 下载新版 → 还原数据"""
    has_config = False
    print()
    print("正在备份用户数据(data 目录与 config.yaml)...")
    if os.path.isdir(os.path.join(TARGET_DIR, "data")):
        try:
            shutil.move(os.path.join(TARGET_DIR, "data"), BACKUP_DIR)
        except Exception:
            pass
    if os.path.isfile(os.path.join(TARGET_DIR, "config.yaml")):
        has_config = True
        try:
            shutil.move(os.path.join(TARGET_DIR, "config.yaml"), CONFIG_BAK)
        except Exception:
            pass

    print("正在删除旧版本代码...")
    shutil.rmtree(TARGET_DIR, ignore_errors=True)

    print("正在下载新版...")
    if not do_download():
        return False
    if not do_extract():
        return False
    try:
        os.rename(EXTRACTED_DIR, TARGET_DIR)
    except Exception as e:
        print(f"  [错误] 重命名失败: {e}")
        return False

    print("正在还原用户数据...")
    if os.path.isdir(BACKUP_DIR):
        new_data = os.path.join(TARGET_DIR, "data")
        if os.path.isdir(new_data):
            shutil.rmtree(new_data, ignore_errors=True)
        try:
            shutil.move(BACKUP_DIR, os.path.join(TARGET_DIR, "data"))
        except Exception:
            pass
    if has_config and os.path.isfile(CONFIG_BAK):
        try:
            shutil.move(CONFIG_BAK, os.path.join(TARGET_DIR, "config.yaml"))
        except Exception:
            pass
    _cleanup_zip()

    print()
    print("[成功] SillyTavern 更新完成！")
    print("提示: 代码已更新，建议重新执行依赖安装(node_modules 已被替换)。")
    return True


def check_node():
    """检查 Node.js 版本 >= 18，返回 (ok, major_version)"""
    try:
        result = subprocess.run(
            ["node", "-v"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, 0
        version = result.stdout.strip()
        if version.startswith("v"):
            version = version[1:]
        major = int(version.split(".")[0])
        if major < 18:
            return False, major
        return True, major
    except FileNotFoundError:
        return False, 0
    except Exception:
        return False, 0


def npm_install():
    """在 TARGET_DIR 中执行 npm install"""
    ok, major = check_node()
    if not ok:
        if major == 0:
            print()
            print("[警告] 未检测到 Node.js(SillyTavern 要求 Node.js 18 或更高版本)。")
            if sys.platform == "win32":
                choice = input("是否尝试通过 winget 自动安装 Node.js LTS? (y/n): ").strip().lower()
                if choice == "y":
                    try:
                        subprocess.run(
                            ["winget", "install", "OpenJS.NodeJS.LTS",
                             "--accept-package-agreements", "--accept-source-agreements"],
                            timeout=300
                        )
                        print()
                        print("[成功] Node.js 安装完成！")
                        print("重要提示: 环境变量 PATH 需要重新加载才能生效。")
                        print("请关闭本窗口，重新打开终端后再次运行本脚本。")
                        return False
                    except Exception:
                        print("[错误] winget 安装失败。")
        print()
        print("请手动安装 Node.js LTS(18 或更高版本):")
        if sys.platform == "win32":
            print("  下载地址: https://nodejs.org/")
            print("  或命令: winget install OpenJS.NodeJS.LTS")
        else:
            print("  方式一(推荐): 使用 nvm")
            print("    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash")
            print("    source ~/.bashrc && nvm install --lts")
            print("  方式二: 官网下载安装包 https://nodejs.org/")
        return False
    else:
        print(f"  [信息] 检测到 Node.js v{major}，版本符合要求。")

    npm_path = shutil.which("npm")
    if not npm_path:
        print("[错误] 未检测到 npm 命令，请确认 Node.js 已正确安装。")
        return False
    print()
    print("正在安装依赖(可能需要几分钟，取决于网络速度)...")
    print()
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                "npm install --no-audit --no-fund",
                shell=True,
                cwd=TARGET_DIR,
                timeout=600,
            )
        else:
            result = subprocess.run(
                [npm_path, "install", "--no-audit", "--no-fund"],
                cwd=TARGET_DIR,
                timeout=600,
            )
        if result.returncode != 0:
            print()
            print("[错误] 依赖安装失败！请检查上方报错信息。")
            print("常见原因: 网络问题，可尝试配置镜像后重试:")
            print("  npm config set registry https://registry.npmmirror.com")
            return False
        print()
        print("[成功] SillyTavern 依赖安装完成！")
        return True
    except FileNotFoundError:
        print("[错误] 未检测到 npm 命令，请确认 Node.js 已正确安装。")
        return False
    except Exception as e:
        print(f"[错误] 依赖安装异常: {e}")
        return False


def print_guide():
    """打印使用指南"""
    print()
    print("=" * 50)
    print("  SillyTavern 使用指南")
    print("=" * 50)
    print()
    print("  1. 进入目录:   cd " + TARGET_DIR)
    print("  2. 安装依赖:   npm install")
    if sys.platform == "win32":
        print("  3. 启动服务:   运行 Start.bat (或命令行执行 node server.js)")
    else:
        print("  3. 启动服务:   bash start.sh (或 node server.js)")
    print()
    print("  启动成功后默认地址为: http://127.0.0.1:8000")
    print()
    print("  请在本插件(调酒师)的配置中设置:")
    print("    browser_ip   = http://127.0.0.1")
    print("    browser_port = 8000")
    print()
    print("  说明: 本脚本通过下载 Release 源码包安装，更新时重新下载替换，")
    print("        用户数据(data 目录与 config.yaml)会自动保留。")
    print("=" * 50)


def _cleanup_zip():
    """清理临时 zip 文件"""
    try:
        if os.path.isfile(ZIPFILE):
            os.remove(ZIPFILE)
    except Exception:
        pass


def main():
    print()
    print("=" * 50)
    print("    SillyTavern 一键下载脚本(release 稳定版)")
    print("=" * 50)
    print()

    if os.path.isdir(TARGET_DIR):
        # ---- 已存在：检查更新 ----
        print("检测到已存在 SillyTavern，正在检查版本更新...")
        print()

        local_ver = read_local_version()
        if local_ver is None:
            print("[警告] 无法读取本地版本信息(package.json 缺失或损坏)。")
            choice = input("是否删除并重新下载最新版? (y/n): ").strip().lower()
            if choice == "y":
                success = do_replace()
                if not success:
                    print()
                    print("[错误] 更新失败！请检查网络连接后重试。")
                    print(f"备用方案 - 浏览器手动下载并解压: {URL}")
                    _wait_exit()
                    return
            else:
                print("已跳过更新。")
        else:
            print("正在查询远端最新版本(需要联网)...")
            remote_ver = read_remote_version()
            if remote_ver is None:
                print("[警告] 无法获取远端最新版本(网络问题)，无法判断是否需要更新。")
                choice = input("是否删除并重新下载最新版? (y/n): ").strip().lower()
                if choice == "y":
                    success = do_replace()
                    if not success:
                        print()
                        print("[错误] 更新失败！请检查网络连接后重试。")
                        _wait_exit()
                        return
                else:
                    print("已跳过更新。")
            else:
                print(f"  本地版本: {local_ver}")
                print(f"  最新版本: {remote_ver}")
                print()
                if local_ver == remote_ver:
                    print("已是最新版本，无需更新。")
                else:
                    print(f"发现版本不同，可更新到 {remote_ver}。")
                    choice = input("是否更新? (y/n): ").strip().lower()
                    if choice == "y":
                        success = do_replace()
                        if not success:
                            print()
                            print("[错误] 更新失败！请检查网络连接后重试。")
                            print(f"备用方案 - 浏览器手动下载并解压: {URL}")
                            _wait_exit()
                            return
                    else:
                        print("已跳过更新。")
    else:
        # ---- 全新安装 ----
        success = fresh_install()
        if not success:
            print()
            print("[错误] 下载失败！请检查网络连接或代理设置后重试。")
            print(f"备用方案 - 浏览器手动下载并解压: {URL}")
            _wait_exit()
            return

    # ---- 依赖安装询问 ----
    print()
    choice = input("是否现在自动执行依赖安装 (npm install)? (y/n): ").strip().lower()
    if choice == "y":
        npm_install()
    else:
        print("已跳过依赖安装，可稍后参考文末指南手动执行。")

    print_guide()
    _wait_exit()


def _wait_exit():
    """等待用户按回车退出（双击运行时不至于窗口闪退）"""
    print()
    try:
        input("按回车键退出...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
