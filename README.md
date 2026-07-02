<div align="center">

# astrbot_plugin_bartender

_✨ [AstrBot](https://github.com/AstrBotDevs/AstrBot) 酒馆（SillyTavern）交互插件 ✨_

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-3.4%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-dragonuniverse8248-blue)](https://github.com/dragonuniverse8248)

</div>

## 🤝 介绍

**astrbot_plugin_bartender** 是一个基于 Playwright 无头浏览器库的 AstrBot 插件，通过对 [SillyTavern（酒馆）](https://github.com/SillyTavern/SillyTavern) 前端页面进行自动化操作与交互，实现在聊天机器人（QQ/微信等平台）中与酒馆 AI 角色进行对话。

插件通过操控本地或远程部署的酒馆前端页面，完成消息发送、角色切换、角色卡管理、楼层删除等操作，让用户无需直接打开酒馆页面，即可在聊天平台上无缝体验 AI 角色扮演，游戏体验高于现成的联机脚本。

### ✨ 核心特性

- 🍸 **酒馆对话**：通过 `/酒` 指令向当前角色发送消息并获取 AI 回复（合并转发形式）
- 🎭 **角色管理**：支持浏览、切换、添加、删除酒馆角色卡
- 🔄 **消息重生成**：支持重新生成最新楼层的 AI 回复
- 🗑️ **楼层管理**：支持批量删除指定数量的聊天楼层
- 🧵 **线程安全模式**：可配置的浏览器线程管理模式，避免浏览器实例冲突
- 🖥️ **跨平台支持**：兼容 Windows / Linux，自动适配浏览器可执行文件
- 🧹 **进程清理**：提供管理员指令，一键清理残留的 Chrome/Chromium 后台进程

## 🖥️ 前置运行依赖说明

> **基础依赖**：Python 3.10+ · 已部署运行的 [SillyTavern（酒馆）](https://github.com/SillyTavern/SillyTavern) · `playwright` / `aiohttp` 等 Python 包（插件安装时自动拉取）

本插件基于 Playwright 操控 Chromium 浏览器实现对酒馆页面的自动化。由于 GitHub 仓库无法直接上传体积庞大的浏览器可执行文件，因此**需要用户自行获取浏览器内核**。

插件启动时会按以下优先级查找浏览器：
1. **插件目录 `browser/` 文件夹** → 手动放置或脚本下载的浏览器
2. **Playwright 默认缓存路径** → 通过 `playwright install chromium` 安装的浏览器

> 💡 推荐使用项目自带的**自动下载脚本**，一键完成下载与解压。

---

### 🔧 方式一：一键安装脚本（推荐 ⭐）

插件根目录自带了三个下载脚本，**无需手动操作**，脚本会自动完成检测→下载→解压全部流程：

| 脚本文件 | 适用系统 | 使用方法 |
|:--------|:--------:|:--------|
| **`download_browser.bat`** | Windows | 双击运行，或在终端执行 `.\download_browser.bat` |
| **`download_browser.sh`** | Linux / macOS | 在终端执行 `bash download_browser.sh` |
| **`download_browser.py`** | 跨平台通用 | 在终端执行 `python download_browser.py`（Linux/Mac 用 `python3`） |

#### 一步一步跟我做

**Windows 用户：**

1. 打开插件目录（例如 `AstrBot/data/plugins/astrbot_plugin_bartender/`）
2. 双击运行 **`download_browser.bat`**
3. 等待脚本自动下载并解压，控制台会显示实时进度条
4. 完成后，插件目录下会出现一个 **`browser/`** 文件夹，里面包含 `chrome.exe` 和大量配套文件

```
astrbot_plugin_bartender/
├── download_browser.bat   ← 双击这个！
├── download_browser.py
├── download_browser.sh
├── main.py
├── browser/               ← 脚本自动生成的文件夹
│   ├── chrome.exe
│   ├── chrome.dll
│   └── ... (其他配套文件)
└── ...
```

**Linux / macOS 用户：**

1. 打开终端，进入插件目录：
   ```bash
   cd AstrBot/data/plugins/astrbot_plugin_bartender
   ```
2. 运行下载脚本：
   ```bash
   bash download_browser.sh
   ```
3. 等待完成后，使用 `ls browser/` 确认 `chrome` 可执行文件已存在

> 💡 如果 `browser/` 文件夹已存在，脚本会询问是否覆盖重新下载，输入 `y` 回车即可。脚本运行结束后会自动清理临时下载的 `browser.zip`，不会留下垃圾文件。



---

### 📦 方式二：手动下载 GitHub Releases 压缩包

1. 前往 [GitHub Releases](https://github.com/dragonuniverse8248/astrbot_plugin_bartender/releases) 页面
2. 下载 `browser.zip` 压缩包
3. 将压缩包解压到插件根目录，确保最终目录结构为：

```
astrbot_plugin_bartender/
└── browser/
    ├── chrome.exe    # Windows
    └── chrome        # Linux/macOS（以及 chrome 相关 .dll/.pak 等文件）
```

---

### 🌐 方式三：通过 Playwright 官方渠道下载

如果你已安装 `playwright` 模块，直接运行以下命令即可：

```bash
playwright install chromium
```

> 💡 插件启动时会自动检测 Playwright 默认缓存路径中的 Chromium，无需指定下载目录，默认安装即可。
>
> ⚠️ 此方式需要网络能正常访问 Playwright 的 CDN 下载源。若下载缓慢或失败，建议使用方式一或方式二。

## 📦 安装插件

- 可以直接在 AstrBot 的插件市场搜索 `astrbot_plugin_bartender`，点击安装，耐心等待安装完成即可
- 也可以手动安装：

```bash
# 克隆仓库到插件目录
cd /AstrBot/data/plugins
git clone https://github.com/dragonuniverse8248/astrbot_plugin_bartender

# 控制台重启AstrBot
```

## ⌨️ 使用说明

### 指令命令表

|       指令       |            参数            |                    说明                    |
|:---------------:|:--------------------------:|:------------------------------------------:|
| `/酒 [文字内容]` | 要发送的消息文本 | 向当前酒馆角色发送消息并获取 AI 回复，不支持图片输入 |
| `/酒切换 [名字]` | 目标角色卡名称 | 切换当前对话角色卡，名称需在角色列表中 |
| `/酒删除 [楼层数]` | 要删除的楼层数量（可选，默认1） | 删除指定数量的最新聊天楼层，建议至少2层（含用户输入） |
| `/酒加卡 [图片]` | PNG 格式角色卡图片 | 上传角色卡到酒馆；可附带图片一起发送，也可先发指令后补发图片 |
| `/酒删卡 [名字]` | 目标角色卡名称 | 删除指定角色卡，若删除的是当前角色则自动切换至默认卡 |
| `/酒重新` | 无 | 重新生成当前最新楼层的 AI 回复 |
| `/酒查看` | 无 | 查看最新楼层的消息并与当前楼层总数 |
| `/酒状态` | 无 | 查看当前角色卡、角色列表及浏览器连接状态 |
| `/酒关闭` | 无 | 调试指令，手动关闭运行中的浏览器实例 |
| `/酒帮助` | 无 | 显示所有指令的帮助信息 |
| `/酒重置` | 🔒 管理员 | 重置插件所有全局变量，恢复默认角色，重新获取角色列表 |
| `/酒进程` | 🔒 管理员 | 强制清理后台所有 Chrome/Chromium 进程（需在配置中开启） |

> 🔒 标记为管理员指令，仅管理员可执行。

### 使用示例

|        场景         |                     输入                     |            说明            |
|:-------------------:|:--------------------------------------------:|:--------------------------|
|    基础对话    | `/酒 你好，今天天气怎么样？`           | 向当前角色发送消息并获取 AI 回复 |
|    切换角色    | `/酒切换 Seraphina`                     | 切换到名为 Seraphina 的角色卡 |
|    删除楼层    | `/酒删除 2`                             | 删除最近的 2 层聊天楼层       |
|  添加角色卡  | 先发 `/酒加卡`，再在等待时间内发送图片 | 支持分步操作，无需一次发送     |
|  查看状态    | `/酒状态`                                | 查看角色、列表和浏览器状态    |
| 重新生成回复 | `/酒重新`                                | 重新生成最新楼层的 AI 回复    |

### 消息监听说明

当用户先发送 `/酒加卡` 指令（未附带图片）时，插件会为该用户开启一个计时等待窗口，在配置的时间间隔内，用户单独发送一张 PNG 图片即可自动完成角色卡上传。超时后等待状态自动取消。

## ⚙️ 配置

进入 AstrBot 插件配置面板进行配置：

| 配置项 | 类型 | 默认值 | 说明 |
|:------|:----:|:------|:----|
| `browser_ip` | string | `http://127.0.0.1` | 酒馆前端页面的 IP 地址 |
| `browser_port` | string | `8000` | 酒馆前端页面的端口号 |
| `now_chats_name` | string | `Seraphina` | 当前默认使用的角色卡名称 |
| `browser_Visible` | bool | `true` | 浏览器可视化模式（`true` 为无头模式，`false` 为显示窗口） |
| `browser_delay` | int | `0` | 浏览器操作的慢动作延迟（毫秒），用于调试 |
| `thread_safe_mode` | bool | `false` | 线程安全模式：每次操作前后自动开启/关闭浏览器 |
| `upload_interval` | int | `30` | 上传角色卡时的等待时间（秒），超时自动取消 |
| `kill_Process` | bool | `false` | 是否允许执行 `/酒进程` 管理员指令 |

> ⚠️ **注意**：`thread_safe_mode` 开启后，每次命令执行前后都会重新启动和关闭浏览器，对性能有一定影响，但能避免多用户并发时的浏览器实例冲突。单用户场景建议关闭以提升响应速度。

## 📌 注意事项

- 插件需要已部署并运行中的 **SillyTavern（酒馆）** 前端页面，请确保 `browser_ip` 和 `browser_port` 配置正确
- 若插件目录 `browser/` 下找不到浏览器，会自动降级尝试使用 **Playwright 默认缓存**中的 Chromium；若两处都没有，插件启动将报错，请参考上方「前置运行依赖说明」获取浏览器
- 角色卡上传仅支持 **PNG 格式** 的角色卡图片文件
- 删除楼层时建议至少删除 **2 层**（包含用户输入层和 AI 回复层），删除最底层（1层且仅有1层）将不生效
- 默认角色卡 `Seraphina` 不可删除，受到保护
- Linux/Docker 环境下启动浏览器需要 `--no-sandbox` 等参数，插件已内置处理
- 插件运行依赖 `playwright`、`aiohttp` 等第三方库，请确保已安装依赖

## 🔧 技术架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  AstrBot    │────▶│  QQ/微信等    │────▶│  终端用户        │
│  消息平台   │     │  聊天平台     │     │  (发送指令)      │
└──────┬──────┘     └──────────────┘     └─────────────────┘
       │
       │ 插件系统
       ▼
┌──────────────────────────────────────┐
│  astrbot_plugin_bartender            │
│  ┌────────────────────────────┐     │
│  │  bartender_crawler (Star)   │     │
│  │  ├─ 浏览器生命周期管理      │     │
│  │  ├─ 酒馆页面操作            │     │
│  │  ├─ 角色卡管理              │     │
│  │  └─ 图片落地与清理          │     │
│  └────────────────────────────┘     │
└──────────────┬───────────────────────┘
               │ Playwright (无头浏览器)
               ▼
┌──────────────────────────────────────┐
│  SillyTavern 酒馆前端页面             │
│  └─ AI 角色对话 & 角色卡管理          │
└──────────────────────────────────────┘
```

## 👥 贡献指南

- 🌟 **Star** 这个项目！（点右上角的星星，感谢支持！）
- 🐛 提交 **Issue** 报告问题或 Bug
- 💡 提出**新功能建议**
- 🔧 提交 **Pull Request** 改进代码

## 📄 开源协议

本项目基于 [MIT License](https://opensource.org/licenses/MIT) 开源。
