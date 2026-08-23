<div align="center">

# astrbot_plugin_bartender_extra

_✨ [AstrBot](https://github.com/AstrBotDevs/AstrBot) 酒馆（SillyTavern）交互插件 ✨_

[![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FNetheritePickaxe%2Fastrbot_plugin_bartender_extra%2Fmain%2Fmetadata.yaml&query=%24.version&label=%E7%89%88%E6%9C%AC&color=blueviolet)](https://github.com/NetheritePickaxe/astrbot_plugin_bartender_extra/releases)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-3.4%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-dragonuniverse8248-blue)](https://github.com/dragonuniverse8248)

</div>

## 🤝 介绍

本项目是 [dragonuniverse8248/astrbot_plugin_bartender](https://github.com/dragonuniverse8248/astrbot_plugin_bartender) 的 **Fork 增强分支**，在原项目基础上新增了 WebUI 页面、人设绑定、世界书管理、聊天模式等功能。

**astrbot_plugin_bartender_extra** 是一个基于 Playwright 无头浏览器库的 AstrBot 插件，通过对 [SillyTavern（酒馆）](https://github.com/SillyTavern/SillyTavern) 前端页面进行自动化操作与交互，实现在聊天机器人（QQ/微信等平台）中与酒馆 AI 角色进行对话。

插件通过操控本地或远程部署的酒馆前端页面，完成消息发送、角色切换、角色卡管理、楼层删除等操作，让用户无需直接打开酒馆页面，即可在聊天平台上无缝体验 AI 角色扮演，游戏体验高于现成的联机脚本。

### ✨ 核心特性

- 🍸 **酒馆对话**：通过 `/酒` 指令向当前角色发送消息并获取 AI 回复（合并转发形式）
- 🎭 **角色管理**：支持浏览、切换、添加、删除酒馆角色卡
- 👤 **用户人设绑定**：每个用户可绑定独立的酒馆人设（User Persona），发送消息时自动切换
- 🔄 **消息重生成**：支持重新生成最新楼层的 AI 回复
- 🗑️ **楼层管理**：支持批量删除指定数量的聊天楼层
- 🔌 **低内存占用模式**：可选的低内存运行方式，指令执行时临时开关浏览器、不常驻内存
- 🖥️ **跨平台支持**：兼容 Windows / Linux，自动适配浏览器可执行文件
- 🧹 **进程清理**：提供管理员指令，一键清理残留的 Chrome/Chromium 后台进程

### 🆕 本项目新增功能

基于原项目，本增强分支额外提供：

- 🖥️ **WebUI 插件页面**：AstrBot 面板内直接内嵌酒馆 WebUI，支持状态检测、一键启动/一键安装 SillyTavern（需 AstrBot ≥ v4.24.2）
- 💬 **酒馆聊天模式**：`/酒开始 [群聊]` 开启后无需指令前缀，直接发消息即转酒馆；`/酒结束` 退出
- 👤 **人设子命令系统**：`/酒人设 绑定/查看/修改/解绑` 精细化控制，按群隔离或全局绑定
- 📚 **世界书管理**：`/酒世界书` 查看全部/查看条目/一键启停世界书
- 🔐 **权限控制**：管理员模式、群白名单/黑名单，支持 `/酒权限` 在线管理
- ✍️ **生成控制**：续写（`/酒续写`）、备选回复切换（`/酒备选`）、中断生成（`/酒停止生成`）、新对话（`/酒新建`）
- 🛠️ **角色卡工具**：聊天记录导出（`/酒导出`）、聊天统计（`/酒统计`）、重命名（`/酒改名`）
- 🌐 **英文指令别名**：全部指令支持英文别名（`tavern` / `tavern_help` / `tavern_add` 等），中英文指令均可使用
- 📦 **一键部署**：内置 SillyTavern 下载脚本与浏览器自动下载脚本，WebUI 支持一键安装并启动酒馆
- 🎁 **体验优化**：引用消息定位楼层、处理中表情回应、可选楼层数提示等

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

1. 打开插件目录（例如 `AstrBot/data/plugins/astrbot_plugin_bartender_extra/`）
2. 双击运行 **`download_browser.bat`**
3. 等待脚本自动下载并解压，控制台会显示实时进度条
4. 完成后，插件目录下会出现一个 **`browser/`** 文件夹，里面包含 `chrome.exe` 和大量配套文件

```
astrbot_plugin_bartender_extra/
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
   cd AstrBot/data/plugins/astrbot_plugin_bartender_extra
   ```
2. 运行下载脚本：
   ```bash
   bash download_browser.sh
   ```
3. 等待完成后，使用 `ls browser/` 确认 `chrome` 可执行文件已存在

> 💡 如果 `browser/` 文件夹已存在，脚本会询问是否覆盖重新下载，输入 `y` 回车即可。脚本运行结束后会自动清理临时下载的 `browser.zip`，不会留下垃圾文件。



---

### 📦 方式二：手动下载 GitHub Releases 压缩包

1. 前往 [GitHub Releases](https://github.com/NetheritePickaxe/astrbot_plugin_bartender_extra/releases) 页面
2. 下载 `browser.zip` 压缩包
3. 将压缩包解压到插件根目录，确保最终目录结构为：

```
astrbot_plugin_bartender_extra/
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

- 可以直接在 AstrBot 的插件市场搜索 `astrbot_plugin_bartender_extra`，点击安装，耐心等待安装完成即可
- 也可以手动安装：

```bash
# 克隆仓库到插件目录
cd /AstrBot/data/plugins
git clone https://github.com/NetheritePickaxe/astrbot_plugin_bartender_extra

# 控制台重启AstrBot
```

## ⌨️ 使用说明

### 指令列表

|        指令         |     英文别名      |        参数        |                    说明                    |
|:-------------------:|:-----------------:|:------------------:|:------------------------------------------:|
| `/酒 [文字内容]`    | `tavern`          | 要发送的消息文本   | 向当前酒馆角色发送消息并获取 AI 回复，不支持图片输入 |
| `/酒切换 [名字]`    | `tavern_switch`   | 目标角色卡名称     | 切换当前对话角色卡，名称需在角色列表中 |
| `/酒删除 [楼层数]`  | `tavern_delete`   | 要删除的楼层数量（可选，默认1） | 删除指定数量的最新聊天楼层，建议至少2层（含用户输入） |
| `/酒加卡 [图片]`    | `tavern_add`      | PNG 格式角色卡图片 | 上传角色卡到酒馆；支持直接附带图片、引用含图消息、或先发指令后计时内补发图片 |
| `/酒删卡 [名字]`    | `tavern_remove`   | 目标角色卡名称     | 删除指定角色卡，若删除的是当前角色则自动切换至默认卡 |
| `/酒重生成`         | `tavern_re`       | 无                 | 重新生成当前最新楼层的 AI 回复 |
| `/酒续写`           | `tavern_continue` | 无                 | 续写最新楼层，让 AI 在最新回复后继续生成内容 |
| `/酒备选 [上\|下]`  | `tavern_swipe`    | 上/下（可选，默认下） | 切换最新楼层的上一条/下一条备选回复；下一条会重新生成 |
| `/酒停止生成`       | `tavern_stop`     | 无                 | 中断当前正在进行的酒馆生成 |
| `/酒新建`           | `tavern_new`      | 无                 | 与当前角色开始新对话（清空当前楼层） |
| `/酒导出`           | `tavern_export`   | 无                 | 导出当前聊天记录为 JSONL 文件发送 |
| `/酒统计`           | `tavern_stats`    | 无                 | 查看当前角色的聊天统计（消息数/字数/生成耗时等） |
| `/酒改名 [旧名] [新名]` | `tavern_rename` | 旧名 + 新名        | 重命名指定角色卡，禁止修改默认角色名 |
| `/酒查看`           | `tavern_view`     | 无                 | 查看最新楼层；引用一条消息后发送可定位其楼层数 |
| `/酒人设`           | `tavern_persona`  | 无                 | 查看当前绑定人设与酒馆人设列表 |
| `/酒人设 绑定 [名字]` | `tavern_persona bind` | 人设名称       | 绑定当前用户到指定人设，之后 `/酒` 与 `/酒重生成` 会先切换人设 |
| `/酒人设 查看 [名字]` | `tavern_persona view` | 人设名称（可选） | 查看指定人设的名称、描述与位置等详细信息；无参时展示人设列表 |
| `/酒人设 修改 [名字] [内容]` | `tavern_persona modify` | 名字 + 描述内容（可选） | 新建或修改人设：人设不存在则新建（仅名字为空人设），存在且有内容则改描述，存在且无内容则删除 |
| `/酒人设 解绑`      | `tavern_persona unbind` | 无             | 解除当前用户绑定的人设 |
| `/酒世界书`         | `tavern_worldinfo` | 无                | 列出所有世界书与当前已启用的世界书 |
| `/酒世界书 查看 [名字]` | `tavern_worldinfo view` | 世界书名称   | 查看指定世界书的条目内容（触发词与正文） |
| `/酒世界书 切换 [名字]` | `tavern_worldinfo toggle` | 世界书名称 | 启用或停用指定世界书（对当前角色生效） |
| `/酒开始 群聊`      | `tavern_mode group` | 群聊（可选字面量） | 开启酒馆聊天模式：之后直接发消息即转酒馆，无需 `/酒` 前缀；带「群聊」按当前群生效，无参按本人；同一用户只能开启一次 |
| `/酒结束`           | `tavern_end`      | 无                 | 结束自己创建的酒馆聊天模式 |
| `/酒状态`           | `tavern_status`   | 无                 | 查看当前角色卡、角色列表及浏览器连接状态 |
| `/酒帮助`           | `tavern_help`     | 无                 | 显示所有指令的帮助信息 |
| `/酒启动`           | `tavern_start`    | 🔒 管理员          | 启动插件目录中的 SillyTavern 酒馆服务，启动后自动连接浏览器 |
| `/酒关闭`           | `tavern_close`    | 🔒 管理员          | 关闭插件浏览器并清理后台所有 Chrome/Chromium 进程 |
| `/酒重置`           | `tavern_reset`    | 🔒 管理员          | 重置插件所有全局变量，恢复默认角色，重新获取角色列表 |
| `/酒进程`           | `tavern_process`  | 🔒 管理员          | 查看当前 Chrome/Chromium 进程数量与插件浏览器状态 |
| `/酒权限`           | `tavern_permission` | 🔒 管理员        | 管理酒命令访问权限：`管理 开\|关`（管理员模式）、`白名单 [群号\|移除 群号]`、`黑名单 [群号\|移除 群号]` |

> 🔒 标记为管理员指令，仅管理员可执行。

子命令同样支持英文别名：`bind` / `view` / `modify` / `unbind`（人设）、`view` / `toggle`（世界书）、`admin` / `whitelist` / `blacklist`（权限，其中 `on` / `off`、`remove`）、`group`（开始）、`up` / `left`（备选）。

### 使用示例

|        场景         |                     输入                     |            说明            |
|:-------------------:|:--------------------------------------------:|:--------------------------|
|    基础对话    | `/酒 你好，今天天气怎么样？`           | 向当前角色发送消息并获取 AI 回复 |
|    切换角色    | `/酒切换 Seraphina`                     | 切换到名为 Seraphina 的角色卡 |
|    删除楼层    | `/酒删除 2`                             | 删除最近的 2 层聊天楼层       |
|  添加角色卡  | 先发 `/酒加卡`，再在等待时间内发送图片 | 支持分步操作，无需一次发送     |
| 查看状态    | `/酒状态`                                | 查看角色、列表和浏览器状态    |
| 绑定人设    | `/酒人设 绑定 旅行者`                     | 绑定当前用户人设为"旅行者"，此后 `/酒` 自动切换    |
| 解除人设    | `/酒人设 解绑`                            | 解除当前用户的人设绑定    |
| 查看人设详情    | `/酒人设 查看 旅行者`                     | 查看旅行者人设的名称、头像ID、描述等    |
| 重新生成回复 | `/酒重生成`                                | 重新生成最新楼层的 AI 回复    |
| 查看世界书    | `/酒世界书`                                | 列出所有世界书及当前已启用的    |

### 消息监听说明

当用户先发送 `/酒加卡` 指令（未附带图片）时，插件会为该用户开启一个计时等待窗口，在配置的时间间隔内，用户单独发送一张 PNG 图片即可自动完成角色卡上传。超时后等待状态自动取消。

## ⚙️ 配置

进入 AstrBot 插件配置面板进行配置：

### 酒馆设置

| 配置项 | 类型 | 默认值 | 说明 |
|:------|:----:|:------|:----|
| `browser_ip` | string | `http://127.0.0.1` | 酒馆前端页面的 IP 地址 |
| `browser_port` | string | `8000` | 酒馆前端页面的端口号 |
| `browser_Visible` | bool | `true` | 浏览器无头模式（`true` 为无头，`false` 为显示窗口） |
| `low_memory_mode` | bool | `false` | 低内存占用模式：开启后每次执行指令时临时启动浏览器、执行完毕自动关闭，内存占用低但响应较慢；关闭后浏览器常驻后台，响应更快 |
| `browser_delay` | int | `50` | 每次点击和查找操作之间的延迟（毫秒） |
| `upload_interval` | int | `20` | 等待角色卡上传的间隔时间（秒） |

### 基础设置

| 配置项 | 类型 | 默认值 | 说明 |
|:------|:----:|:------|:----|
| `reaction_emoji` | string | `319` | 指令处理期间给触发消息贴的 QQ 表情回应，代替文字占位提示；留空则禁用 |
| `show_floor_count` | bool | `false` | 开启后 `/酒` 的回复会在正文前附带“当前共 X 楼层”；默认关闭只发正文 |
| `global_persona_binding` | bool | `false` | 开启后用户人设绑定按 QQ 号全局生效，同一用户在所有群共用一个人设；关闭时按群隔离 |

### 权限管理

| 配置项 | 类型 | 默认值 | 说明 |
|:------|:----:|:------|:----|
| `admin_only` | bool | `false` | 管理员模式：开启后所有酒命令仅管理员可用（可用 `/酒权限 管理 开|关` 实时切换） |
| `whitelist_groups` | list | `[]` | 群聊白名单：允许使用酒命令的群号列表，为空不限制 |
| `blacklist_groups` | list | `[]` | 群聊黑名单：禁止使用酒命令的群号列表，优先于白名单 |

> ⚠️ **注意**：`low_memory_mode` 开启后，每次命令执行前后都会自动启动和关闭浏览器，内存占用低但响应较慢；关闭后浏览器常驻后台，响应更快。两种模式均已防止浏览器进程残留；异常时可用 `/酒进程` 查看进程数量与状态，用 `/酒关闭` 一键清理。

## 🖥️ 插件 WebUI 页面

> 需要 AstrBot ≥ **v4.24.2**（插件 Pages 能力）。旧版本会自动降级，仅聊天指令可用，不影响使用。

在 AstrBot WebUI 中进入 **插件 → astrbot_plugin_bartender_extra → 详情页 → Pages「酒馆界面」**，即可在面板内直接内嵌打开酒馆（SillyTavern）前端界面。内嵌地址取自插件配置中的 `browser_ip` 与 `browser_port`，修改配置后刷新页面即生效。

页面功能：

- **状态栏**：显示酒馆地址与在线状态（绿/灰圆点）
- **内嵌界面**：酒馆在线时全屏加载酒馆 WebUI
- **一键启动**：酒馆未连接且插件目录存在 SillyTavern 时，显示「启动酒馆」按钮（复用 `/酒启动` 逻辑）
- **复制地址**：内嵌受限时复制地址，到新标签页手动打开

> ⚠️ **已知限制**：
> - AstrBot 面板若走 **HTTPS**，浏览器会拦截内嵌的 HTTP 酒馆（混合内容），需保证面板与酒馆同协议，或将面板也用 HTTP 访问。
> - 从**其他设备**访问面板时，配置中的 `127.0.0.1` 会指向那台设备自身，请将 `browser_ip` 改为服务器局域网 IP。
> - 内嵌运行在 Dashboard 受限沙箱中，若酒馆因存储访问受限出现异常，请用「复制地址」在新标签页打开。

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
│  astrbot_plugin_bartender_extra            │
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
