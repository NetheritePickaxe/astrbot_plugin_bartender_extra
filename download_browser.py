# -*- coding: utf-8 -*-
"""
自动下载并解压 Playwright 浏览器内核
策略1: 从 GitHub Release 下载预打包的 browser.zip（速度快，离线可用）
策略2: 如果 Release 下载失败，回退到 playwright install 命令在线安装
"""

import os
import sys
import subprocess
import urllib.request
import zipfile

# ======================== 配置区 ========================
# Release 下载链接（由 CI 工作流 browser-dependence.yml 自动构建并发布）
DOWNLOAD_URL = "https://github.com/NetheritePickaxe/astrbot_plugin_bartender/releases/download/browser_dependence/browser.zip"

# 下载的临时文件名
ZIP_FILENAME = "browser.zip"

# 解压目标目录（当前目录）
EXTRACT_DIR = "."

# 超时时间（秒），用于判断 Release 链接是否可达
TIMEOUT_SECONDS = 15
# ========================================================


def check_release_available(url):
    """检测 GitHub Release 链接是否可达"""
    print("正在检测 GitHub Release 是否可访问...")
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Range": "bytes=0-0"  # 只请求第一个字节，减少流量
        })
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            if status == 200 or status == 206:
                total_size = response.headers.get("Content-Range", "0/0")
                total_bytes = total_size.split("/")[-1] if "/" in total_size else "未知"
                try:
                    total_mb = int(total_bytes) // 1048576
                    print(f"✅ Release 可访问，文件大小约 {total_mb} MB\n")
                except ValueError:
                    print("✅ Release 可访问\n")
                return True
            else:
                print(f"⚠️ Release 返回状态码: {status}\n")
                return False
    except Exception as e:
        print(f"⚠️ 无法访问 GitHub Release: {e}\n")
        return False


def download_from_release(url, filename):
    """策略1: 从 GitHub Release 下载并解压"""
    print("=" * 50)
    print("  📦 方式一: 从 GitHub Release 下载")
    print("=" * 50)
    print()

    print(f"正在下载: {url}")
    print("请耐心等待...\n")

    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })

        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 8192

            with open(filename, "wb") as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)

                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        bar_length = 40
                        filled = int(bar_length * downloaded // total_size)
                        bar = "█" * filled + "-" * (bar_length - filled)
                        sys.stdout.write(
                            f"\r进度: |{bar}| {percent:.1f}% "
                            f"({downloaded // 1048576}MB / {total_size // 1048576}MB)"
                        )
                        sys.stdout.flush()
                    else:
                        sys.stdout.write(f"\r已下载: {downloaded // 1048576}MB")
                        sys.stdout.flush()

        print("\n\n✅ 下载完成！")

        # 验证文件完整性
        actual_size = os.path.getsize(filename)
        if total_size > 0 and actual_size != total_size:
            print(f"⚠️ 文件大小不匹配 (期望 {total_size} 字节, 实际 {actual_size} 字节)")
            print("可能下载不完整，将尝试解压...")
        elif actual_size < 1024:
            print(f"⚠️ 下载文件仅 {actual_size} 字节，可能不是有效压缩包")
            return False

        # 解压
        print(f"\n正在解压 {filename} ...")
        try:
            with zipfile.ZipFile(filename, "r") as zip_ref:
                file_count = len(zip_ref.namelist())
                print(f"压缩包内共有 {file_count} 个文件\n")

                for i, member in enumerate(zip_ref.namelist(), 1):
                    zip_ref.extract(member, EXTRACT_DIR)
                    if i % 50 == 0 or i == file_count:
                        percent = (i / file_count) * 100
                        sys.stdout.write(f"\r解压进度: {percent:.1f}% ({i}/{file_count})")
                        sys.stdout.flush()

            print("\n\n✅ 解压完成！")
            return True

        except zipfile.BadZipFile:
            print("\n❌ 压缩包已损坏或不完整")
            return False

    except Exception as e:
        print(f"\n❌ 下载失败: {e}")
        return False


def download_via_playwright():
    """策略2: 回退到 playwright install 命令下载"""
    print("=" * 50)
    print("  🌐 方式二: 通过 Playwright 在线下载浏览器内核")
    print("=" * 50)
    print()

    # 检查 playwright 是否已安装
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            print("❌ 未检测到 playwright 模块")
            print("正在尝试安装 playwright...")
            install_result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                timeout=120
            )
            if install_result.returncode != 0:
                print("❌ playwright 安装失败")
                return False
    except Exception:
        print("❌ 无法调用 playwright，请确认已安装: pip install playwright")
        return False

    # 设置环境变量，让浏览器下载到当前项目的 browser 目录
    env = os.environ.copy()
    project_browser_path = os.path.join(os.getcwd(), "browser")
    env["PLAYWRIGHT_BROWSERS_PATH"] = project_browser_path

    print(f"浏览器将下载到: {project_browser_path}")
    print("正在执行 playwright install chromium ...")
    print("(此过程较慢，请耐心等待)\n")

    try:
        # 实时输出安装过程
        process = subprocess.Popen(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        if process.stdout is not None:
            for line in process.stdout:
                print(f"  {line}", end="")

        process.wait()

        if process.returncode == 0:
            print("\n✅ Playwright 浏览器内核下载完成！")
            print(f"   安装位置: {project_browser_path}")
            return True
        else:
            print(f"\n❌ playwright install 执行失败 (返回码: {process.returncode})")
            return False

    except Exception as e:
        print(f"\n❌ 执行 playwright install 时出错: {e}")
        return False


def cleanup(filename):
    """清理临时文件"""
    try:
        if os.path.exists(filename):
            os.remove(filename)
            print(f"🧹 已清理临时文件: {filename}")
    except Exception as e:
        print(f"⚠️ 清理临时文件失败: {e}")


def main():
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║    Playwright 浏览器内核 下载 & 解压工具       ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    # 检查是否已经存在 browser 目录
    if os.path.isdir("browser"):
        print("📁 检测到已存在 browser 目录。")
        choice = input("   是否要覆盖重新下载？(y/n): ").strip().lower()
        if choice != "y":
            print("已取消，退出。")
            input("\n按回车键退出...")
            return
        # 删除旧目录
        print("正在清理旧的 browser 目录...")
        import shutil
        shutil.rmtree("browser", ignore_errors=True)

    success = False

    # ---- 策略1: 尝试从 GitHub Release 下载 ----
    if check_release_available(DOWNLOAD_URL):
        success = download_from_release(DOWNLOAD_URL, ZIP_FILENAME)
        # 无论成功失败，都清理临时 zip 文件
        cleanup(ZIP_FILENAME)
    else:
        print("⏭️ 跳过 Release 方式，直接尝试 Playwright 下载\n")

    # ---- 策略2: Release 失败则回退到 playwright install ----
    if not success:
        print()
        print("🔄 Release 方式不可用或失败，正在尝试备用方式...\n")
        success = download_via_playwright()

    # ---- 最终结果 ----
    print()
    print("=" * 50)
    if success:
        print("   ✅ 浏览器内核下载并解压成功！")
        print("   你现在可以正常运行插件了。")
    else:
        print("   ❌ 所有下载方式均失败！")
        print("   请手动尝试以下操作:")
        print("   1. 检查网络连接")
        print(f"   2. 手动下载: {DOWNLOAD_URL}")
        print("   3. 或手动执行: playwright install chromium")
    print("=" * 50)
    input("\n按回车键退出...")


if __name__ == "__main__":
    main()
