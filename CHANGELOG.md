# 更新日志

## [v1.6.8] — 2026-08-24

### 修复
- 修复内嵌酒馆 UI 与真实 webui 完全不同（控制台 `$ is not defined`、ST 渲染坏掉）的问题：Dashboard 用沙箱 iframe 内嵌，ST 处于不透明源；helmet 默认的 `Cross-Origin-Resource-Policy: same-origin` 把 ST 自身脚本（jQuery 等）当跨域拦掉，导致脚本全失效、UI 退化成裸 HTML
- `_patch_st_frameguard` 升级为 `_patch_st_helmet`：除 `frameguard` 外再关闭 `crossOriginResourcePolicy` / `crossOriginOpenerPolicy` / `originAgentCluster`，去掉这三个响应头 → 沙箱 iframe 内 ST 脚本正常加载，渲染与真实 webui 一致；ST API 走 CORS（`cors.origin: ["null"]` 显式允许不透明源）→ 设置仍可服务端持久化

---

## [v1.6.7] — 2026-08-24

### 修复
- 修复「安装酒馆」报「依赖未安装」的问题：v1.6.6 把相对路径 `self.st_dir` 传给 `download_sillytavern.py` 作为 `TARGET_DIR`，脚本以自身 cwd（持久父目录）为基准解析，导致 `os.rename` 目标嵌套为 `data/.../data/.../SillyTavern`、父目录不存在而失败（WinError 3）。现 `self.st_dir` 在 `__init__` 即 `.resolve()` 为绝对路径，脚本拿到绝对 `TARGET_DIR`，`os.rename` 与 `npm install` 的 cwd 均正确，安装全自动跑通

---

## [v1.6.6] — 2026-08-24

### 变更
- SillyTavern 安装位置由插件目录（`plugin_dir/SillyTavern`）迁至持久数据目录 `data/<插件名>/SillyTavern`（AstrBot 全局 data 下，与 plugins 同级），插件更新不再删除内置酒馆及其角色/聊天/配置数据
- `__init__` 新增 `self.st_dir` 持久路径，并调用 `_migrate_legacy_st` 自动迁移旧位置（一次性安全网）
- `_install_tavern_bg` 下载/解压/安装均在持久位置进行（subprocess 传入持久绝对路径，cwd 设为持久父目录）
- `download_sillytavern.py` 支持命令行参数指定安装目录：`TARGET_DIR = argv[1] or "SillyTavern"`
- `.gitignore` 补 `SillyTavern/`

### 升级须知
- 更新到 v1.6.6 前，建议先手动搬一次：把 `data/plugins/astrbot_plugin_bartender_extra/SillyTavern` 移到 `data/astrbot_plugin_bartender_extra/SillyTavern`，避免更新清空插件目录时数据丢失
- 若 AstrBot 更新保留了未跟踪文件，新版 `__init__` 会自动迁移，无需手动操作

---

## [v1.6.5] — 2026-08-24

### 修复
- 修复面板 iframe 无法内嵌酒馆、浏览器显示「127.0.0.1 拒绝连接」的问题：SillyTavern 1.18.0 经 helmet 默认发送 `X-Frame-Options: SAMEORIGIN`，与面板（不同源）跨域 iframe 冲突。插件现于启动 ST 前幂等修补 `SillyTavern/src/server-main.js`，给 `helmet({...})` 补 `frameguard: false`，去掉该响应头，允许面板内嵌

### 变更
- `start_tavern` 在拉起 `node server.js` 前调用 `_patch_st_frameguard` 幂等打补丁（每次启动检查，能扛住 ST 重新下载覆盖）

---

## [v1.6.4] — 2026-08-24

### 修复
- 修复 Windows 下「安装酒馆」`npm install` 始终失败的问题：`subprocess.run(["npm", ...])` 在 `shell=False` 时 Windows 的 CreateProcess 无法解析 `npm.cmd`（只试 `.exe`），导致 `node_modules` 缺失、酒馆启动即崩（`ERR_MODULE_NOT_FOUND: yargs`）。改为 Windows 下 `shell=True` 经 cmd.exe 按 PATHEXT 解析 npm.cmd，Linux 保持 list 形式
- 修复 `start_tavern` 中 `proc.wait()` 无限阻塞事件循环的潜在问题：server.js 成功启动后会永久挂起，现移除该阻塞，改为就绪轮询后正常返回

### 变更
- `/酒启动` 与 WebUI「启动酒馆」在检测到 `node_modules` 缺失时自动执行 `npm install`（线程池执行，不阻塞事件循环），无需用户手动安装依赖
- WebUI 安装状态准确性：`_install_tavern_bg` 在进程退出码为 0 时校验 `node_modules` 是否存在，缺失则标记 `failed: 依赖未安装`，避免误报「安装完成」

---

## [v1.6.3] — 2026-08-24

### 移除
- 移除浏览器手动下载机制：删除 `download_browser.{py,bat,sh}` 脚本与 `.github/workflows/browser-dependence.yml` CI 工作流，并删除 GitHub `browser_dependence` Release（含本地与远端标签）
- 不再依赖插件目录下的 `browser/` 文件夹或 `executable_path` 指定本地浏览器

### 变更
- 浏览器改由 Playwright 默认 Chromium 提供（参考 `astrbot_plugin_steaminfo_xiaoheihe` 同方案），AstrBot 环境通常已内置，无需手动下载；缺失时执行一次 `playwright install chromium` 即可
- `main.py` 移除 `self.browser_dir` 属性与本地 `chrome.exe`/`chrome` 查找逻辑，`chromium.launch()` 不再传 `executable_path`
- 浏览器启动失败错误提示更新为引导执行 `playwright install chromium`
- README「前置运行依赖说明」重写为单段说明，移除原三种获取浏览器教程

### 修复
- WebUI 页面 `:root` 深色变量对齐 SillyTavern 官方暗色调色板（近黑底 `#171717` + 象牙白 `#dcdcd2` + 琥珀强调 `#e18a24`），修复此前的深蓝色调问题；浅色主题保持不变

---

## [v1.6.2] — 2026-08-23

### 移除
- 配置项 `language` 回复语言配置项；回复文案统一为简体中文硬编码
- 配置项 `thread_safe_mode` 更名为 `low_memory_mode`（低内存占用模式）；老用户需重新配置
- 浏览器无头模式默认开启（`browser_Visible` 默认值由 `false` 改为 `true`）
- README 指令列表合并英文别名列，移除独立别名章节

### 修复
- 修复 metadata.yaml `display_name` 回归（恢复「调酒师-增强」）与 `short_desc` 缺失

### 变更
- 配置面板按功能分组（酒馆设置 / 基础设置 / 权限管理）
- 优化低内存占用模式配置描述文案
- 指令重整：`/酒停止生成` 更名为 `/酒中断`；`/酒关闭` 更名为 `/酒停止` 且同时关闭酒馆主程序（node 进程）；`/酒进程` 新增「停止」子命令（仅关闭浏览器进程）；移除 `/酒改名`
- 新增 `/酒重启` 指令：先停止后启动插件目录中的酒馆，完成后自动连接浏览器（与 WebUI 重启按钮同能力）

### 新增
- README 添加动态版本徽章（读 metadata.yaml 自动同步）
- `/酒加卡` 支持文字建卡：`/酒加卡 名字 [角色描述] [开场白]`，中括号内可含空格与换行，无需图片直接创建角色卡（纯 Python 生成 V2 角色卡 PNG 走标准导入流程）
- `/酒加卡` 支持更新已有角色卡：同名卡存在时按括号参数覆盖描述/开场白（整卡对象回传，避免未提供字段被酒馆置空）；特殊值 `[/]`=保留原值、`[]`=清空、省略括号=不改
- `/酒人设 修改 名字 [内容]` 同步括号语法：内容用中括号包裹防止空格换行出错
- `/酒导出 data` 整库备份：打包内置酒馆 `data` 目录（排除 `backups/`）为 zip 发送 QQ 文件；超过 2 GB 拒绝；仅管理员可用，异步打包防阻塞，保留最新一个备份
- `/酒导出` 整体升级为管理员指令（无参导出当前聊天 JSONL 亦需管理员权限）
- WebUI 主题修复：`:root` 默认深色（与 SillyTavern 官方暗色一致），`[data-theme="light"]` 浅色覆盖；bridge 自动处理 `data-theme` 跟随面板主题；补 `applyLang()` 语言同步与 `bridge.onContext` 回调注册

> **⚠️ 配置迁移提示**：升级后 `thread_safe_mode` 旧键失效，该设置将重置为默认关闭；如需重新启用请在 AstrBot 插件配置中手动开启 `low_memory_mode`。`browser_Visible` 沿用用户已保存值，未修改过的用户将自动生效为无头模式。

---

## [v1.6.1] — 2026-08-23

### 新增
- `/酒世界书` 输出文案补全（usage/detail_header/detail_count/entry_item/action_on+off/toggled/toggle_fail/current_chat/active_list/all_header/empty_list/selector_missing）
- `/酒人设` 分支输出文案补全（绑定用法提示、查看未找到、未知子命令、详情字段标签等）
- `toggle_world_info` JS evaluate 返回值结构化（`{ok, code}` / `{ok, was}`），Python 侧统一处理状态文案输出
- 插件名称由「调酒师」改为「调酒师-增强」（metadata.yaml）
- README 新增「🆕 本项目新增功能」章节（10 项增强特性）
- README 介绍段声明为 dragonuniverse8248/astrbot_plugin_bartender 的 Fork 增强分支
- README 使用示例补充 3 行新指令；修正 Releases/Git 仓库链接至 NetheritePickaxe 主仓库

### 修改
- WebUI 酒馆页面参考 SillyTavern 官方视觉风格重写（强制深色主题、glassmorphism、amber/gold 强调色）
- WebUI 新增一键安装 SillyTavern 按钮（后台 subprocess 调用 download_sillytavern.py，2s 轮询状态）
- 统一异常兜底与状态文案输出（执行异常、指令忙碌、状态获取失败等场景）

---

## [v1.6.0] — 2026-08-23

### 新增
- `/酒人设 绑定 [名字]` — 当前用户绑定酒馆人设，后续 `/酒` 自动切换
- `/酒人设 查看 [名字]` — 查看人设详情（名称、头像ID、位置、描述）
- `/酒世界书` — 列出所有世界书及已启用列表
- `/酒世界书 查看 [名字]` — 查看世界书条目详情
- `/酒世界书 切换 [名字]` — 一键启用/禁用指定世界书

---

## [v1.5.0] — 2026-08-23

### 新增
- 酒馆聊天模式：`/酒开始 [群聊]` 开启后无需指令前缀直接发送；`/酒结束` 退出
- 权限控制：`/酒权限` 在线管理管理员/群白名单/黑名单
- 指令改名：`/酒加卡` → 仍保留；`/酒启动` / `/酒停止` 新增；`/酒进程` 逻辑改为查看进程状态

---

## [v1.3.0] — 2026-08-23

### 新增
- WebUI 插件页面（AstrBot 面板内嵌，支持状态检测、启动/关闭浏览器）
- 人设系统（Persona）：创建、修改、删除、绑定、解绑
- 8 条新指令

---

## [v1.0.4] — 2026-08-22

### 新增
- 项目重命名为 `astrbot_plugin_bartender_extra`
- `/酒加卡` / `/酒查看` 支持引用消息定位楼层
- `/酒启动` — 启动浏览器与酒馆
- `/酒停止` — 停止浏览器
- Python 版 `download_sillytavern.py`
- browser.zip 自动构建 CI 工作流

### 修改
- `/酒进程` 逻辑调整为查看进程状态

---

## [v1.0.3] — 原项目版本

fork 自 [dragonuniverse8248/astrbot_plugin_bartender](https://github.com/dragonuniverse8248/astrbot_plugin_bartender)
