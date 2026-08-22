@echo off
chcp 65001 >nul
setlocal

set "URL=https://github.com/SillyTavern/SillyTavern/archive/refs/heads/release.zip"
set "ZIPFILE=st-release.zip"
set "EXTRACTED_DIR=SillyTavern-release"
set "TARGET_DIR=SillyTavern"
set "BACKUP_DIR=st_data_backup"

echo.
echo ============================================================
echo     SillyTavern 一键下载脚本(release 稳定版)
echo ============================================================
echo.

:: ==================== 工具检查 ====================
set "HAS_CURL=0"
where curl >nul 2>nul && set "HAS_CURL=1"
set "HAS_TAR=0"
where tar >nul 2>nul && set "HAS_TAR=1"
where powershell >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 PowerShell,无法继续.
    echo.
    pause
    exit /b 1
)

:: ==================== 已存在则检查更新,否则全新下载 ====================
if exist "%TARGET_DIR%" goto UPDATE_CHECK
goto FRESH_INSTALL

:FRESH_INSTALL
echo 未检测到 SillyTavern,将进行全新下载安装.
echo.
call :DO_DOWNLOAD
if errorlevel 1 goto DOWNLOAD_FAIL
call :DO_EXTRACT
if errorlevel 1 goto EXTRACT_FAIL
ren "%EXTRACTED_DIR%" "%TARGET_DIR%"
if %errorlevel% neq 0 goto RENAME_FAIL
del "%ZIPFILE%" >nul 2>nul
echo.
echo [成功] SillyTavern 下载完成!
goto ASK_INSTALL

:UPDATE_CHECK
echo 检测到已存在 SillyTavern,正在检查版本更新...
echo.

:: ---- 读取本地版本 ----
set "LOCAL_VER="
if not exist "%TARGET_DIR%\package.json" goto LOCAL_UNKNOWN
powershell -NoProfile -Command "try { (Get-Content '%TARGET_DIR%\package.json' -Raw | ConvertFrom-Json).version } catch {}" > "%TEMP%\st_local_ver.txt" 2>nul
set /p LOCAL_VER=< "%TEMP%\st_local_ver.txt"
del "%TEMP%\st_local_ver.txt" >nul 2>nul
if "%LOCAL_VER%"=="" goto LOCAL_UNKNOWN

:: ---- 获取远端最新版本 ----
echo 正在查询远端最新版本(需要联网)...
set "REMOTE_VER="
powershell -NoProfile -Command "try { (Invoke-RestMethod 'https://api.github.com/repos/SillyTavern/SillyTavern/releases/latest' -UseBasicParsing).tag_name } catch {}" > "%TEMP%\st_remote_ver.txt" 2>nul
set /p REMOTE_VER=< "%TEMP%\st_remote_ver.txt"
del "%TEMP%\st_remote_ver.txt" >nul 2>nul
if "%REMOTE_VER%"=="" goto REMOTE_UNKNOWN

echo   本地版本: %LOCAL_VER%
echo   最新版本: %REMOTE_VER%
echo.

if "%LOCAL_VER%"=="%REMOTE_VER%" goto ALREADY_LATEST

echo 发现版本不同,可更新到 %REMOTE_VER%.
echo 是否更新 y/n:
set /p DO_UPDATE=
if /i not "%DO_UPDATE%"=="y" goto ASK_INSTALL
goto DO_REPLACE

:LOCAL_UNKNOWN
echo [警告] 无法读取本地版本信息.
echo 是否删除并重新下载最新版 y/n:
set /p REINSTALL=
if /i "%REINSTALL%"=="y" goto DO_REPLACE
echo 已跳过更新.
goto ASK_INSTALL

:REMOTE_UNKNOWN
echo [警告] 无法获取远端最新版本(网络问题),无法判断是否需要更新.
echo 是否删除并重新下载最新版 y/n:
set /p REINSTALL=
if /i "%REINSTALL%"=="y" goto DO_REPLACE
goto ASK_INSTALL

:ALREADY_LATEST
echo 已是最新版本,无需更新.
goto ASK_INSTALL

:: ==================== 替换更新(保留用户数据)====================
:DO_REPLACE
set "HAS_CONFIG=0"
echo.
echo 正在备份用户数据(data 目录与 config.yaml)...
if exist "%TARGET_DIR%\data" move /Y "%TARGET_DIR%\data" "%BACKUP_DIR%" >nul 2>nul
if not exist "%TARGET_DIR%\config.yaml" goto BACKUP_DONE
set "HAS_CONFIG=1"
move /Y "%TARGET_DIR%\config.yaml" "config.yaml.bak" >nul 2>nul
:BACKUP_DONE

echo 正在删除旧版本代码...
rmdir /s /q "%TARGET_DIR%" 2>nul

echo 正在下载新版...
call :DO_DOWNLOAD
if errorlevel 1 goto DOWNLOAD_FAIL
call :DO_EXTRACT
if errorlevel 1 goto EXTRACT_FAIL
ren "%EXTRACTED_DIR%" "%TARGET_DIR%"
if %errorlevel% neq 0 goto RENAME_FAIL

echo 正在还原用户数据...
if not exist "%BACKUP_DIR%" goto RESTORE_CONFIG
if exist "%TARGET_DIR%\data" rmdir /s /q "%TARGET_DIR%\data" 2>nul
move /Y "%BACKUP_DIR%" "%TARGET_DIR%\data" >nul 2>nul
:RESTORE_CONFIG
if "%HAS_CONFIG%"=="1" move /Y "config.yaml.bak" "%TARGET_DIR%\config.yaml" >nul 2>nul
del "%ZIPFILE%" >nul 2>nul

echo.
echo [成功] SillyTavern 更新完成!
echo 提示:代码已更新,建议重新执行依赖安装(node_modules 已被替换).
goto ASK_INSTALL

:DOWNLOAD_FAIL
echo.
echo [错误] 下载失败!请检查网络连接或代理设置后重试.
echo 备用方案 - 浏览器手动下载并解压:
echo   %URL%
echo.
pause
exit /b 1

:EXTRACT_FAIL
echo.
echo [错误] 解压失败!
echo.
pause
exit /b 1

:RENAME_FAIL
echo.
echo [错误] 重命名 %EXTRACTED_DIR% 为 %TARGET_DIR% 失败!
echo 可能 %TARGET_DIR% 目录已被占用,请手动处理.
echo.
pause
exit /b 1

:: ==================== 依赖安装询问 ====================
:ASK_INSTALL
echo.
echo 是否现在自动执行依赖安装 (npm install) y/n:
set /p INSTALL_DEPS=
if /i "%INSTALL_DEPS%"=="y" goto CHECK_NODE
echo 已跳过依赖安装,可稍后参考文末指南手动执行.
goto GUIDE

:: ==================== Node.js 检查 ====================
:CHECK_NODE
where node >nul 2>nul
if %errorlevel% neq 0 goto NODE_MISSING

for /f "delims=v. tokens=1" %%a in ('node -v') do set NODE_MAJOR=%%a
if "%NODE_MAJOR%"=="" goto NODE_MISSING
if %NODE_MAJOR% LSS 18 goto NODE_TOO_OLD

echo [信息] 检测到 Node.js 版本符合要求.
cd "%TARGET_DIR%"
echo.
echo 正在安装依赖(可能需要几分钟,取决于网络速度)...
echo.
call npm install --no-audit --no-fund
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败!请检查上方报错信息.
    echo 常见原因:网络问题,可尝试配置镜像后重试:
    echo   npm config set registry https://registry.npmmirror.com
    cd ..
    pause
    exit /b 1
)
echo.
echo [成功] SillyTavern 依赖安装完成!
cd ..
goto GUIDE

:: ==================== Node.js 缺失处理 ====================
:NODE_MISSING
echo.
echo [警告] 未检测到 Node.js(SillyTavern 要求 Node.js 18 或更高版本).
echo 是否尝试通过 winget 自动安装 Node.js LTS y/n:
set /p AUTO_INSTALL_NODE=
if /i "%AUTO_INSTALL_NODE%"=="y" goto TRY_WINGET
goto NODE_MANUAL

:TRY_WINGET
where winget >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 winget,无法自动安装.
    goto NODE_MANUAL
)
echo 正在通过 winget 安装 Node.js LTS(约需几分钟)...
winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
if %errorlevel% neq 0 (
    echo [错误] winget 安装失败.
    goto NODE_MANUAL
)
echo.
echo [成功] Node.js 安装完成!
echo.
echo 重要提示:环境变量 PATH 需要重新加载才能生效.
echo 请关闭本窗口,重新打开终端后再次运行本脚本,
echo 选择继续完成依赖安装即可.
echo.
pause
exit /b 0

:NODE_MANUAL
echo.
echo 请手动安装 Node.js LTS(18 或更高版本):
echo   下载地址: https://nodejs.org/
echo 安装完成后重新运行本脚本即可继续.
echo.
pause
exit /b 1

:NODE_TOO_OLD
echo.
echo [警告] 当前 Node.js 版本过低(检测到主版本 %NODE_MAJOR%,要求大于等于 18).
echo 请升级 Node.js 后重试: https://nodejs.org/
echo.
pause
exit /b 1

:: ==================== 完成指南 ====================
:GUIDE
echo.
echo ============================================================
echo   SillyTavern 使用指南
echo ============================================================
echo.
echo   1. 进入目录:   cd SillyTavern
echo   2. 安装依赖:   npm install
echo   3. 启动服务:   运行 Start.bat (或命令行执行 node server.js)
echo.
echo   启动成功后默认地址为: http://127.0.0.1:8000
echo.
echo   请在本插件(调酒师)的配置中设置:
echo     browser_ip   = http://127.0.0.1
echo     browser_port = 8000
echo.
echo   说明:本脚本通过下载 Release 源码包安装,更新时重新下载替换,
echo         用户数据(data 目录与 config.yaml)会自动保留.
echo ============================================================
echo.
pause
exit /b 0

:: ==================== 下载子程序 ====================
:DO_DOWNLOAD
if "%HAS_CURL%"=="1" (
    curl -fSL --retry 3 --retry-delay 5 -o "%ZIPFILE%" "%URL%"
    if not errorlevel 1 exit /b 0
    echo [警告] curl 下载失败,尝试 PowerShell...
)
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIPFILE%' -UseBasicParsing } catch { exit 1 }"
exit /b %errorlevel%

:: ==================== 解压子程序 ====================
:DO_EXTRACT
if "%HAS_TAR%"=="1" (
    tar -xf "%ZIPFILE%"
    if not errorlevel 1 exit /b 0
    echo [警告] tar 解压失败,尝试 PowerShell...
)
powershell -NoProfile -Command "try { Expand-Archive -Path '%ZIPFILE%' -DestinationPath '.' -Force } catch { exit 1 }"
exit /b %errorlevel%
