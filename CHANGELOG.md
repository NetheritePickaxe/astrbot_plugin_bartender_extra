# Changelog

所有版本变更均记录在此文件中。

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 格式。

本项目是 [dragonuniverse8248/astrbot_plugin_bartender](https://github.com/dragonuniverse8248/astrbot_plugin_bartender) 的 Fork 增强分支。

---

## [v2.0.0-beta] — 2026-08-23

### 新增
- 配置项 `thread_safe_mode` 更名为 `low_memory_mode`（低内存占用模式）
- 浏览器无头模式默认开启（`browser_Visible` 默认值由 `false` 改为 `true`）

### 变更
> **⚠️ 配置迁移提示**：升级后 `thread_safe_mode` 旧键失效，该设置将重置为默认关闭；如需重新启用请在 AstrBot 插件配置中手动开启 `low_memory_mode`。`browser_Visible` 沿用用户已保存值，未修改过的用户将自动生效为无头模式。

---

## [v1.6.1] — 2026-08-23

### 新增
- `/酒世界书` 全量 i18n 翻译（usage/detail_header/detail_count/entry_item/action_on+off/toggled/toggle_fail/current_chat/active_list/all_header/empty_list/selector_missing）
- `/酒人设` 分支补全 i18n（bind_usage / view_not_found / unknown_sub / field_name/field_avatar/field_position/field_desc/empty_desc）
- `toggle_world_info` JS evaluate 返回值结构化（`{ok, code}` / `{ok, was}`），Python 侧统一走 `self.t()` 翻译，彻底关闭翻译漏洞
- 插件名称由「调酒师」改为「调酒师-增强」（metadata.yaml + i18n zh-CN / en-US）
- README 新增「🆕 本项目新增功能」章节（10 项增强特性）
- README 介绍段声明为 dragonuniverse8248/astrbot_plugin_bartender 的 Fork 增强分支
- README 使用示例补充 3 行新指令；修正 Releases/Git 仓库链接至 NetheritePickaxe 主仓库

### 修改
- WebUI 酒馆页面参考 SillyTavern 官方视觉风格重写（强制深色主题、glassmorphism、amber/gold 强调色）
- WebUI 新增一键安装 SillyTavern 按钮（后台 subprocess 调用 download_sillytavern.py，2s 轮询状态）
- 异常兜底统一使用 i18n 键：`chat.error.exec`、`chat.busy.shake`、`chat.chrome.stat_fail`、`_t_status("无角色卡")`
- `chat.state.none` 键复用（替代硬编码的 "无"）

---

## [v1.6.0] — 2026-08-23

### 新增
- `/酒人设 绑定 [名字]` — 当前用户绑定酒馆人设，后续 `/酒` 自动切换
- `/酒人设 查看 [名字]` — 查看人设详情（名称、头像ID、位置、描述）
- `/酒世界书` — 列出所有世界书及已启用列表
- `/酒世界书 查看 [名字]` — 查看世界书条目详情
- `/酒世界书 切换 [名字]` — 一键启用/禁用指定世界书
- i18n 框架（支持 zh-CN / en-US）

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

本项目 fork 自 [dragonuniverse8248/astrbot_plugin_bartender](https://github.com/dragonuniverse8248/astrbot_plugin_bartender)

---

## 版本说明

- **[Unreleased]**：暂存区中的未发布改动
- **[v1.6.1]**：[bce4d4e...ad94201]
- **[v1.6.0]**：[bda220f...c2783b5]
- **[v1.5.0]**：[1b5f2b2]
- **[v1.3.0]**：[b714e8f]
- **[v1.0.4]**：[1970e83...ddfda1a]
