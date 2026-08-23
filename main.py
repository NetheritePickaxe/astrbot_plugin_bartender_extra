# -*- coding: utf-8 -*-
import re, json
import time, aiohttp, platform
import subprocess, os, shutil, asyncio, functools, sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Node, Nodes, Plain, Image, File, Reply

try:  # 插件 Pages 后端 API（AstrBot >= v4.24.2），旧版降级跳过
    from astrbot.api.web import json_response
    _WEB_API_AVAILABLE = True
except ImportError:
    _WEB_API_AVAILABLE = False

PLUGIN_NAME = "astrbot_plugin_bartender_extra"

# 引用定位兼容楼层前缀
_FLOOR_PREFIX_RE = re.compile(r"^当前共\d+楼层$")

# 括号参数提取：匹配 [内容]，内容可含空格与换行（不含嵌套方括号）
_BRACKET_ARG_RE = re.compile(r"\[([^\[\]]*)\]")


def _split_bracket_args(text):
    """从文本提取括号片段：返回（首个左括号前的文本strip后的名字, 片段列表）"""
    m = _BRACKET_ARG_RE.search(text)
    if not m:
        return text.strip(), []
    head = text[:m.start()].strip()
    segs = [s.strip() for s in _BRACKET_ARG_RE.findall(text)]
    return head, segs


def _norm_field(seg):
    """规范化括号字段值："/" 表示保留原值（返回 None），空串表示清空，其余原样返回"""
    seg = seg.strip()
    return None if seg == "/" else seg


def _build_card_png(name, description, first_mes):
    """纯 Python 生成最小 V2 角色卡 PNG（1x1 像素 + tEXt chara 块），返回本地文件路径"""
    import base64
    import struct
    import zlib

    card = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": description,
            "personality": "",
            "scenario": "",
            "first_mes": first_mes,
            "mes_example": "",
            "creator_notes": "",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "tags": [],
            "creator": "",
            "character_version": "",
            "extensions": {},
        },
    }
    payload = base64.b64encode(json.dumps(card, ensure_ascii=False).encode("utf-8"))

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0) # 1x1 像素、8bit、RGB
    idat = zlib.compress(b"\x00\xff\xff\xff") # filter 0 + 单像素白色
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"tEXt", b"chara\x00" + payload) # SillyTavern 标准角色卡嵌入格式
    png += chunk(b"IDAT", idat)
    png += chunk(b"IEND", b"")

    save_dir = Path("data/temp/astrbot_plugin_bartender_extra")
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"textcard_{int(time.time() * 1000)}.png"
    save_path.write_bytes(png)
    return save_path


# 聊天模式下放行的本插件指令名集合（首词命中则不拦截，交给指令分发）
CHAT_MODE_COMMANDS = frozenset({
    "酒", "酒切换", "酒删除", "酒加卡", "酒删卡", "酒重生成", "酒续写", "酒备选",
    "酒中断", "酒停止", "酒新建", "酒导出", "酒统计", "酒查看",
    "酒人设", "酒状态", "酒帮助", "酒启动", "酒重置", "酒重启",
    "酒进程", "酒开始", "酒结束", "酒权限", "酒世界书",
})
# 注：酒人设 修改 / 酒人设 解绑 为 酒人设 子命令，首词「酒人设」已在集合内


def _access_required(handler):
    """指令访问控制装饰器：按黑/白名单与管理员模式校验，不通过则直接回复原因"""
    @functools.wraps(handler)
    async def wrapper(self, event: AstrMessageEvent):
        ok, reason = self._check_access(event)
        if not ok:
            yield event.plain_result(reason)
            return
        async for result in handler(self, event):
            yield result
    return wrapper

# 设置环境变量以启用 Playwright 的调试模式，0为正常模式，1为调试模式
os.environ["PWDEBUG"] = "0"

# 插件注册，参数分别为：插件名（唯一标识符）、作者、简介、版本号    
@register(PLUGIN_NAME,
           "dragonuniverse8248编写 GML5.2 & deepseek指导",
            "基于playwright无头浏览器库，对sillytavern项目进行操作和交互，达成通过机器人远程游玩Sillytavern，以及高于联机脚本的游玩体验貂蝉在一起",
              "1.6.2")



# 爬虫类定义
class bartender_crawler(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config # 初始化配置文件
        self.ST_URL = f"{self.config['tavern']['browser_ip']}:{self.config['tavern']['browser_port']}" # 获取配置的本地酒馆地址
        self.chats_name_id = {} # 初始化角色字典
        self.default_chat = self.config['basic']['now_chats_name'] # 获取配置文件当前角色
        self.browser = None # 初始化浏览器类
        self._browser_lock = asyncio.Lock() # 浏览器启动/关闭互斥锁，防止并发重复启动出多个浏览器
        self.status_running = False # 消息状态初始化
        self._st_proc = None # 酒馆 node 进程句柄（插件启动时保存，用于后续停止/重启）
        self.cache_dir = Path("data/temp/astrbot_plugin_bartender_extra") # 初始化本地缓存文件夹路径
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.waiting_sessions = {} # 初始化会话状态字典，用于记录哪些用户正在等待发送图片，格式为: {"群号_用户ID": 过期时间戳}
        self.chat_mode_creators = {} # 酒馆聊天模式：创建者键"{群号}_{用户ID}" -> ("user"|"group", scope)
        self.chat_mode_user_keys = set() # 活跃的按用户聊天模式键 "{群号}_{用户ID}"
        self.chat_mode_group_keys = {} # 活跃的按群聊天模式键 "{群号}" -> 创建者键
        self.plugin_dir = Path(__file__).parent # 获取当前目录
        self.browser_dir = self.plugin_dir / "browser"
        self.persona_bindings = self._load_persona_bindings() # 用户人设绑定字典，格式为: {"群号_用户ID": {"name": 人设名, "avatar_id": 人设头像ID}}
        self._st_install_status = None # 酒馆安装状态：None | "downloading" | "extracting" | "installing_deps" | "done" | "failed: <msg>"
        self._register_web_apis(context)

    def _register_web_apis(self, context):
        """注册插件 Pages 后端 API（旧版 AstrBot 无此能力时降级跳过）"""
        if not (_WEB_API_AVAILABLE and hasattr(context, "register_web_api")):
            logger.warning("当前 AstrBot 版本不支持插件 Pages（需 v4.24.2+），WebUI 页面不可用，聊天指令不受影响。")
            return
        context.register_web_api(
            f"/{PLUGIN_NAME}/info",
            self.page_info,
            ["GET"],
            "获取酒馆地址与连通状态",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/tavern/start",
            self.page_start_tavern,
            ["POST"],
            "启动插件目录中的酒馆",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/tavern/install",
            self.page_install_tavern,
            ["POST"],
            "下载并安装 SillyTavern 到插件目录",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/tavern/stop",
            self.page_stop_tavern,
            ["POST"],
            "停止插件目录中的酒馆服务",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/tavern/restart",
            self.page_restart_tavern,
            ["POST"],
            "重启插件目录中的酒馆服务（先停后启）",
        )

    def _check_access(self, event):
        """访问控制：黑名单优先、白名单限制群聊、管理员模式要求管理员；返回 (是否通过, 原因)"""
        gid = event.get_group_id()
        gid_s = str(gid) if gid is not None else ""
        blacklist = [str(x) for x in (self.config['permission'].get('blacklist_groups') or [])]
        whitelist = [str(x) for x in (self.config['permission'].get('whitelist_groups') or [])]
        if gid_s and gid_s in blacklist: # 群黑名单优先（私聊不适用群名单）
            return False, """本群已被加入黑名单，禁止使用酒命令"""
        if gid_s and whitelist and gid_s not in whitelist: # 白名单非空时仅允许列内群聊
            return False, """本群不在白名单内，禁止使用酒命令"""
        if self.config['permission'].get('admin_only') and not event.is_admin(): # 管理员模式
            return False, """管理员模式已开启，该命令仅管理员可用"""
        return True, ""

    async def page_info(self):
        """返回酒馆地址、连通性、是否携带捆绑酒馆"""
        st_url = f"{self.config['tavern']['browser_ip']}:{self.config['tavern']['browser_port']}"
        parsed = urlparse(st_url)
        host = parsed.hostname or parsed.path.split(":")[0]
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        reachable = False
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
            writer.close()
            await writer.wait_closed()
            reachable = True
        except Exception:
            reachable = False
        has_bundled = (self.plugin_dir / "SillyTavern" / "server.js").exists()
        return json_response({
            "st_url": st_url,
            "ip": self.config['tavern']['browser_ip'],
            "port": self.config['tavern']['browser_port'],
            "reachable": reachable,
            "has_bundled_st": has_bundled,
            "install_status": self._st_install_status,
        })

    async def page_start_tavern(self):
        """启动插件目录中的酒馆（供 WebUI 一键启动按钮调用）"""
        ok, msg = await self.start_tavern()
        return json_response({"ok": ok, "message": msg})

    async def page_install_tavern(self):
        """下载并安装 SillyTavern（供 WebUI 一键安装按钮调用）"""
        if self._st_install_status is not None:
            return json_response({"ok": False, "message": """正在安装中，请等待完成"""})
        ok, msg = await self.install_tavern()
        if ok:
            asyncio.create_task(self._install_tavern_bg())
        return json_response({"ok": ok, "message": msg})

    async def install_tavern(self):
        """启动酒馆安装流程（后台 subprocess 调用 download_sillytavern.py）"""
        st_dir = self.plugin_dir / "SillyTavern"
        if (st_dir / "server.js").exists():
            return False, """酒馆已安装"""
        node_path = shutil.which("node")
        if not node_path:
            return False, """未检测到 Node.js，请先安装 Node.js 18+"""
        self._st_install_status = "starting"
        return True, """安装中…"""

    async def _install_tavern_bg(self):
        """后台执行：subprocess 调用 download_sillytavern.py，逐行读 stdout 更新状态"""
        script = self.plugin_dir / "download_sillytavern.py"
        log_path = self.cache_dir / "st_install.log"
        try:
            if hasattr(self, "_st_install_log") and self._st_install_log:
                try:
                    self._st_install_log.close()
                except Exception:
                    pass
            self._st_install_log = open(log_path, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": str(self.plugin_dir),
                "stdin": subprocess.PIPE,
                "stdout": self._st_install_log,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                **popen_kwargs,
            )
            try:
                proc.stdin.write(b"y\n")
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.stdin.close()
            except Exception:
                pass
            # 逐行读日志文件更新状态
            while proc.poll() is None:
                self._update_install_status_from_log()
                await asyncio.sleep(2)
            self._update_install_status_from_log()
            rc = proc.returncode
            if rc == 0:
                self._st_install_status = "done"
            else:
                if not (self._st_install_status and self._st_install_status.startswith("failed")):
                    self._st_install_status = f"failed: exit code {rc}"
        except Exception as e:
            self._st_install_status = f"failed: {e}"
            logger.error(f"安装 SillyTavern 异常: {e}")
        finally:
            try:
                self._st_install_log.close()
            except Exception:
                pass
            await asyncio.sleep(10)
            self._st_install_status = None

    def _update_install_status_from_log(self):
        """读取安装日志文件末尾，匹配关键字更新安装状态"""
        log_path = self.cache_dir / "st_install.log"
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                if "[错误]" in line or "失败" in line:
                    self._st_install_status = f"failed: {line}"
                    return
                if "正在安装依赖" in line or "npm install" in line.lower():
                    self._st_install_status = "installing_deps"
                    return
                if "正在解压" in line or "解压进度" in line:
                    self._st_install_status = "extracting"
                    return
                if "正在下载" in line or "已下载" in line:
                    self._st_install_status = "downloading"
                    return
                if "[成功]" in line and "下载完成" in line:
                    self._st_install_status = "extracting"
                    return
                if "[成功]" in line and "依赖安装完成" in line:
                    self._st_install_status = "done"
                    return
                break
        except Exception:
            pass

    def _persona_bindings_path(self) -> Path:
        """人设绑定数据的持久化文件路径"""
        return self.cache_dir / "persona_bindings.json"

    def _load_persona_bindings(self) -> dict:
        """从本地文件加载用户人设绑定数据"""
        try:
            path = self._persona_bindings_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.error(f"加载人设绑定数据失败: {e}")
        return {}

    def _save_persona_bindings(self):
        """保存用户人设绑定数据至本地文件"""
        try:
            path = self._persona_bindings_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.persona_bindings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存人设绑定数据失败: {e}")

    def get_persona_session_key(self, event) -> str:
        """计算用户人设绑定键：开启全局绑定仅用用户ID，否则用 群号_用户ID（按群隔离）"""
        if self.config['basic'].get('global_persona_binding'):
            return str(event.get_sender_id())
        return f"{event.get_group_id()}_{event.get_sender_id()}"

    async def initialize_browser(self):
        """使用 Playwright 来启动浏览器（加锁串行化，防止并发重复启动出多个浏览器）"""
        async with self._browser_lock:
            return await self._launch_browser()

    async def _launch_browser(self):
        """启动浏览器与加载页面的实际逻辑（调用方需持有 _browser_lock）"""
        parsed = urlparse(self.ST_URL) # 解析目标地址和端口
        host = parsed.hostname or parsed.path.split(":")[0]
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try: # 快速连通性检查（TCP）
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=3
            )
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            logger.error(f"目标地址 {self.ST_URL} 不可达（host={host}, port={port}），请确认酒馆已启动或配置正确。错误：{e}")
            return False  # 不可达直接退出函数，不再启动浏览器
        await self._close_browser() # 先清理可能残留的旧浏览器（含孤儿进程）
        self.p = await async_playwright().start()
        if os.name == 'nt':
            exe_path = self.browser_dir / "chrome.exe"
        else:
            exe_path = self.browser_dir / "chrome"
        launch_exe = str(exe_path) # 如果没有找到打包的浏览器，降级为使用 Playwright 默认下载的浏览器
        launch_exe = str(exe_path) if exe_path.exists() else None
        if not launch_exe:
            logger.warning(f"未在 {self.browser_dir} 找到打包的浏览器，将尝试使用 Playwright 默认浏览器。")
        try:
            self.browser = await self.p.chromium.launch(
                headless=bool(self.config['tavern']['browser_Visible']),
                slow_mo=int(self.config['tavern']['browser_delay']),
                executable_path=launch_exe, # 【修改】指定本地浏览器路径
                args=[
                    '--no-sandbox', # Linux下必须，防止权限报错
                    '--disable-gpu', # 提高无头模式稳定性
                    '--disable-dev-shm-usage' # 防止 Docker/容器环境中内存溢出
                ]
            )
            self.page = await self.browser.new_page() # 使用ST_URL网页打开本地服务，等待页面加载完成
            await self.page.goto(self.ST_URL, wait_until="domcontentloaded")
            await self.page.wait_for_selector(".welcomeHeaderVersionDisplay",state="visible")
            logger.info(f"{self.ST_URL}页面加载成功")
            return True
        except Exception as e:
            logger.error(f"请检查是否目录下是否有浏览器文件browser文件，或系统安装playwright的运行环境并且下载了浏览器依赖，若无请查看说明进行安装: {e}")
            return False

    async def check_browser(self):
        """检查浏览器是否可用；不可用时加锁重启，避免并发启动出多个浏览器"""
        async with self._browser_lock:
            try: # 连接正常则直接复用
                if self.browser and self.browser.is_connected():
                    self.page.locator("#rightNavDrawerIcon")
                    return True
            except Exception as e:
                logger.warning(f"浏览器探活失败，准备重启: {e}")
            ok = await self._launch_browser() # 锁内串行重启，旧进程会被 _close_browser 清理
            if ok:
                logger.info("浏览器重启成功")
            return ok

    async def open_chats(self):
        """打开角色导航栏并检测"""
        if await self.check_browser():
            try:
                # await self.page.wait_for_timeout(800) # 避免操作过快
                await self.page.locator("#rightNavDrawerIcon").click() # 打开角色导航栏
                await self.page.wait_for_selector("#rm_button_characters[title='选择/创建角色']",state="visible",timeout=3000)
                return True
            except Exception as e:
                logger.error(f"打开角色导航栏失败{e}")
                return False

    async def close_chats(self):
        """检测角色导航栏是否开启并关闭"""
        try:
            # await self.page.wait_for_timeout(500) # 避免操作过快
            await self.page.wait_for_selector("#rm_button_characters[title='选择/创建角色']",state="visible",timeout=3000)
            await self.page.locator("#rightNavDrawerIcon").click() # 关闭角色导航栏
        except Exception as e:
            pass
        # logger.info("已关闭角色导航栏")
        return True

    async def check_1000page(self):
        """检查角色页是否1000分页"""
        if await self.check_browser(): # 检测浏览器状态和打开角色导航
            try:
                await self.page.wait_for_timeout(500) # 避免加载过慢
                await self.open_chats() # 打开导航栏
                options = self.page.locator("#rm_print_characters_pagination").locator(".paginationjs")\
                    .locator(".paginationjs-size-changer").locator(".J-paginationjs-size-select").locator("option[selected]")
                value = await options.get_attribute("value")
                # logger.info(f"分页{value}")
                if value == "1000": # 检测到1000分页，退出
                    logger.info("检查到1000分页")
                else: # 检查到非1000分页，进行修改
                    await options.select_option(value="1000", timeout=5000)
                    logger.info("修改为1000分页")
                await self.close_chats()
                return True
            except Exception as e:
                logger.error(f"检查分页失败：{e}")
                await self.close_chats()
                return False
        else:
            logger.error("浏览器打开失败")
            return False

    async def get_all_chats(self):
        """获取所有的角色卡,最高1000张"""
        await self.close_chats() # 先确保抽屉关闭再重新打开
        if await self.open_chats(): # 检查是否为1000分页
            try:
                self.chats_name_id = {}
                chats = self.page.locator(".character_select.entity_block[role='listitem']")
                for i in range(await chats.count()): # 遍历所有角色卡
                    chat = chats.nth(i)
                    name = await chat.locator(".ch_name").inner_text()
                    id = await chat.get_attribute("id")
                    self.chats_name_id[name] = id
                logger.info(f"列表：{self.chats_name_id}")
            except Exception as e:
                logger.error(f"获取角色列表失败")
            await self.close_chats()

    async def switch_chats(self, name):
        """切换角色卡"""
        if self.chats_name_id != None and await self.check_browser() and await self.open_chats(): # 检查前置状态
            if name in self.chats_name_id.keys(): # 判断输入是否合法
                await self.page.locator(f"#{self.chats_name_id[name]}").click() # 点击角色卡
                await self.check_confirm() # 检查是否有世界书和酒馆脚本确认
                await self.page.locator("#rm_button_characters").click() # 切换回角色列表
                await self.close_chats()
                self.config['basic']['now_chats_name'] = name
                self.config.save_config()
                logger.info(f"切换角色为：{name}")
                return name
            else:
                logger.info("未找到存在角色")
                return None

    async def is_persona_panel_open(self):
        """检测人设管理面板是否已打开"""
        try:
            return bool(await self.page.evaluate(
                "() => document.querySelector('#PersonaManagement')?.classList.contains('openDrawer') ?? false"))
        except Exception:
            return False

    async def open_persona_panel(self):
        """打开人设管理面板"""
        if await self.check_browser():
            try:
                if not await self.is_persona_panel_open():
                    await self.page.locator("#persona-management-button .drawer-toggle").click()
                    await self.page.wait_for_selector("#PersonaManagement.openDrawer", state="visible", timeout=5000)
                return True
            except Exception as e:
                logger.error(f"打开人设面板失败: {e}")
                return False
        return False

    async def close_persona_panel(self):
        """关闭人设管理面板（若已打开）"""
        try:
            if await self.is_persona_panel_open():
                await self.page.locator("#persona-management-button .drawer-toggle").click()
                await self.page.wait_for_selector("#PersonaManagement.openDrawer", state="hidden", timeout=5000)
        except Exception as e:
            logger.warning(f"关闭人设面板异常: {e}")
        return True

    async def _ensure_persona_list_full(self):
        """将人设列表分页调整为1000，保证一次渲染全部人设（与角色列表 check_1000page 同理）"""
        try:
            size_select = self.page.locator("#persona_pagination_container .J-paginationjs-size-select")
            await size_select.select_option(value="1000", timeout=5000)
            await self.page.wait_for_timeout(500) # 等待分页重渲染
        except Exception as e:
            logger.warning(f"人设分页调整失败（可能无需调整）: {e}")

    async def get_personas(self):
        """获取所有人设：返回 (人设字典{名称: 头像ID}, 当前人设名/None)；浏览器失败返回 (None, None)"""
        if not await self.open_persona_panel():
            return None, None
        try:
            await self._ensure_persona_list_full()
            blocks = self.page.locator("#user_avatar_block .avatar-container")
            personas = {}
            current = None
            for i in range(await blocks.count()):
                block = blocks.nth(i)
                name = (await block.locator(".ch_name").inner_text()).strip()
                avatar_id = await block.get_attribute("data-avatar-id")
                if not name or not avatar_id:
                    continue
                personas[name] = avatar_id
                if await block.evaluate("el => el.classList.contains('selected')"):
                    current = name
            return personas, current
        except Exception as e:
            logger.error(f"获取人设列表失败: {e}")
            return None, None
        finally:
            await self.close_persona_panel()

    async def switch_persona(self, name):
        """切换到指定人设（支持人设名或头像ID）；返回 (是否成功, 头像ID/None)"""
        if not await self.open_persona_panel():
            return False, None
        try:
            await self._ensure_persona_list_full()
            blocks = self.page.locator("#user_avatar_block .avatar-container")
            for i in range(await blocks.count()):
                block = blocks.nth(i)
                block_name = (await block.locator(".ch_name").inner_text()).strip()
                avatar_id = await block.get_attribute("data-avatar-id")
                if name in (block_name, avatar_id):
                    await block.click()
                    await self.page.wait_for_function(
                        """(id) => Array.from(document.querySelectorAll('#user_avatar_block .avatar-container'))
                                          .some(el => el.getAttribute('data-avatar-id') === id && el.classList.contains('selected'))""",
                        arg=avatar_id, timeout=5000)
                    logger.info(f"切换人设为：{name}（{avatar_id}）")
                    return True, avatar_id
            logger.warning(f"未找到人设：{name}")
            return False, None
        except Exception as e:
            logger.error(f"切换人设失败: {e}")
            return False, None
        finally:
            await self.close_persona_panel()

    async def _select_persona_block(self, name):
        """在人设面板中按名称选中人设（不关闭面板）；返回是否成功"""
        await self._ensure_persona_list_full()
        blocks = self.page.locator("#user_avatar_block .avatar-container")
        for i in range(await blocks.count()):
            block = blocks.nth(i)
            block_name = (await block.locator(".ch_name").inner_text()).strip()
            if block_name == name:
                if not await block.evaluate("el => el.classList.contains('selected')"):
                    await block.click()
                    await self.page.wait_for_timeout(300)
                return True
        return False

    async def create_persona(self, name, description):
        """新建人设（名+可选描述）；返回 (是否成功, 提示)"""
        if not await self.open_persona_panel():
            return False, "打开人设面板失败"
        try:
            await self.page.locator("#create_dummy_persona").click(timeout=5000) # 点击新建按钮
            name_input = self.page.locator(".popup-input").first # 等待名称输入弹窗
            await name_input.wait_for(state="visible", timeout=5000)
            await name_input.fill(name, timeout=5000)
            await self.page.locator(".popup-button-ok[data-result='1']").click(timeout=5000) # 确认
            await self.page.locator(".popup-input").first.wait_for(state="hidden", timeout=5000) # 等待弹窗关闭
            await self.page.wait_for_timeout(500) # 等待新人设渲染选中
            if description: # 描述非空才填写（默认即为空描述）
                desc = self.page.locator("#persona_description")
                await desc.fill(description, timeout=5000)
                await self.page.wait_for_timeout(500) # 等待自动保存
            logger.info(f"已创建人设：{name}")
            return True, "正常"
        except Exception as e:
            logger.error(f"创建人设失败：{e}")
            return False, "错误"
        finally:
            await self.close_persona_panel()

    async def set_persona_description(self, name, description):
        """更新已存在人设的描述；返回 (是否成功, 提示)"""
        if not await self.open_persona_panel():
            return False, "打开人设面板失败"
        try:
            if not await self._select_persona_block(name):
                return False, "未找到人设"
            desc = self.page.locator("#persona_description")
            await desc.fill(description, timeout=5000)
            await self.page.wait_for_timeout(500) # 等待自动保存
            logger.info(f"已更新人设描述：{name}")
            return True, "正常"
        except Exception as e:
            logger.error(f"更新人设描述失败：{e}")
            return False, "错误"
        finally:
            await self.close_persona_panel()

    async def delete_persona(self, name):
        """删除人设；返回 (是否成功, 提示)"""
        if not await self.open_persona_panel():
            return False, "打开人设面板失败"
        try:
            if not await self._select_persona_block(name):
                return False, "未找到人设"
            await self.page.locator("#persona_delete_button").click(timeout=5000) # 点击删除
            ok = self.page.locator(".popup-button-ok[data-result='1']") # 等待确认弹窗
            await ok.wait_for(state="visible", timeout=5000)
            await ok.click(timeout=5000)
            await self.page.wait_for_timeout(500) # 等待删除完成
            logger.info(f"已删除人设：{name}")
            return True, "正常"
        except Exception as e:
            logger.error(f"删除人设失败：{e}")
            return False, "错误"
        finally:
            await self.close_persona_panel()

    async def apply_user_persona(self, event):
        """发送前应用当前用户绑定的人设；返回 (是否成功, 失败提示/空串)"""
        session_key = self.get_persona_session_key(event)
        bound = self.persona_bindings.get(session_key)
        if not bound:
            return True, ""
        target = bound.get("avatar_id") or bound.get("name")
        ok, _ = await self.switch_persona(target)
        if not ok and bound.get("name") and target != bound.get("name"):
            ok, _ = await self.switch_persona(bound.get("name")) # 头像ID失效则退回按名称匹配
        if not ok:
            return False, f"""人设切换失败：{(bound.get('name'))}，请发送 /酒人设 解绑 解除后重新绑定"""
        return True, ""

    async def list_world_infos(self):
        """通过 page.evaluate 调 REST 列出所有世界书及当前已启用"""
        try:
            if not await self.check_browser():
                return None
            data = await self.page.evaluate(
                """async () => {
                    const list = await fetch('/api/worldinfo/list', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r => r.ok ? r.json() : []);
                    const sel = document.getElementById('world_info');
                    const active = sel ? Array.from(sel.selectedOptions).map(o => o.text || o.value) : [];
                    return {list: list, active: active};
                }"""
            )
            return data
        except Exception as e:
            logger.error(f"列出世界书失败：{e}")
            return None

    async def get_world_info_detail(self, name):
        """通过 page.evaluate 调 REST 查看指定世界书的条目"""
        try:
            if not await self.check_browser():
                return None
            data = await self.page.evaluate(
                """async (name) => {
                    const r = await fetch('/api/worldinfo/get', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: name})});
                    if (!r.ok) return null;
                    return await r.json();
                }""",
                name,
            )
            return data
        except Exception as e:
            logger.error(f"查看世界书失败：{e}")
            return None

    async def toggle_world_info(self, name):
        """通过 Playwright UI 切换世界书的启用/停用（#WIDrawer 内 #world_info 多选）"""
        try:
            if not await self.check_browser():
                return False, "浏览器未连接"
            # 打开世界书抽屉
            wi_drawer = self.page.locator("#WorldInfo")
            was_open = await wi_drawer.evaluate("el => el.classList.contains('openDrawer')")
            if not was_open:
                await self.page.locator("#WIDrawerIcon").click()
                await self.page.wait_for_selector("#WorldInfo.openDrawer", state="visible", timeout=5000)
            try:
                # 在 #world_info 多选中切换选项
                result = await self.page.evaluate(
                    """(name) => {
                        const sel = document.getElementById('world_info');
                        if (!sel) return {ok: false, code: 'selector'};
                        let opt = null;
                        for (const o of sel.options) {
                            if (o.text === name || o.value === name) { opt = o; break; }
                        }
                        if (!opt) return {ok: false, code: 'not_found'};
                        const was = opt.selected;
                        opt.selected = !was;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return {ok: true, was};
                    }""",
                    name,
                )
            finally:
                if not was_open: # 关闭抽屉（如果原来就是开的就不关）
                    await self.page.locator("#WIDrawerIcon").click()
            if not result.get("ok", False):
                code = result.get("code", "")
                msg = {"selector": "世界书选择器缺失", "not_found": "未找到世界书"}.get(code, "错误")
                return False, msg
            was = bool(result.get("was"))
            return True, "已停用" if was else "已启用"
        except Exception as e:
            logger.error(f"切换世界书失败：{e}")
            return False, "错误"

    async def get_new_message(self, bot_id):
        """获取最新消息（返回Nodes转发消息）"""
        if await self.check_browser() and await bartender_crawler.get_chat_Status(self): # 判断聊天栏状态
            message_box = self.page.locator("#chat > *") # 获取所有楼层
            message_new = await message_box.last.locator(".mes_block").locator(".mes_text").all_inner_texts()
            logger.info(f"get_new_message 读到 {len(message_new)} 条消息")
            if not message_new or not message_new[0].strip():
                logger.error("get_new_message 消息为空")
                return None
            message_list = [s.strip() for s in message_new[0].split("\n") if s.strip()]
            logger.info(f"get_new_message 过滤后 {len(message_list)} 段，首段前50字: {message_list[0][:50]}")
            max_nodes = 100
            truncated = False
            if len(message_list) > max_nodes:
                message_list = message_list[:max_nodes]
                truncated = True
            nodes_list = [
                Node(
                    uin = bot_id,
                    name = self.config['basic']['now_chats_name'],
                    content = [Plain(str(item))]
                )
                for item in message_list]
            if truncated:
                nodes_list.append(Node(
                    uin = bot_id,
                    name = self.config['basic']['now_chats_name'],
                    content = [Plain("""（内容过长，已截断）""")]
                ))
            forward_message = Nodes(nodes=nodes_list)
            return forward_message
        else:
            logger.error("获取信息失败")
            return None

    async def get_new_message_text(self):
        """获取最新消息（返回纯文本）"""
        if await self.check_browser() and await bartender_crawler.get_chat_Status(self):
            message_box = self.page.locator("#chat > *")
            message_new = await message_box.last.locator(".mes_block").locator(".mes_text").all_inner_texts()
            if not message_new or not message_new[0].strip():
                logger.error("get_new_message_text 消息为空")
                return None
            message_list = message_new[0].split("\n")
            # 拼接全部非空段，去掉首尾空白
            text = "\n".join([s.strip() for s in message_list if s.strip()])
            logger.info(f"get_new_message_text 返回文本前100字: {text[:100]}")
            return text
        else:
            logger.error("获取信息失败")
            return None

    async def get_chat_Status(self):
        """获取当前角色卡"""
        if await self.check_browser(): # 检查前置状态
            try:
                name = await self.page.locator("#rm_button_selected_ch").locator(".interactable").inner_text() # 检测当前状态
                if name != "": # 检测并赋予角色卡
                    self.config['basic']['now_chats_name'] = name
                    logger.info(f"当前角色为：{self.config['basic']['now_chats_name']}")
                    self.config.save_config()
                    return True
                else:
                    self.config['basic']['now_chats_name'] = None
                    logger.info(f"当前角色为：无")
                    return False
            except Exception as e:
                await self.close_chats()
                logger.error(f"角色检测错误{e}")
        elif self.config['basic']['now_chats_name'] == (None or '') and self.chats_name_id == {}:
            logger.error("当前无角色或角色列表")
            return False

    async def send_message(self, user):
        """发送消息至酒馆并等待生成完成"""
        try:
            if await self.check_browser() and await self.get_chat_Status(): # 检测状态
                    await self.page.locator("#send_textarea").fill(user) # 将文本输入至聊天框
                    await self.page.locator("#send_textarea").press("Enter") # 回车发送
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible",timeout=15000) # 检测AI生成中
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="hidden",timeout=120000) # 检测生成完成
                    await self.page.wait_for_selector("#send_but",state="visible",timeout=10000) # 发送按钮已经复位
                    logger.info("消息生成完成")
                    return "正常"
            else:
                return "无角色卡"
        except Exception as e:
            logger.error(f"发送信息失败：{e}")
            return "错误"

    async def rest_message(self):
        """重新生成消息"""
        try:
            if await self.check_browser() and await self.get_chat_Status(): # 检测状态
                    await self.page.locator("#options_button").click(timeout=5000) # 打开菜单
                    await self.page.locator("#option_regenerate").click(timeout=5000) # 点击重新生成按钮
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible",timeout=15000) # 检测AI生成中
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="hidden",timeout=120000) # 检测生成完成
                    await self.page.wait_for_selector("#send_but",state="visible",timeout=10000) # 发送按钮已经复位
                    logger.info("消息生成完成")
                    return "正常"
            else:
                return "无角色卡"
        except Exception as e:
            logger.error(f"发送信息失败：{e}")
            return "错误"

    async def del_message(self, input_number):
        """删除楼层"""
        try:
            if self.browser and await self.get_chat_Status():
                await self.page.locator("#options_button").click() # 打开菜单
                await self.page.locator("#option_delete_mes").click() # 进入删除楼层模式
                message_box = self.page.locator("#chat > *") # 获取所有楼层
                message_count = await message_box.count() # 楼层数量
                if (input_number >= message_count) or (input_number == message_count == 1):
                    return False, message_count
                elif input_number == 1: # 避免陷入循环
                    now_message = message_box.nth(-input_number)
                    await now_message.click()
                else: # 多数循环点击
                    for i in range(1,input_number+1):
                        # logger.info(f"循环{i}")
                        now_message = message_box.nth(-i)
                        await now_message.click()
                    logger.info("暂停中")
                await self.page.locator("#dialogue_del_mes_ok").click()
                return True
            logger.error(f"删除楼层错误无角色卡")
            return False
        except Exception as e:
            logger.error(f"删除楼层错误:{e}")
            return False

    async def start_new_chat(self):
        """与当前角色开始新对话（清空楼层）"""
        try:
            if await self.check_browser() and await self.get_chat_Status():
                await self.page.locator("#options_button").click(timeout=5000) # 打开菜单
                await self.page.locator("#option_start_new_chat").click(timeout=5000) # 点击新对话
                await self.check_confirm() # 检查确认框
                logger.info("已开始新对话")
                return "正常"
            else:
                return "无角色卡"
        except Exception as e:
            logger.error(f"开始新对话失败：{e}")
            return "错误"

    async def continue_message(self):
        """续写最新楼层"""
        try:
            if await self.check_browser() and await self.get_chat_Status():
                await self.page.locator("#options_button").click(timeout=5000) # 打开菜单
                await self.page.locator("#option_continue").click(timeout=5000) # 点击续写
                await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible",timeout=15000) # 检测AI生成中
                await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="hidden",timeout=120000) # 检测生成完成
                await self.page.wait_for_selector("#send_but",state="visible",timeout=10000) # 发送按钮复位
                logger.info("续写完成")
                return "正常"
            else:
                return "无角色卡"
        except Exception as e:
            logger.error(f"续写失败：{e}")
            return "错误"

    async def stop_generation(self):
        """中断当前生成"""
        try:
            if not await self.check_browser():
                return "浏览器未连接"
            generating = False
            try:
                await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible",timeout=2000) # 检测是否生成中
                generating = True
            except Exception:
                generating = False
            if not generating:
                return "无生成中"
            await self.page.locator(".fa-solid.fa-circle-stop").click(timeout=5000) # 点击停止
            await self.page.wait_for_selector("#send_but",state="visible",timeout=10000) # 等待复位
            logger.info("已中断生成")
            return "已停止"
        except Exception as e:
            logger.error(f"中断生成失败：{e}")
            return "错误"

    async def swipe_message(self, direction):
        """切换上一条/下一条备选回复，direction: next/prev"""
        try:
            if await self.check_browser() and await self.get_chat_Status():
                message_box = self.page.locator("#chat > *") # 获取最新楼层
                last = message_box.nth(-1)
                arrow = last.locator(".swipe_right" if direction == "next" else ".swipe_left")
                try:
                    await arrow.click(timeout=5000) # 点击左右箭头
                except Exception:
                    return "无更多回复"
                generating = False # next 会触发生成，prev 仅切换
                try:
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible",timeout=3000)
                    generating = True
                except Exception:
                    generating = False
                if generating:
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="hidden",timeout=120000) # 等待生成完成
                    await self.page.wait_for_selector("#send_but",state="visible",timeout=10000) # 发送按钮复位
                logger.info(f"swipe {direction} 完成")
                return "正常"
            else:
                return "无角色卡"
        except Exception as e:
            logger.error(f"swipe 失败：{e}")
            return "错误"

    async def get_current_stats(self):
        """通过页面上下文调用酒馆 REST 获取当前角色统计，返回 {name, stats} 或 None"""
        try:
            if not await self.check_browser():
                return None
            data = await self.page.evaluate(
                """async () => {
                    const nameEl = document.querySelector('#rm_button_selected_ch .interactable');
                    const name = nameEl ? nameEl.innerText.trim() : null;
                    if (!name) return null;
                    const list = await fetch('/api/characters/all', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r => r.ok ? r.json() : []);
                    const item = (Array.isArray(list) ? list : []).find(c => c.name === name);
                    if (!item) return {name: name, stats: null};
                    const stats = await fetch('/api/stats/get', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r => r.ok ? r.json() : {});
                    return {name: name, stats: stats[item.avatar] || null};
                }"""
            )
            return data
        except Exception as e:
            logger.error(f"获取统计失败：{e}")
            return None

    async def export_current_chat(self):
        """通过页面上下文调用酒馆 REST 导出当前聊天记录，返回本地文件路径或 None"""
        save_path = self.cache_dir / f"export_{int(time.time() * 1000)}.jsonl"
        try:
            if not await self.check_browser():
                return None
            text = await self.page.evaluate(
                """async () => {
                    const recent = await fetch('/api/chats/recent', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max: 1})}).then(r => r.ok ? r.json() : []);
                    const cur = Array.isArray(recent) && recent.length ? recent[0] : null;
                    if (!cur || !cur.file_name || !cur.avatar) return null;
                    const r = await fetch('/api/chats/export', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({file: cur.file_name, avatar_url: cur.avatar, is_group: false, format: 'jsonl'})});
                    if (!r.ok) return null;
                    const data = await r.json();
                    return data.result || null;
                }"""
            )
            if not text:
                return None
            save_path.write_text(text, encoding="utf-8") # 落地为本地文件
            return save_path
        except Exception as e:
            logger.error(f"导出聊天记录失败：{e}")
            return None

    async def edit_card_fields(self, name, new_desc, new_mes):
        """更新同名角色卡的描述与开场白；返回 {exists, ok}，None=异常；None 字段保留原值。
        酒馆 /api/characters/edit 会置空未提供字段，故先取完整角色对象整体回传"""
        try:
            if not await self.check_browser():
                return {"exists": False}
            result = await self.page.evaluate(
                """async ([name, desc, mes]) => {
                    const all = await fetch('/api/characters/all', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r => r.ok ? r.json() : null);
                    const list = Array.isArray(all) ? all : (all && typeof all === 'object' ? Object.values(all) : []);
                    const item = list.find(c => c && c.name === name);
                    if (!item) return {exists: false};
                    const payload = Object.assign({}, item);
                    if (desc !== null) payload.description = desc;
                    if (mes !== null) payload.first_mes = mes;
                    payload.name = name;
                    payload.avatar_url = item.avatar;
                    const r = await fetch('/api/characters/edit', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
                    return {exists: true, ok: r.ok};
                }""",
                [name, new_desc, new_mes]
            )
            if isinstance(result, dict) and result.get("exists") and result.get("ok"):
                await self.page.reload(wait_until="domcontentloaded")
                await self.page.wait_for_selector(".welcomeHeaderVersionDisplay", timeout=60000)
                await self.get_all_chats()
            return result
        except Exception as e:
            logger.error(f"更新角色卡失败：{e}")
            return None

    async def open_browser_auto(self, first : bool):
        """低内存占用模式判断开启"""
        if self.config['tavern']['low_memory_mode']: # 判断并且打开浏览器
            await self.initialize_browser() # 打开浏览器
            # await self.page.wait_for_timeout(800) # 等待防超时
            if first == False: # 初始化时无需打开角色卡
                await self.switch_chats(self.config['basic']['now_chats_name']) # 角色切换保存

    async def check_confirm(self):
        """检测聊天确认框并点击"""
        if await self.check_browser():
            try: # 寻找出脚本和世界书脚本确认
                button_locator_world = self.page.locator('.popup-button-ok[data-result="1"]', has_text="是")
                button_locator_assistant = self.page.locator(".menu_button.interactable", has_text="确认")
                book_locator_world = self.page.locator("span[data-i18n='Worlds/Lorebooks']", has_text="世界/知识书")
            except Exception as e:
                pass
            if await button_locator_world.is_visible(): # 查找存在和点击
                await button_locator_world.click()
            if await button_locator_assistant.is_visible(): # 查找存在和点击
                await button_locator_assistant.click()
            if await book_locator_world.is_visible(): # 查看世界书是否打开
                await self.page.locator("#WIDrawerIcon").click()

    async def get_now_floor(self, number):
        """获取当前楼层并且返回"""
        try:
            if await self.check_browser() and await self.get_chat_Status():
                message_box = self.page.locator("#chat > *") # 获取所有楼层
                message_count = await message_box.count() # 楼层数量
                out = message_count - number
                return out
            else:
                return 0
        except Exception as e:
            logger.error(f"获取楼层错误:{e}")
            return 0

    def extract_quoted_text(self, comp):
        """从 Reply 组件提取被引用消息的纯文本（兼容无 message_str 字段的旧版 AstrBot）"""
        text = getattr(comp, "message_str", None) or ""
        if not text.strip(): # 旧版回退：从被引用消息段链中拼接文本
            parts = []
            for seg in (getattr(comp, "chain", None) or []):
                seg_text = getattr(seg, "text", None) or getattr(seg, "message_str", None) or ""
                if seg_text:
                    parts.append(str(seg_text))
            text = "".join(parts)
        return text.strip()

    async def get_floor_by_quote(self, quoted_text):
        """根据被引用消息文本定位酒馆楼层，返回匹配到的楼层号列表（1 起，旧→新）"""
        quoted_text = (quoted_text or "").strip()
        if not quoted_text:
            return []
        # 兼容性候选：原文 / 去掉"当前共N楼层"前缀的 /酒 回复 / 去掉"酒"/"/酒"前缀的用户指令
        candidates = [quoted_text]
        head, sep, rest = quoted_text.partition("\n")
        if sep and _FLOOR_PREFIX_RE.match(head.strip()) and rest.strip():
            candidates.append(rest.strip())
        parts = quoted_text.split(None, 1)
        if len(parts) == 2 and parts[0].lstrip("/") == "酒":
            candidates.append(parts[1].strip())
        norm_candidates = [" ".join(c.split()) for c in candidates if c.strip()]
        floors = await self.page.evaluate(
            """() => Array.from(document.querySelectorAll('#chat > *')).map(el => {
                const mt = el.querySelector('.mes_block .mes_text');
                return mt ? mt.innerText : null;
            })"""
        )
        matches = []
        for i, floor_text in enumerate(floors or []):
            if not floor_text:
                continue
            norm = " ".join(str(floor_text).split())
            if any(norm == c for c in norm_candidates):
                matches.append(i + 1)
        return matches

    async def close_browser_auto(self):
        """低内存占用模式判断关闭"""
        if self.config['tavern']['low_memory_mode']: # 判断并且关闭浏览器
            await self.close_browser()

    async def close_browser(self):
        """关闭浏览器（加锁，与启动/检查互斥）"""
        async with self._browser_lock:
            await self._close_browser()

    async def _close_browser(self):
        """关闭浏览器与 playwright 驱动的实际逻辑（调用方需持有 _browser_lock）"""
        browser = getattr(self, 'browser', None)
        if browser:
            try:
                if browser.is_connected():
                    await browser.close() # 正常关闭
                else:
                    # 连接已断但进程可能残留：直接杀进程，防止孤儿 chrome 占内存
                    proc = getattr(browser, 'process', None)
                    if proc:
                        proc.kill()
            except Exception as e:
                logger.warning(f"关闭浏览器进程异常: {e}")
        p = getattr(self, 'p', None)
        if p: # 原代码误写 self.playwright（从未赋值），驱动从未真正停止，导致进程残留
            try:
                await p.stop()
            except Exception as e:
                logger.warning(f"停止 playwright 驱动异常: {e}")
        self.browser = None
        self.page = None
        self.p = None

    async def react_message(self, event):
        """给触发指令的聊天消息贴表情回应（仅QQ/aiocqhttp平台，失败静默不影响主流程）"""
        try:
            emoji_cfg = str(self.config['basic'].get('reaction_emoji', '')).strip()
            if not emoji_cfg or event.get_platform_name() != "aiocqhttp":
                return
            client = getattr(event, "bot", None)
            if client is None or event.message_obj.message_id is None:
                return
            # 纯数字 → QQ系统表情ID（如319=比心）；emoji字符 → Unicode码点
            emoji_id = emoji_cfg if emoji_cfg.isdigit() else str(ord(emoji_cfg[0]))
            await client.call_action("set_msg_emoji_like",
                                     message_id=int(event.message_obj.message_id),
                                     emoji_id=emoji_id)
        except Exception as e:
            logger.warning(f"添加表情回应失败（不影响后续流程）: {e}")

    def find_card_comp(self, event):
        """从消息链中查找角色卡组件（支持直接附带、引用图片、引用转发卡片内的图片）"""
        comps = event.get_messages()
        for comp in comps:
            if isinstance(comp, (Image, File)):
                return comp
        for comp in comps:
            if isinstance(comp, Reply) and comp.chain:
                for inner in comp.chain:
                    found = self._find_media_in_comp(inner)
                    if found:
                        return found
        return None

    def _find_media_in_comp(self, comp):
        """递归从组件中查找图片或文件（穿透 Nodes/Node 嵌套）"""
        if isinstance(comp, (Image, File)):
            return comp
        if isinstance(comp, Node):
            for inner in (comp.content or []):
                found = self._find_media_in_comp(inner)
                if found:
                    return found
        if isinstance(comp, Nodes):
            for node in (comp.nodes or []):
                found = self._find_media_in_comp(node)
                if found:
                    return found
        return None
    async def process_image(self, image_comp: Image):
        """统一处理图片落地与后续操作的流程控制"""
        logger.info("已接收到图片，正在落地为本地文件并处理...")
        local_img_path = None
        try: # 1. 调用落地函数，将图片转为本地物理文件路径
            local_img_path = await self.save_to_local_file(image_comp)
            if not local_img_path or not local_img_path.exists(): # 2. 检查文件是否成功生成
                logger.error("图片缓存至本地失败！")
            await self.up_chat_png(local_img_path) # 3. 调用上传操作函数，传入本地物理路径
        except Exception as e: # 捕获整个流程中的任何异常
            logger.error(f"操作过程发生错误: {str(e)}")
        finally: # 5. 强制清理：无论成功还是报错，只要生成了本地文件，最后都删掉
            if local_img_path and local_img_path.exists():
                local_img_path.unlink()

    async def save_to_local_file(self, image_comp) -> Optional[Path]:
        """将组件转换为本地物理文件路径"""
        save_path = self.cache_dir / f"upload_{int(time.time() * 1000)}.png"
        try: # get_file() 通常会返回 AstrBot 下载好的本地临时文件路径
            file_data = await image_comp.get_file()
            if isinstance(file_data, str) and os.path.exists(file_data): # 如果返回的是字符串路径，且文件存在
                shutil.copy2(file_data, save_path)
                return save_path
            elif isinstance(file_data, bytes): # 如果返回的是 bytes 字节流
                with open(save_path, 'wb') as f:
                    f.write(file_data)
                return save_path
        except Exception as e:
            logger.error(f"[调试] 调用 get_file() 失败，尝试降级方案: {e}")
        url = getattr(image_comp, 'url', None)
        if url and str(url).startswith("http"):
            try:# 2. 降级方案：如果是 Image 组件且有 http url，直接用 aiohttp 下载
                async with aiohttp.ClientSession() as session:
                    timeout = aiohttp.ClientTimeout(total=15)
                    async with session.get(url, timeout=timeout) as resp:
                        if resp.status == 200:
                            with open(save_path, 'wb') as f:
                                f.write(await resp.read())
                            return save_path
            except Exception as e:
                logger.error(f"[调试] aiohttp 下载失败: {e}")
        return None

    async def up_chat_png(self, local_file_path):
        """上传角色卡,只支持png图片（调用方已持有 status_running 互斥）"""
        await self.open_browser_auto(False)
        try:
            if await self.check_browser(): # 打开浏览器
                await self.open_chats() # 打开角色导航栏
                self.page.on("filechooser", lambda file_chooser: file_chooser.set_files(local_file_path))# 1. 监听文件选择器事件
                await self.page.click("#character_import_button") # 2. 点击指定的元素
                await self.page.wait_for_selector(".toast.toast-success", timeout=5000,state="visible") # 3. 等待页面响应
                await self.close_chats() # 关闭角色导航栏
                await self.get_all_chats() # 重新获取角色列表
                logger.info(f"成功点击按钮并上传文件: {local_file_path}") # 4. 返回操作结果
        except Exception as e:
            logger.info(f"添加操作失败: {str(e)}")
        await self.close_browser_auto() # 关闭浏览器

    async def del_chat_png(self, dal_name):
        """删除角色卡"""
        if await self.check_browser():
            await self.open_chats()
            await self.page.locator(f"#{self.chats_name_id[dal_name]}").click() # 点击角色卡
            await self.check_confirm() # 检查是否有世界书和酒馆脚本确认
            await self.page.locator("#delete_button").click() # 点击删除角色
            await self.page.locator("#del_char_checkbox").click() # 点击包含聊天记录
            await self.page.locator(".popup-button-ok.menu_button[data-result='1']").click() # 点击确认删除
            await self.close_chats()
            await self.get_all_chats() # 获取角色列表
            if self.config['basic']['now_chats_name'] == dal_name:
                self.config['basic']['now_chats_name'] = "Seraphina"
                self.config.save_config()

    async def kill_chrome_process(self):
        """删除所有chrome进程"""
        try:
            current_os = platform.system()
            if current_os == "Windows":
                # Windows: 强制终止所有 chrome.exe 进程
                # /F 强制终止, /T 终止子进程, /IM 映像名称
                command = ["taskkill", "/F", "/T", "/IM", "chrome.exe"]
                # 也可以顺带杀掉 chromium
                subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["taskkill", "/F", "/T", "/IM", "chromium.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Linux/Mac: 强制终止所有 chrome 和 chromium 进程
                # -9 发送 SIGKILL 信号
                subprocess.run(["pkill", "-9", "chrome"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["pkill", "-9", "chromium"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["pkill", "-9", "chromium-browser"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[系统清理] 已尝试清理所有后台 Chrome/Chromium 进程。")
            return True
        except FileNotFoundError: # 如果系统没有 pkill 命令，不会报错，静默处理
            pass
        except Exception as e:
            print(f"[系统清理] 清理 Chrome 进程时发生错误: {e}")
            return False

    def count_chrome_processes(self):
        """统计系统 chrome/chromium 进程数量，返回 (总数, 明细列表)"""
        current_os = platform.system()
        total = 0
        detail = []
        try:
            if current_os == "Windows":
                for image in ("chrome.exe", "chromium.exe"):
                    r = subprocess.run(
                        ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                        capture_output=True, text=True, timeout=10
                    )
                    # CSV 行以引号开头；无匹配时 tasklist 输出 INFO: 行，不算进程数
                    n = len([line for line in r.stdout.splitlines() if line.strip().startswith('"')])
                    if n:
                        detail.append(f"{image}: {n}")
                    total += n
            else:
                for name in ("chrome", "chromium", "chromium-browser"):
                    r = subprocess.run(
                        ["pgrep", "-x", name], capture_output=True, text=True, timeout=10
                    )
                    n = len([line for line in r.stdout.splitlines() if line.strip()])
                    if n:
                        detail.append(f"{name}: {n}")
                    total += n
        except Exception as e:
            return -1, [f"""统计失败: {e}"""]
        return total, detail

    async def start_tavern(self):
        """启动插件目录中的酒馆（后台拉起 server.js）"""
        parsed = urlparse(self.ST_URL)
        host = parsed.hostname or parsed.path.split(":")[0]
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # 已运行检查
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
            writer.close()
            await writer.wait_closed()
            return True, """酒馆已在运行"""
        except Exception:
            pass
        # 定位目录
        st_dir = self.plugin_dir / "SillyTavern"
        if not (st_dir / "server.js").exists():
            return False, """未在插件目录找到 SillyTavern，请先运行 download_sillytavern 脚本下载"""
        # Node 检查
        node_path = shutil.which("node")
        if not node_path:
            if os.name == "nt":
                return False, """未检测到 Node.js，SillyTavern 需要 Node.js 18 或更高版本。请安装: winget install OpenJS.NodeJS.LTS"""
            return False, """未检测到 Node.js，SillyTavern 需要 Node.js 18 或更高版本。请通过 nvm 或官网安装"""
        # 后台启动
        log_path = self.cache_dir / "sillytavern.log"
        try:
            if hasattr(self, "_st_log") and self._st_log:
                try:
                    self._st_log.close()
                except Exception:
                    pass
            self._st_log = open(log_path, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": str(st_dir),
                "stdout": self._st_log,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen([node_path, str(st_dir / "server.js")], **popen_kwargs)
            self._st_proc = proc
            proc.wait()
            self._st_proc = None
        except Exception as e:
            return False, f"""启动失败: {e}"""
        # 等待就绪（最长约 60 秒）
        for _ in range(30):
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2)
                writer.close()
                await writer.wait_closed()
                return True, """酒馆已启动"""
            except Exception:
                await asyncio.sleep(2)
        return False, f"""酒馆启动超时，请查看日志: {log_path}"""

    async def stop_tavern(self):
        """停止插件目录内启动的 SillyTavern 服务进程；返回 (ok, msg)"""
        # 优先：已跟踪进程直接终止
        proc = getattr(self, "_st_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                else:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
            except Exception as e:
                logger.warning(f"stop_tavern: 终止句柄进程异常: {e}")
            self._st_proc = None
            return True, """酒馆已关闭"""
        # 兜底：按配置端口查杀监听进程（仅在内置酒馆场景下调用）
        try:
            parsed = urlparse(self.ST_URL)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except Exception:
            host, port = "127.0.0.1", 8000
        try:
            if os.name == "nt":
                import re as _re
                out = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
                ).stdout
                pid = None
                for line in out.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.strip().split()
                        if parts:
                            pid = parts[-1]
                            break
                if pid:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", pid],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    return True, f"""已通过端口 {port} 定位并关闭酒馆进程"""
            else:
                import shlex
                subprocess.run(
                    ["fuser", "-k", f"{port}/tcp"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                )
                return True, f"""已通过端口 {port} 关闭酒馆进程"""
        except Exception as e:
            logger.warning(f"stop_tavern 兜底查杀异常: {e}")
        return False, """未找到酒馆进程，可能尚未启动或已被手动关闭"""

    async def restart_tavern(self):
        """重启酒馆：先停后启；返回 (ok, msg)"""
        await self.stop_tavern()
        await asyncio.sleep(2)
        return await self.start_tavern()

    async def page_stop_tavern(self):
        """停止酒馆服务（供 WebUI 分体按钮调用）"""
        ok, msg = await self.stop_tavern()
        return json_response({"ok": ok, "message": msg})

    async def page_restart_tavern(self):
        """重启酒馆服务（供 WebUI 分体按钮调用）"""
        ok, msg = await self.restart_tavern()
        return json_response({"ok": ok, "message": msg})



# 机器人指令定义
    # @filter.command("test")
    # async def test(self, event: AstrMessageEvent):
    #     """这是一个测试指令"""
    #     logger.info("触发了 test 指令")
    #     await bartender_crawler.open_browser_auto(self, False)
    #     await bartender_crawler.switch_chats(self, "创世神喻")
    #     await bartender_crawler.close_browser_auto(self)
    #     yield event.plain_result(f"喵~这是测试指令的回复")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒停止")
    async def command_stop_all(self, event: AstrMessageEvent):
        """完全关闭：停止酒馆主程序(node 进程)、插件浏览器，并清理后台所有 chrome/chromium 进程"""
        st_ok, st_msg = await self.stop_tavern() # 先停酒馆主程序（node server.js）
        await bartender_crawler.close_browser(self) # 再优雅关闭插件自己的浏览器
        await bartender_crawler.kill_chrome_process(self) # 兜底清理残留进程
        yield event.plain_result(f"""酒馆主程序：{st_msg}
已关闭浏览器并清理所有后台 Chrome/Chromium 进程""")

    @filter.command("酒")
    @_access_required
    async def command_send_message(self, event: AstrMessageEvent):
        """酒馆发送信息"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip()
                if user_message and len(user_message.split()) > 1:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息（QQ不支持流式输出）
                    user_message = ' '.join(user_message.split()[1:])
                    send_result = await bartender_crawler.send_message(self, user_message) # 发送消息至酒馆
                    if send_result != "正常":
                        yield event.plain_result(f"""发送失败: {(send_result)}""")
                        return
                    message_text = await bartender_crawler.get_new_message_text(self) # 获取最新的消息文本
                    remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                    if message_text:
                        if self.config['basic'].get('show_floor_count'):
                            yield event.plain_result(f"{f"""当前共{remaining}楼层"""}\n\n{message_text}")
                        else:
                            yield event.plain_result(message_text)
                    else:
                        yield event.plain_result("""合并消息为空""")
                else:
                    yield event.plain_result("""禁止输入为空""")
            except Exception as e:
                logger.error(f"酒指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒人设")
    @_access_required
    async def command_persona_bind(self, event: AstrMessageEvent):
        """绑定当前用户的人设；无参数时查看绑定状态与人设列表"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                session_key = self.get_persona_session_key(event)
                user_message = event.message_str.strip()
                tokens = user_message.split()
                if len(tokens) > 1: # 子命令模式
                    if tokens[1] == "绑定": # /酒人设 绑定 [名字]
                        if len(tokens) < 3:
                            yield event.plain_result("""请输入：/酒人设 绑定 [人设名]""")
                            return
                        persona_name = " ".join(tokens[2:])
                        ok, avatar_id = await bartender_crawler.switch_persona(self, persona_name)
                        if ok:
                            self.persona_bindings[session_key] = {"name": persona_name, "avatar_id": avatar_id}
                            self._save_persona_bindings()
                            yield event.plain_result(f"""已绑定人设：{persona_name}""")
                        else:
                            yield event.plain_result(f"""未找到人设：{persona_name}，发送 /酒人设 查看全部人设""")
                        return
                    if tokens[1] == "查看" and len(tokens) >= 3: # /酒人设 查看 [名字] → 查看人设详情
                        persona_name = " ".join(tokens[2:])
                        if not await bartender_crawler.open_persona_panel(self):
                            yield event.plain_result("打开人设面板失败")
                            return
                        try:
                            if not await bartender_crawler._select_persona_block(self, persona_name):
                                yield event.plain_result(f"""未找到人设：{persona_name}""")
                                return
                            desc = await self.page.locator("#persona_description").input_value()
                            display_name = await self.page.locator("#your_name").inner_text()
                            avatar_id = ""
                            blocks = self.page.locator("#user_avatar_block .avatar-container.selected")
                            if await blocks.count():
                                avatar_id = await blocks.first.get_attribute("data-avatar-id") or ""
                            pos_sel = self.page.locator("#persona_description_position")
                            pos_val = await pos_sel.evaluate("el => el.options[el.selectedIndex]?.text || ''") if await pos_sel.count() else ""
                            lines = [f"""人设：{display_name}""",
                                     f"""头像ID：{(avatar_id or """无""")}"""]
                            if pos_val:
                                 lines.append(f"""位置：{pos_val}""")
                            lines.append(f"""描述：
{(desc or """[空]""")}""")
                            yield event.plain_result("\n".join(lines))
                        finally:
                            await bartender_crawler.close_persona_panel(self)
                        return
                    if tokens[1] == "修改": # /酒人设 修改 名字 [内容]：仅名字删除，不存在则新建；内容用[]包裹可含空格换行
                        rest = re.sub(r"^酒人设\s+修改\s*", "", user_message)
                        persona_name, segs = _split_bracket_args(rest)
                        if not persona_name:
                            yield event.plain_result("""请输入：/酒人设 修改 名字 [内容]（内容用中括号包裹，防止空格换行导致错误；仅名字则删除该人设）""")
                            return
                        description = "\n".join(segs) if segs else ""
                        await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                        personas, _ = await bartender_crawler.get_personas(self) # 判断人设是否存在
                        exists = bool(personas is not None and persona_name in personas)
                        if exists:
                            if description:
                                ok, msg = await bartender_crawler.set_persona_description(self, persona_name, description)
                                action = "update"
                            else:
                                ok, msg = await bartender_crawler.delete_persona(self, persona_name)
                                action = "delete"
                        else:
                            ok, msg = await bartender_crawler.create_persona(self, persona_name, description)
                            action = "create"
                        # action texts: update=更新, delete=删除, create=新建
                        if ok:
                            if action == "delete":
                                yield event.plain_result(f"""已删除人设：{persona_name}""")
                            elif action == "create" and not description:
                                yield event.plain_result(f"""已新建空人设：{persona_name}""")
                            else:
                                yield event.plain_result(f"""已{( '更新' if action == 'update' else '删除' if action == 'delete' else '新建') }人设：{persona_name}""")
                        else:
                            yield event.plain_result(f"""{( '更新' if action == 'update' else '删除' if action == 'delete' else '新建') }人设失败: {(msg)}""")
                        return
                    if tokens[1] == "解绑": # /酒人设 解绑
                        if session_key in self.persona_bindings:
                            del self.persona_bindings[session_key]
                            self._save_persona_bindings()
                            yield event.plain_result("""已解除绑定人设""")
                        else:
                            yield event.plain_result("""当前未绑定人设""")
                        return
                    yield event.plain_result("""未知子命令，可用：绑定、查看、修改、解绑；发送 /酒人设 查看全部人设""")
                    return
                # 查看模式：/酒人设
                bound = self.persona_bindings.get(session_key)
                bound_text = f"{bound['name']}" if bound else """无"""
                personas, current = await bartender_crawler.get_personas(self)
                if personas is None:
                    yield event.plain_result("""浏览器连接失败，无法获取人设列表""")
                    return
                lines = [f"""当前绑定人设：{bound_text}""",
                         f"""酒馆当前人设：{(current or """无""")}"""]
                if personas:
                    lines.append("""人设列表：""")
                    lines.extend(f"""- {name}（{avatar_id}）"""
                                 for name, avatar_id in personas.items())
                else:
                    lines.append("""酒馆中暂无任何人设，可先在酒馆页面创建""")
                yield event.plain_result("\n".join(lines))
            except Exception as e:
                logger.error(f"酒人设指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")

    @filter.command("酒重生成")
    @_access_required
    async def command_rest_message(self, event: AstrMessageEvent):
        """重新生成当前楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = self.config['basic']['now_chats_name']
                if user_message != "" and user_message != None:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息（QQ不支持流式输出）
                    rest_result = await bartender_crawler.rest_message(self)
                    if rest_result != "正常":
                        yield event.plain_result(f"""重调失败: {(rest_result)}""")
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result("""合并消息为空""")
                else:
                    yield event.plain_result("""禁止输入为空""")
            except Exception as e:
                logger.error(f"酒重生成指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒查看")
    @_access_required
    async def command_get_message(self, event: AstrMessageEvent):
        """获取最新楼层；引用消息时可定位其楼层数"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                quoted_text = ""
                for comp in event.get_messages(): # 检测消息中是否带引用
                    if isinstance(comp, Reply):
                        quoted_text = bartender_crawler.extract_quoted_text(self, comp)
                        break
                if quoted_text: # 引用模式：定位被引用消息对应的楼层
                    if not await bartender_crawler.check_browser(self):
                        yield event.plain_result("""浏览器连接失败""")
                        return
                    matches = await bartender_crawler.get_floor_by_quote(self, quoted_text)
                    if not matches:
                        yield event.plain_result("""未在酒馆中找到与引用消息匹配的楼层""")
                    elif len(matches) == 1:
                        yield event.plain_result(f"""引用消息为第 {matches[0]} 层""")
                    else:
                        nums = """、""".join(str(m) for m in matches)
                        yield event.plain_result(f"""引用消息匹配到多层：第 {nums} 层""")
                    return
                bot_id =event.message_obj.self_id # 获取bot_id
                forward_message = await bartender_crawler.get_new_message(self, bot_id) # 获取信息
                remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                if forward_message != None:
                    yield event.plain_result(f"""当前共{remaining}楼层""")
                    yield MessageEventResult(chain=[forward_message])
                else:
                    yield event.plain_result("""合并消息为空""")
            except Exception as e:
                logger.error(f"酒查看指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")

    @filter.command("酒状态")
    @_access_required
    async def command_get_status(self, event: AstrMessageEvent):
        """获取当前所有状态"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                await self.get_chat_Status()
                if self.config['basic']['now_chats_name'] == None:
                    chat = """无角色卡"""
                else:
                    chat = self.config['basic']['now_chats_name']
                logger.info(f"角色卡：{chat}")
                if await bartender_crawler.check_browser(self):
                    connect_status = """正常"""
                else:
                    connect_status = """失败"""
                chats = '\n'.join(self.chats_name_id.keys())
                session_key = self.get_persona_session_key(event)
                bound = self.persona_bindings.get(session_key)
                bound_text = f"{bound['name']}" if bound else """无"""
                yield event.plain_result(f"""当前角色卡为：{chat}
链接状态：{connect_status}
你的绑定人设：{bound_text}
角色列表：
{chats}""")
            except Exception as e:
                logger.error(f"酒状态指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")

    @filter.command("酒切换")
    @_access_required
    async def command_chat_switch(self, event: AstrMessageEvent):
        """酒馆切换角色卡"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip()
                if user_message != "酒切换" and len(user_message.split()) > 1:
                    chat_name = (user_message.split()[1:])[0]
                    if await bartender_crawler.switch_chats(self, chat_name):
                        yield event.plain_result(f"""角色卡切换至：{chat_name}""")
                    else:
                        yield event.plain_result(f"""未找到角色卡：{chat_name}""")
                else:
                    yield event.plain_result("""消息不能为空""")
            except Exception as e:
                logger.error(f"酒切换指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")

    @filter.command("酒删除")
    @_access_required
    async def command_del_message(self, event: AstrMessageEvent):
        """删除聊天楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                del_message = None
                del_status = False
                remaining = None
                user_message = event.message_str.strip() # 获取输入消息
                if user_message == "酒删除" : # 判断消息是否为空
                    del_message = 1
                    del_status = await bartender_crawler.del_message(self, abs(del_message))
                    remaining = await bartender_crawler.get_now_floor(self, (abs(del_message)))
                else:
                    try: # 避免错误
                        user_message = (user_message.split()[1:])[0]
                        del_message = int(user_message)
                        del_status = await bartender_crawler.del_message(self, abs(del_message))
                        remaining = await bartender_crawler.get_now_floor(self, (abs(del_message)))
                    except Exception as e:
                        logger.error(f"楼层数解析失败: {e}")
                        yield event.plain_result("""请输入数字""")
                        return
                if del_status and del_message != None:
                    yield event.plain_result(f"""已删除{(abs(del_message))}楼层
剩余{remaining}楼层""")
                else:
                    yield event.plain_result("""输入楼层数异常或最低""")
            except Exception as e:
                logger.error(f"酒删除指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")

    @filter.command("酒加卡")
    @_access_required
    async def upload_chat_command(self, event: AstrMessageEvent):
        """添加或更新角色卡：附带PNG图片上传，或文字建卡/更新已有卡 /酒加卡 名字 [角色描述] [开场白]"""
        if self.status_running: # 判断运行状态
            self.status_running = False
            try:
                image_comp = bartender_crawler.find_card_comp(self, event)
                if image_comp: # 情况 A：同条消息附带图片或引用了含图消息，直接进入处理流程
                    await bartender_crawler.process_image(self, image_comp) # process_image无返回值，无需yield
                    chats = '\n'.join(self.chats_name_id.keys())
                    yield event.plain_result(f"""角色列表：
{chats}""")
                    return
                rest = re.sub(r"^酒加卡\s*", "", event.message_str.strip())
                if rest: # 情况 B：文字建卡或更新已有卡 /酒加卡 名字 [角色描述] [开场白]，[/]=不改 []=清空 省略=不改
                    name, segs = _split_bracket_args(rest)
                    if not name or not segs:
                        yield event.plain_result("""请输入：/酒加卡 名字 [角色描述] [开场白]（描述与开场白用中括号包裹，可含空格换行；[/]=不改 []=清空 省略=不改；开场白可省略）""")
                        return
                    desc = _norm_field(segs[0])
                    mes = _norm_field(segs[1]) if len(segs) > 1 else None
                    await bartender_crawler.open_browser_auto(self, False)
                    try:
                        result = await bartender_crawler.edit_card_fields(self, name, desc, mes)
                    finally:
                        await bartender_crawler.close_browser_auto(self)
                    if result is None: # 异常时中止，防止误走建卡流程产生重复卡片
                        yield event.plain_result("""更新角色卡检查异常，已中止操作，请稍后重试""")
                        return
                    if result.get("exists"): # 已有同名卡：更新流程
                        chats = '\n'.join(self.chats_name_id.keys())
                        if result.get("ok"):
                            yield event.plain_result(f"""已更新角色卡「{name}」
角色列表：
{chats}""")
                        else:
                            yield event.plain_result(f"""更新角色卡「{name}」失败，请稍后重试""")
                        return
                    # 不存在同名卡：回落到文字建卡流程（[/]/省略视为空内容）
                    card_path = _build_card_png(name, "" if desc is None else desc, "" if mes is None else mes)
                    try:
                        await bartender_crawler.up_chat_png(self, card_path)
                        chats = '\n'.join(self.chats_name_id.keys())
                        yield event.plain_result(f"""已创建角色卡「{name}」
角色列表：
{chats}""")
                    finally:
                        if card_path.exists():
                            card_path.unlink()
                    return
                # 情况 C：指令和图片分条发送。为该用户开启等待状态，设定有效期
                session_key = f"{event.get_group_id()}_{event.get_sender_id()}"
                self.waiting_sessions[session_key] = time.time() + int(self.config['tavern']['upload_interval'])
                yield event.plain_result(f"""请在{self.config['tavern']['upload_interval']}秒内发送角色卡""")
            except Exception as e:
                logger.error(f"酒加卡指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")


    @filter.command("酒删卡")
    @_access_required
    async def del_chat_command(self, event: AstrMessageEvent):
        """删除聊天楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip() # 获取输入消息
                if user_message == "酒删卡" or len(user_message.split()) <= 1: # 判断消息是否为空
                    yield event.plain_result("""请输入角色卡名称""")
                else:
                    user_message = (user_message.split()[1:])[0]
                    if user_message in self.chats_name_id:
                        await bartender_crawler.del_chat_png(self, user_message) # 删除对应名字角色卡
                        chats = '\n'.join(self.chats_name_id.keys())
                        yield event.plain_result(f"""当前角色列表：
{chats}""")
                    elif user_message == "Seraphina":
                        yield event.plain_result("""禁止删除默认角色""")
                    else:
                        yield event.plain_result("""未查找到角色卡名称""")
            except Exception as e:
                logger.error(f"酒删卡指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""等待其他操作完成""")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒启动")
    async def command_start_tavern(self, event: AstrMessageEvent):
        """启动目录中的酒馆"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.react_message(self, event)
                should_connect, result = await bartender_crawler.start_tavern(self)
                if not should_connect:
                    yield event.plain_result(result)
                    return
                if self.config['tavern']['low_memory_mode']:
                    await bartender_crawler.open_browser_auto(self, False)
                    await bartender_crawler.check_1000page(self)
                    await bartender_crawler.get_all_chats(self)
                    await bartender_crawler.close_browser_auto(self)
                else:
                    await bartender_crawler.initialize_browser(self)
                    await bartender_crawler.check_1000page(self)
                    await bartender_crawler.get_all_chats(self)
                    await bartender_crawler.switch_chats(self, self.config['basic']['now_chats_name'])
                yield event.plain_result(f"{result}{"""，已自动连接"""}")
            except Exception as e:
                logger.error(f"酒启动指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒重启")
    async def command_restart_tavern(self, event: AstrMessageEvent):
        """重启目录中的酒馆（先停止后启动），完成后自动连接浏览器"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.react_message(self, event)
                should_connect, result = await bartender_crawler.restart_tavern(self)
                if not should_connect:
                    yield event.plain_result(result)
                    return
                if self.config['tavern']['low_memory_mode']:
                    await bartender_crawler.open_browser_auto(self, False)
                    await bartender_crawler.check_1000page(self)
                    await bartender_crawler.get_all_chats(self)
                else:
                    await bartender_crawler.initialize_browser(self)
                    await bartender_crawler.check_1000page(self)
                    await bartender_crawler.get_all_chats(self)
                    await bartender_crawler.switch_chats(self, self.config['basic']['now_chats_name'])
                yield event.plain_result(f"{result}{"""，已自动连接"""}")
            except Exception as e:
                logger.error(f"酒重启指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒进程")
    async def chrome_status_command(self, event: AstrMessageEvent):
        """查看后台 chrome/chromium 进程数量与插件浏览器状态；子命令 停止 仅关闭浏览器进程"""
        tokens = event.message_str.strip().split()
        if len(tokens) > 1 and tokens[1] == "停止": # /酒进程 停止：仅关闭浏览器并清理残留进程（不动酒馆主程序）
            await bartender_crawler.close_browser(self)
            await bartender_crawler.kill_chrome_process(self)
            yield event.plain_result("""已关闭浏览器并清理所有后台 Chrome/Chromium 进程""")
            return
        total, detail = bartender_crawler.count_chrome_processes(self)
        if self.browser and self.browser.is_connected():
            browser_state = """已连接"""
        elif self.browser:
            browser_state = """连接已断开"""
        else:
            browser_state = """未启动"""
        driver_state = """运行中""" if getattr(self, 'p', None) else """未启动"""
        lines = [f"""系统 chrome/chromium 进程总数：{total}"""]
        if detail:
            lines.append(f"""明细：{("，".join(detail))}""")
        lines.append(f"""插件浏览器：{browser_state}""")
        lines.append(f"""playwright 驱动：{driver_state}""")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒重置")
    async def reset_plugin_command(self, event: AstrMessageEvent):
        """重置插件所有参数"""
        await bartender_crawler.open_browser_auto(self, False)
        self.chats_name_id = {} # 初始化角色字典
        self.status_running = False # 消息状态初始化
        self.cache_dir = Path("data/temp/astrbot_plugin_bartender_extra") # 初始化本地缓存文件夹路径
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.waiting_sessions = {} # 初始化会话状态字典，用于记录哪些用户正在等待发送图片，格式为: {"群号_用户ID": 过期时间戳}
        self.chat_mode_creators = {} # 清空酒馆聊天模式创建记录
        self.chat_mode_user_keys = set() # 清空按用户聊天模式
        self.chat_mode_group_keys = {} # 清空按群聊天模式
        self.config['basic']['now_chats_name'] = "Seraphina" # 当前角色切换至默认
        await bartender_crawler.get_all_chats(self) # 重新获取所有角色
        await bartender_crawler.switch_chats(self, "Seraphina") # 切换至默认卡
        await bartender_crawler.close_browser_auto(self)
        yield event.plain_result("""已重置获取所有变量""")

    @filter.command("酒新建")
    @_access_required
    async def command_new_chat(self, event: AstrMessageEvent):
        """与当前角色开始新对话"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                result = await bartender_crawler.start_new_chat(self)
                if result != "正常":
                    yield event.plain_result(f"""新对话失败: {(result)}""")
                else:
                    remaining = await bartender_crawler.get_now_floor(self, 0) # 获取当前楼层数
                    yield event.plain_result(f"""已开始新对话，当前共{remaining}楼层""")
            except Exception as e:
                logger.error(f"酒新建指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒续写")
    @_access_required
    async def command_continue_message(self, event: AstrMessageEvent):
        """续写最新楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = self.config['basic']['now_chats_name']
                if user_message != "" and user_message != None:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                    cont_result = await bartender_crawler.continue_message(self)
                    if cont_result != "正常":
                        yield event.plain_result(f"""续写失败: {(cont_result)}""")
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result("""合并消息为空""")
                else:
                    yield event.plain_result("""无角色卡""")
            except Exception as e:
                logger.error(f"酒续写指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒中断")
    @_access_required
    async def command_stop_generation(self, event: AstrMessageEvent):
        """中断当前酒馆生成"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                result = await bartender_crawler.stop_generation(self)
                yield event.plain_result(result)
            except Exception as e:
                logger.error(f"酒中断指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒备选")
    @_access_required
    async def command_swipe_message(self, event: AstrMessageEvent):
        """切换上一条/下一条备选回复，参数 上/下，默认下"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip()
                tokens = user_message.split()
                arg = tokens[1] if len(tokens) > 1 else "下"
                if arg in ("上", "左", "prev", "previous", "上一个"):
                    direction = "prev"
                else:
                    direction = "next"
                user_message = self.config['basic']['now_chats_name']
                if user_message != "" and user_message != None:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                    swipe_result = await bartender_crawler.swipe_message(self, direction)
                    if swipe_result != "正常":
                        yield event.plain_result(swipe_result)
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result("""合并消息为空""")
                else:
                    yield event.plain_result("""无角色卡""")
            except Exception as e:
                logger.error(f"酒备选指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒导出")
    @_access_required
    async def command_export_chat(self, event: AstrMessageEvent):
        """导出当前聊天记录为文件发送"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                path = await bartender_crawler.export_current_chat(self)
                if path and path.exists():
                    yield event.plain_result("""已导出当前聊天记录""")
                    yield event.chain_result([File.fromFileSystem(str(path))])
                else:
                    yield event.plain_result("""导出失败，未找到当前聊天记录""")
            except Exception as e:
                logger.error(f"酒导出指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒统计")
    @_access_required
    async def command_get_stats(self, event: AstrMessageEvent):
        """查看当前角色聊天统计"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                data = await bartender_crawler.get_current_stats(self)
                if not data:
                    yield event.plain_result("""获取统计失败或无角色卡""")
                    return
                name = data.get("name") or """未知"""
                s = data.get("stats")
                if not s:
                    yield event.plain_result(f"""角色卡：{name}
未找到该角色的聊天统计""")
                    return
                gen_sec = round((s.get("total_gen_time") or 0) / 1000, 1) # 毫秒转秒
                lines = [
                    f"""角色卡：{name}""",
                    f"""消息数：用户 {(s.get('user_msg_count', 0))} 条 / 角色 {(s.get('non_user_msg_count', 0))} 条""",
                    f"""字数：用户 {(s.get('user_word_count', 0))} / 角色 {(s.get('non_user_word_count', 0))}""",
                    f"""备选回复(swipe)：{(s.get('total_swipe_count', 0))}""",
                    f"""生成总耗时：{gen_sec} 秒""",
                    f"""聊天文件大小：{(s.get('chat_size', 0))} 字节""",
                ]
                last = s.get("date_last_chat")
                first = s.get("date_first_chat")
                if last and last < 1e14: # 排除远期哨兵值
                    lines.append(f"""最近对话：{(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last / 1000)))}""")
                if first and first < 1e14:
                    lines.append(f"""首次对话：{(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first / 1000)))}""")
                yield event.plain_result("\n".join(lines))
            except Exception as e:
                logger.error(f"酒统计指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒开始")
    @_access_required
    async def command_start_chat_mode(self, event: AstrMessageEvent):
        """开启酒馆聊天模式：直接发送消息即转酒馆，无需 /酒 前缀；带"群聊"按当前群生效"""
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        creator = f"{group_id}_{user_id}"
        if creator in self.chat_mode_creators: # 开始者只能一次，不能同时用户+群聊
            yield event.plain_result("""您已开启过酒馆聊天模式，请先 /酒结束""")
            return
        user_message = event.message_str.strip()
        is_group_mode = "群聊" in user_message.split()
        if is_group_mode and not group_id: # 私聊不支持群聊模式
            yield event.plain_result("""私聊不支持群聊模式，已按用户开启""")
            is_group_mode = False
        if is_group_mode:
            gid = str(group_id)
            if gid in self.chat_mode_group_keys: # 本群已由他人开启群聊模式
                yield event.plain_result("""本群已开启群聊模式""")
                return
            self.chat_mode_group_keys[gid] = creator
            self.chat_mode_creators[creator] = ("group", gid)
            scope = """本群"""
        else:
            user_key = f"{group_id}_{user_id}"
            self.chat_mode_user_keys.add(user_key)
            self.chat_mode_creators[creator] = ("user", user_key)
            scope = """本人"""
        chat = self.config['basic'].get('now_chats_name') or """无角色卡"""
        yield event.plain_result(
            f"""已进入酒馆聊天模式（{scope}）
当前角色：{chat}
直接发送消息即可（无需 /酒 前缀）
/酒结束 退出"""
        )

    @filter.command("酒结束")
    @_access_required
    async def command_end_chat_mode(self, event: AstrMessageEvent):
        """结束调用者自己创建的酒馆聊天模式"""
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        creator = f"{group_id}_{user_id}"
        if creator not in self.chat_mode_creators:
            yield event.plain_result("""您未开启酒馆聊天模式""")
            return
        mode, scope = self.chat_mode_creators.pop(creator) # 结束这个用户创建的开始
        if mode == "user":
            self.chat_mode_user_keys.discard(scope)
        else:
            self.chat_mode_group_keys.pop(scope, None)
        yield event.plain_result("""已退出酒馆聊天模式""")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒权限")
    async def command_permissions(self, event: AstrMessageEvent):
        """管理酒命令访问权限：管理[开/关] / 白名单[群号|移除 群号] / 黑名单[群号|移除 群号]"""
        user_message = event.message_str.strip()
        tokens = user_message.split()
        if len(tokens) < 2: # 无子命令，查看当前设置
            admin_only = bool(self.config['permission'].get('admin_only'))
            whitelist = [str(x) for x in (self.config['permission'].get('whitelist_groups') or [])]
            blacklist = [str(x) for x in (self.config['permission'].get('blacklist_groups') or [])]
            yield event.plain_result(
                """当前权限设置""" + "\n"
                + f"""管理员模式：{("""开""")}""" + "\n"
                + f"""白名单群聊：{(", ".join(whitelist) or """无""")}""" + "\n"
                + f"""黑名单群聊：{(", ".join(blacklist) or """无""")}""" + "\n"
                + """用法：/酒权限 管理 开|关｜/酒权限 白名单 [群号|移除 群号]｜/酒权限 黑名单 [群号|移除 群号]"""
            )
            return
        sub = tokens[1]
        if sub == "管理":
            if len(tokens) < 3:
                yield event.plain_result(f"""管理员模式当前为：{("""开""")}""")
                return
            sw = tokens[2]
            if sw == "开":
                self.config['permission']['admin_only'] = True
            elif sw == "关":
                self.config['permission']['admin_only'] = False
            else:
                yield event.plain_result("""参数错误，用法：/酒权限 管理 开|关""")
                return
            self.config.save_config()
            yield event.plain_result(f"""已{("""开启""")}管理员模式（所有酒命令{("""仅管理员""")}可用）""")
            return
        if sub in ("白名单", "黑名单"):
            key = 'whitelist_groups' if sub == "白名单" else 'blacklist_groups'
            sub_label = f"""白名单"""
            groups = [str(x) for x in (self.config['permission'].get(key) or [])]
            if len(tokens) >= 4 and tokens[2] in ("移除", "删除", "-"):
                gid = tokens[3]
                groups = [g for g in groups if g != gid]
                self.config['permission'][key] = groups
                self.config.save_config()
                yield event.plain_result(f"""已从{sub_label}移除群聊：{gid}""")
                return
            if len(tokens) >= 3 and tokens[2] not in ("移除", "删除", "-"):
                gid = tokens[2]
                if gid not in groups:
                    groups.append(gid)
                    self.config['permission'][key] = groups
                    self.config.save_config()
                yield event.plain_result(f"""已将群聊 {gid} 加入{sub_label}，当前{sub_label}：{(", ".join(groups) or """无""")}""")
                return
            yield event.plain_result(f"""{sub_label}当前群聊：{(", ".join(groups) or """无""")}""")
            return
        yield event.plain_result("""未知子命令，用法：/酒权限 管理 开|关｜/酒权限 白名单 [群号|移除 群号]｜/酒权限 黑名单 [群号|移除 群号]""")

    @filter.command("酒世界书")
    @_access_required
    async def command_world_info(self, event: AstrMessageEvent):
        """世界书：无参列出全部+已启用；查看 [名字] 查看条目；切换 [名字] 启用/停用"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip()
                tokens = user_message.split()
                if len(tokens) > 1 and tokens[1] == "查看":
                    if len(tokens) < 3:
                        yield event.plain_result("""请输入：/酒世界书 查看 [名字]""")
                        return
                    name = " ".join(tokens[2:])
                    data = await bartender_crawler.get_world_info_detail(self, name)
                    if not data:
                        yield event.plain_result(f"""未找到世界书：{name}""")
                        return
                    entries = data.get("entries") or {}
                    if isinstance(entries, dict):
                        entry_list = list(entries.values())
                    elif isinstance(entries, list):
                        entry_list = entries
                    else:
                        entry_list = []
                    lines = [f"""世界书：{name}""",
                             f"""共 {(len(entry_list))} 条目"""]
                    on_text = """启用"""
                    off_text = """停用"""
                    for i, entry in enumerate(entry_list, 1):
                        enabled = not entry.get("disable", False)
                        keys = entry.get("key", "")
                        content = (entry.get("content", "") or "").strip()
                        lines.append(f"""{i}. [{(on_text if enabled else off_text)}] 触发词：{keys}""")
                        if content:
                            lines.append(f"   {content[:200]}")
                    yield event.plain_result("\n".join(lines))
                elif len(tokens) > 1 and tokens[1] == "切换":
                    if len(tokens) < 3:
                        yield event.plain_result("""请输入：/酒世界书 切换 [名字]""")
                        return
                    name = " ".join(tokens[2:])
                    await bartender_crawler.react_message(self, event)
                    ok, msg = await bartender_crawler.toggle_world_info(self, name)
                    msg_t = msg
                    if ok:
                        yield event.plain_result(f"""世界书「{name}」{msg_t}""")
                    else:
                        yield event.plain_result(f"""切换失败：{name}，{msg_t}""")
                else:
                    # 列出所有世界书 + 已启用
                    data = await bartender_crawler.list_world_infos(self)
                    if not data:
                        yield event.plain_result("""获取世界书列表失败""")
                        return
                    wi_list = data.get("list") or []
                    active = data.get("active") or []
                    none_text = """无"""
                    no_char = "无角色卡"
                    lines = [f"""当前角色：{no_char}"""]
                    lines.append(f"""已启用世界书：{(", ".join(active) if active else none_text)}""")
                    if wi_list:
                        lines.append("---")
                        lines.append("""所有世界书：""")
                        for item in wi_list:
                            lines.append(f"- {item.get('name', item.get('file_id', '?'))}")
                    else:
                        lines.append("""酒馆中暂无世界书""")
                    yield event.plain_result("\n".join(lines))
            except Exception as e:
                logger.error(f"酒世界书指令异常: {e}")
                yield event.plain_result("""指令执行异常，请稍后重试""")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("""正在Shake~，请稍作等待""")

    @filter.command("酒帮助")
    @_access_required
    async def help_command(self, event: AstrMessageEvent):
        """指令帮助指南"""
        yield event.plain_result("""指令帮助""" + "\n" + "基础用法与示例见上表；完整指令见 /酒帮助。")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_received(self, event: AstrMessageEvent):
        """全局监听消息，用于捕捉等待状态下用户单独发送的角色卡"""
        messages = event.get_messages() # 过滤掉空白消息
        if not messages:
            return
        # —— 酒馆聊天模式：纯文本直接转发酒馆，无需 /酒 前缀 ——
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        in_chat_mode = (f"{group_id}_{user_id}" in self.chat_mode_user_keys) or (
            bool(group_id) and str(group_id) in self.chat_mode_group_keys
        )
        if in_chat_mode:
            msg = event.message_str.strip()
            first = msg.split()[0].lstrip("/") if msg else ""
            is_plain_text = bool(msg) and not any(isinstance(c, (Image, File)) for c in messages)
            if first not in CHAT_MODE_COMMANDS and is_plain_text: # 非酒指令的纯文本才拦截
                access_ok, access_reason = self._check_access(event) # 聊天模式同样受黑/白名单与管理员模式约束
                if not access_ok:
                    event.stop_event()
                    yield event.plain_result(access_reason)
                    return
                event.stop_event() # 阻止其他插件/LLM 处理
                if self.status_running: # 与其它指令互斥，避免并发操作同一个浏览器
                    self.status_running = False
                    try:
                        await bartender_crawler.open_browser_auto(self, False)
                        ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                        if not ok_persona:
                            yield event.plain_result(err_persona)
                            return
                        await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                        send_result = await bartender_crawler.send_message(self, msg) # 整条消息作为内容发送
                        if send_result != "正常":
                            yield event.plain_result(f"""发送失败: {(send_result)}""")
                            return
                        message_text = await bartender_crawler.get_new_message_text(self) # 获取最新消息文本
                        remaining = await bartender_crawler.get_now_floor(self, 0) # 获取当前楼层数
                        if message_text:
                            if self.config['basic'].get('show_floor_count'):
                                yield event.plain_result(f"{f"""当前共{remaining}楼层"""}\n\n{message_text}")
                            else:
                                yield event.plain_result(message_text)
                        else:
                            yield event.plain_result("""合并消息为空""")
                    except Exception as e:
                        logger.error(f"聊天模式转发异常: {e}")
                        yield event.plain_result("""指令执行异常，请稍后重试""")
                    finally:
                        await bartender_crawler.close_browser_auto(self)
                        self.status_running = True
                else:
                    yield event.plain_result("""正在Shake~，请稍作等待""")
                return
            # 酒指令 / 含图片 / 空白：落至下方等待逻辑或放行
        session_key = f"{event.get_group_id()}_{event.get_sender_id()}" 
        if session_key not in self.waiting_sessions: # 如果不在等待列表，直接放行
            return
        if time.time() > self.waiting_sessions[session_key]: # 检查是否已经超时
            del self.waiting_sessions[session_key]
            yield event.plain_result("""等待超时，操作已取消""")
            return
        image_comp = None
        for comp in messages: # 遍历这条新消息寻找图片或图片文件
            if isinstance(comp, (Image, File)): # 同时兼容 Image 和 File 组件
                image_comp = comp
                break
        if image_comp:
            del self.waiting_sessions[session_key] # 找到了组件，清除等待状态
            event.stop_event() # 阻止该消息被其他插件重复处理
            if self.status_running: # 与其它指令互斥，避免并发操作同一个浏览器
                self.status_running = False
                try:
                    yield event.plain_result("""已接收角色卡,添加中~""")
                    await bartender_crawler.process_image(self, image_comp) # 进入统一处理流程
                    chats = '\n'.join(self.chats_name_id.keys())
                    yield event.plain_result(f"""当前角色列表：
{chats}""")
                finally:
                    self.status_running = True
            else:
                yield event.plain_result("""有其他操作进行中，请稍后重试""")
        else: # 发的是纯文字，静默忽略
            return 



    # 生命周期管理
    async def initialize(self):
        """异步的插件初始化方法，当插件被加载/启用时会调用。"""
        try:
            if self.config['tavern']['low_memory_mode']:
                await bartender_crawler.open_browser_auto(self, True)
                await bartender_crawler.check_1000page(self) # 检查是为1000分页
                await bartender_crawler.get_all_chats(self) # 获取角色列表
                await bartender_crawler.close_browser_auto(self)
            else:
                await bartender_crawler.initialize_browser(self) # 打开浏览器并访问页面
                await bartender_crawler.check_1000page(self) # 检查是为1000分页
                await bartender_crawler.get_all_chats(self) # 获取角色列表
                await bartender_crawler.switch_chats(self, self.config['basic']['now_chats_name']) # 角色切换保存
        except Exception as e:
            logger.error(f"插件初始化失败: {e}")
        self.status_running = True
        logger.info("插件初始化完成,浏览器已开启")

    async def terminate(self):
        """异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        await bartender_crawler.close_browser(self)
        logger.info("插件已被卸载，浏览器已关闭")
