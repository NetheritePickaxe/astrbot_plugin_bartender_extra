# 更新日志

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
