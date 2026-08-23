# -*- coding: utf-8 -*-
import re, json
import time, aiohttp, platform
import subprocess, os, shutil, asyncio, functools
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

_I18N_DIR = Path(__file__).parent / ".astrbot-plugin" / "i18n"

def _load_i18n_file(lang: str) -> dict:
    """加载 .astrbot-plugin/i18n/{lang}.json；失败或非对象时返回空字典"""
    path = _I18N_DIR / f"{lang}.json"
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.error(f"加载国际化文件失败 ({path.name}): {e}")
    return {}

# 内部方法返回的状态哨兵字符串 -> i18n key（展示给用户时翻译）
_STATUS_TEXT_KEYS = {
    "正常": "chat.status.ok",
    "错误": "chat.status.error",
    "无角色卡": "chat.status.no_char",
    "浏览器未连接": "chat.status.browser_down",
    "无生成中": "chat.status.no_generation",
    "已停止": "chat.status.stopped",
    "无更多回复": "chat.status.no_more_swipes",
    "合并消息为空": "chat.status.empty_message",
    "禁止输入为空": "chat.status.empty_input",
    "打开人设面板失败": "chat.persona.panel_open_fail",
    "未找到人设": "chat.persona.not_found",
}
# 重命名角色卡 REST 返回码 -> i18n key
_RENAME_ERR_KEYS = {
    "not_found": "chat.rename.not_found",
    "request_failed": "chat.rename.request_failed",
}
# 引用定位兼容楼层前缀（随回复语言变化）
_FLOOR_PREFIX_RE = re.compile(r"^(当前共\d+楼层|\d+ floors? total)$")

# 聊天模式下放行的本插件指令名集合（首词命中则不拦截，交给指令分发）
CHAT_MODE_COMMANDS = frozenset({
    "酒", "酒切换", "酒删除", "酒加卡", "酒删卡", "酒重生成", "酒续写", "酒备选",
    "酒停止生成", "酒关闭", "酒新建", "酒导出", "酒统计", "酒改名", "酒查看",
    "酒人设", "酒状态", "酒帮助", "酒启动", "酒重置",
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
             "1.6.0")



# 爬虫类定义
class bartender_crawler(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.ST_URL = f"{config['browser_ip']}:{config['browser_port']}" # 获取配置的本地酒馆地址
        self.chats_name_id = {} # 初始化角色字典
        self.default_chat = config['now_chats_name'] # 获取配置文件当前角色
        self.browser = None # 初始化浏览器类
        self._browser_lock = asyncio.Lock() # 浏览器启动/关闭互斥锁，防止并发重复启动出多个浏览器
        self.status_running = False # 消息状态初始化
        self.config = config # 初始化配置文件
        self._i18n_requested = _load_i18n_file(str(config.get('language', 'zh-CN') or 'zh-CN')) # 配置语言（缺失回退中文）
        self._i18n_fallback = _load_i18n_file("zh-CN") # 源语言兜底
        self.cache_dir = Path("data/temp/astrbot_plugin_bartender_extra") # 初始化本地缓存文件夹路径
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.waiting_sessions = {} # 初始化会话状态字典，用于记录哪些用户正在等待发送图片，格式为: {"群号_用户ID": 过期时间戳}
        self.chat_mode_creators = {} # 酒馆聊天模式：创建者键"{群号}_{用户ID}" -> ("user"|"group", scope)
        self.chat_mode_user_keys = set() # 活跃的按用户聊天模式键 "{群号}_{用户ID}"
        self.chat_mode_group_keys = {} # 活跃的按群聊天模式键 "{群号}" -> 创建者键
        self.plugin_dir = Path(__file__).parent # 获取当前目录
        self.browser_dir = self.plugin_dir / "browser"
        self.persona_bindings = self._load_persona_bindings() # 用户人设绑定字典，格式为: {"群号_用户ID": {"name": 人设名, "avatar_id": 人设头像ID}}
        self._register_web_apis(context)

    @staticmethod
    def _i18n_lookup(data: dict, key: str):
        """按点号路径在 locale 字典中取词；值非字符串/数组视为缺失"""
        cur = data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        if isinstance(cur, list):
            return "\n".join(str(x) for x in cur)
        return cur if isinstance(cur, str) else None

    def t(self, key: str, **kwargs) -> str:
        """国际化取词：按配置语言读取，缺失回退中文源文案，仍缺失返回 key 本身"""
        text = self._i18n_lookup(self._i18n_requested, key)
        if text is None:
            text = self._i18n_lookup(self._i18n_fallback, key)
        if text is None:
            return key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass # 占位符不匹配时原样返回，避免崩指令
        return text

    def _t_status(self, status: str) -> str:
        """内部状态哨兵字符串 -> 用户可见翻译；非哨兵原样返回"""
        key = _STATUS_TEXT_KEYS.get(status)
        return self.t(key) if key else status

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

    def _check_access(self, event):
        """访问控制：黑名单优先、白名单限制群聊、管理员模式要求管理员；返回 (是否通过, 原因)"""
        gid = event.get_group_id()
        gid_s = str(gid) if gid is not None else ""
        blacklist = [str(x) for x in (self.config.get('blacklist_groups') or [])]
        whitelist = [str(x) for x in (self.config.get('whitelist_groups') or [])]
        if gid_s and gid_s in blacklist: # 群黑名单优先（私聊不适用群名单）
            return False, self.t("chat.access.blacklisted")
        if gid_s and whitelist and gid_s not in whitelist: # 白名单非空时仅允许列内群聊
            return False, self.t("chat.access.not_whitelisted")
        if self.config.get('admin_only') and not event.is_admin(): # 管理员模式
            return False, self.t("chat.access.admin_only")
        return True, ""

    async def page_info(self):
        """返回酒馆地址、连通性、是否携带捆绑酒馆"""
        st_url = f"{self.config['browser_ip']}:{self.config['browser_port']}"
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
            "ip": self.config['browser_ip'],
            "port": self.config['browser_port'],
            "reachable": reachable,
            "has_bundled_st": has_bundled,
        })

    async def page_start_tavern(self):
        """启动插件目录中的酒馆（供 WebUI 一键启动按钮调用）"""
        ok, msg = await self.start_tavern()
        return json_response({"ok": ok, "message": msg})

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
        if self.config.get('global_persona_binding'):
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
                headless=bool(self.config['browser_Visible']),
                slow_mo=int(self.config['browser_delay']),
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
                self.config['now_chats_name'] = name
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
            return False, self.t("chat.persona.bind_fail", name=bound.get('name'))
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
                        if (!sel) return {ok: false, msg: '未找到世界书选择器'};
                        let opt = null;
                        for (const o of sel.options) {
                            if (o.text === name || o.value === name) { opt = o; break; }
                        }
                        if (!opt) return {ok: false, msg: '未找到世界书：' + name};
                        const was = opt.selected;
                        opt.selected = !was;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return {ok: true, state: was ? '已停用' : '已启用'};
                    }""",
                    name,
                )
            finally:
                if not was_open: # 关闭抽屉（如果原来就是开的就不关）
                    await self.page.locator("#WIDrawerIcon").click()
            return result.get("ok", False), result.get("state") or result.get("msg", "错误")
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
                    name = self.config['now_chats_name'],
                    content = [Plain(str(item))]
                )
                for item in message_list]
            if truncated:
                nodes_list.append(Node(
                    uin = bot_id,
                    name = self.config['now_chats_name'],
                    content = [Plain(self.t("chat.floor.truncated"))]
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
                    self.config['now_chats_name'] = name
                    logger.info(f"当前角色为：{self.config['now_chats_name']}")
                    self.config.save_config()
                    return True
                else:
                    self.config['now_chats_name'] = None
                    logger.info(f"当前角色为：无")
                    return False
            except Exception as e:
                await self.close_chats()
                logger.error(f"角色检测错误{e}")
        elif self.config['now_chats_name'] == (None or '') and self.chats_name_id == {}:
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

    async def rename_character(self, old_name, new_name):
        """通过页面上下文调用酒馆 REST 重命名角色卡，返回 (是否成功, 提示)"""
        try:
            if not await self.check_browser():
                return False, "浏览器未连接"
            result = await self.page.evaluate(
                """async (args) => {
                    const list = await fetch('/api/characters/all', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r => r.ok ? r.json() : []);
                    const item = (Array.isArray(list) ? list : []).find(c => c.name === args.old);
                    if (!item) return {ok: false, code: 'not_found'};
                    const r = await fetch('/api/characters/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({avatar_url: item.avatar, new_name: args.new})});
                    if (!r.ok) return {ok: false, code: 'request_failed'};
                    return {ok: true};
                }""",
                {"old": old_name, "new": new_name},
            )
            if not result or not result.get("ok"):
                code = (result or {}).get("code") or "error"
                return False, self.t(_RENAME_ERR_KEYS.get(code, "chat.status.error"))
            # REST 改名后前端 DOM 角色列表已过期，重载页面以同步
            try:
                await self.page.reload(wait_until="domcontentloaded")
                await self.page.wait_for_selector(".welcomeHeaderVersionDisplay", state="visible", timeout=10000)
            except Exception as e:
                logger.warning(f"改名后重载页面失败：{e}")
            await self.get_all_chats() # 重新获取角色列表
            return True, "正常"
        except Exception as e:
            logger.error(f"重命名角色卡失败：{e}")
            return False, "错误"

    async def open_browser_auto(self, first : bool):
        """线程安全模式判断开启"""
        if self.config['thread_safe_mode']: # 判断并且打开浏览器
            await self.initialize_browser() # 打开浏览器
            # await self.page.wait_for_timeout(800) # 等待防超时
            if first == False: # 初始化时无需打开角色卡
                await self.switch_chats(self.config['now_chats_name']) # 角色切换保存

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
        """线程安全模式判断关闭"""
        if self.config['thread_safe_mode']: # 判断并且关闭浏览器
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
            emoji_cfg = str(self.config.get('reaction_emoji', '')).strip()
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
            if self.config['now_chats_name'] == dal_name:
                self.config['now_chats_name'] = "Seraphina"
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
            return -1, [f"统计失败: {e}"]
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
            return True, self.t("chat.tavern.already_running")
        except Exception:
            pass
        # 定位目录
        st_dir = self.plugin_dir / "SillyTavern"
        if not (st_dir / "server.js").exists():
            return False, self.t("chat.tavern.not_found")
        # Node 检查
        node_path = shutil.which("node")
        if not node_path:
            if os.name == "nt":
                return False, self.t("chat.tavern.no_node_win")
            return False, self.t("chat.tavern.no_node_unix")
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
            subprocess.Popen([node_path, "server.js"], **popen_kwargs)
        except Exception as e:
            return False, self.t("chat.tavern.start_failed", error=e)
        # 等待就绪（最长约 60 秒）
        for _ in range(30):
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2)
                writer.close()
                await writer.wait_closed()
                return True, self.t("chat.tavern.started")
            except Exception:
                await asyncio.sleep(2)
        return False, self.t("chat.tavern.timeout", path=log_path)



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
    @filter.command("酒关闭")
    async def command_close_browser(self, event: AstrMessageEvent):
        """关闭插件浏览器并清理后台所有 chrome/chromium 进程"""
        await bartender_crawler.close_browser(self) # 先优雅关闭插件自己的浏览器
        await bartender_crawler.kill_chrome_process(self) # 再兜底清理残留进程
        yield event.plain_result(self.t("chat.close.done"))

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
                        yield event.plain_result(self.t("chat.send.failed", status=self._t_status(send_result)))
                        return
                    message_text = await bartender_crawler.get_new_message_text(self) # 获取最新的消息文本
                    remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                    if message_text:
                        if self.config.get('show_floor_count'):
                            yield event.plain_result(f"{self.t('chat.floor.count', count=remaining)}\n\n{message_text}")
                        else:
                            yield event.plain_result(message_text)
                    else:
                        yield event.plain_result(self.t("chat.status.empty_message"))
                else:
                    yield event.plain_result(self.t("chat.status.empty_input"))
            except Exception as e:
                logger.error(f"酒指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

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
                            yield event.plain_result("请输入：/酒人设 绑定 [人设名]")
                            return
                        persona_name = " ".join(tokens[2:])
                        ok, avatar_id = await bartender_crawler.switch_persona(self, persona_name)
                        if ok:
                            self.persona_bindings[session_key] = {"name": persona_name, "avatar_id": avatar_id}
                            self._save_persona_bindings()
                            yield event.plain_result(self.t("chat.persona.bound", name=persona_name))
                        else:
                            yield event.plain_result(self.t("chat.persona.not_found_with_hint", name=persona_name))
                        return
                    if tokens[1] == "查看" and len(tokens) >= 3: # /酒人设 查看 [名字] → 查看人设详情
                        persona_name = " ".join(tokens[2:])
                        if not await bartender_crawler.open_persona_panel(self):
                            yield event.plain_result("打开人设面板失败")
                            return
                        try:
                            if not await bartender_crawler._select_persona_block(self, persona_name):
                                yield event.plain_result(f"未找到人设：{persona_name}")
                                return
                            desc = await self.page.locator("#persona_description").input_value()
                            display_name = await self.page.locator("#your_name").inner_text()
                            avatar_id = ""
                            blocks = self.page.locator("#user_avatar_block .avatar-container.selected")
                            if await blocks.count():
                                avatar_id = await blocks.first.get_attribute("data-avatar-id") or ""
                            pos_sel = self.page.locator("#persona_description_position")
                            pos_val = await pos_sel.evaluate("el => el.options[el.selectedIndex]?.text || ''") if await pos_sel.count() else ""
                            lines = [f"人设：{display_name}", f"头像ID：{avatar_id or '无'}"]
                            if pos_val:
                                lines.append(f"位置：{pos_val}")
                            lines.append(f"描述：\n{desc or '[空]'}")
                            yield event.plain_result("\n".join(lines))
                        finally:
                            await bartender_crawler.close_persona_panel(self)
                        return
                    if tokens[1] == "修改": # /酒人设 修改 [名字] [内容]：仅名字删除，不存在则新建
                        if len(tokens) < 3:
                            yield event.plain_result(self.t("chat.persona.modify_usage"))
                            return
                        persona_name = tokens[2]
                        description = " ".join(tokens[3:]).strip()
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
                        action_keys = {"update": "chat.persona.action_update",
                                       "delete": "chat.persona.action_delete",
                                       "create": "chat.persona.action_create"}
                        if ok:
                            if action == "delete":
                                yield event.plain_result(self.t("chat.persona.deleted", name=persona_name))
                            elif action == "create" and not description:
                                yield event.plain_result(self.t("chat.persona.created_empty", name=persona_name))
                            else:
                                yield event.plain_result(self.t("chat.persona.done",
                                                                 action=self.t(action_keys[action]),
                                                                 name=persona_name))
                        else:
                            yield event.plain_result(self.t("chat.persona.fail",
                                                             action=self.t(action_keys[action]),
                                                             msg=self._t_status(msg)))
                        return
                    if tokens[1] == "解绑": # /酒人设 解绑
                        if session_key in self.persona_bindings:
                            del self.persona_bindings[session_key]
                            self._save_persona_bindings()
                            yield event.plain_result(self.t("chat.persona.unbound"))
                        else:
                            yield event.plain_result(self.t("chat.persona.not_bound"))
                        return
                    yield event.plain_result("未知子命令，可用：绑定、查看、修改、解绑；/酒人设 查看全部人设")
                    return
                # 查看模式：/酒人设
                bound = self.persona_bindings.get(session_key)
                bound_text = f"{bound['name']}" if bound else self.t("chat.state.none")
                personas, current = await bartender_crawler.get_personas(self)
                if personas is None:
                    yield event.plain_result(self.t("chat.persona.list_fail"))
                    return
                lines = [self.t("chat.persona.current_bound", name=bound_text),
                         self.t("chat.persona.current_tavern", name=current or self.t("chat.state.none"))]
                if personas:
                    lines.append(self.t("chat.persona.list_header"))
                    lines.extend(self.t("chat.persona.list_item", name=name, avatar_id=avatar_id)
                                 for name, avatar_id in personas.items())
                else:
                    lines.append(self.t("chat.persona.none_in_tavern"))
                yield event.plain_result("\n".join(lines))
            except Exception as e:
                logger.error(f"酒人设指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))

    @filter.command("酒重生成")
    @_access_required
    async def command_rest_message(self, event: AstrMessageEvent):
        """重新生成当前楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = self.config['now_chats_name']
                if user_message != "" and user_message != None:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息（QQ不支持流式输出）
                    rest_result = await bartender_crawler.rest_message(self)
                    if rest_result != "正常":
                        yield event.plain_result(self.t("chat.regenerate.failed", status=self._t_status(rest_result)))
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result(self.t("chat.status.empty_message"))
                else:
                    yield event.plain_result(self.t("chat.status.empty_input"))
            except Exception as e:
                logger.error(f"酒重生成指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

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
                        yield event.plain_result(self.t("chat.browser_fail"))
                        return
                    matches = await bartender_crawler.get_floor_by_quote(self, quoted_text)
                    if not matches:
                        yield event.plain_result(self.t("chat.quote.not_found"))
                    elif len(matches) == 1:
                        yield event.plain_result(self.t("chat.quote.single", n=matches[0]))
                    else:
                        nums = self.t("chat.quote.list_sep").join(str(m) for m in matches)
                        yield event.plain_result(self.t("chat.quote.multi", nums=nums))
                    return
                bot_id =event.message_obj.self_id # 获取bot_id
                forward_message = await bartender_crawler.get_new_message(self, bot_id) # 获取信息
                remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                if forward_message != None:
                    yield event.plain_result(self.t("chat.floor.count", count=remaining))
                    yield MessageEventResult(chain=[forward_message])
                else:
                    yield event.plain_result(self.t("chat.status.empty_message"))
            except Exception as e:
                logger.error(f"酒查看指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))

    @filter.command("酒状态")
    @_access_required
    async def command_get_status(self, event: AstrMessageEvent):
        """获取当前所有状态"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                await self.get_chat_Status()
                if self.config['now_chats_name'] == None:
                    chat = self.t("chat.status.no_char")
                else:
                    chat = self.config['now_chats_name']
                logger.info(f"角色卡：{chat}")
                if await bartender_crawler.check_browser(self):
                    connect_status = self.t("chat.status.ok")
                else:
                    connect_status = self.t("chat.status.fail")
                chats = '\n'.join(self.chats_name_id.keys())
                session_key = self.get_persona_session_key(event)
                bound = self.persona_bindings.get(session_key)
                bound_text = f"{bound['name']}" if bound else self.t("chat.state.none")
                yield event.plain_result(self.t("chat.status_cmd.text", chat=chat, status=connect_status,
                                                bound=bound_text, chats=chats))
            except Exception as e:
                logger.error(f"酒状态指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))

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
                        yield event.plain_result(self.t("chat.switch.done", name=chat_name))
                    else:
                        yield event.plain_result(self.t("chat.switch.not_found", name=chat_name))
                else:
                    yield event.plain_result(self.t("chat.switch.empty"))
            except Exception as e:
                logger.error(f"酒切换指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))

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
                        yield event.plain_result(self.t("chat.delete.not_number"))
                        return
                if del_status and del_message != None:
                    yield event.plain_result(self.t("chat.delete.done",
                                                     deleted=abs(del_message), remaining=remaining))
                else:
                    yield event.plain_result(self.t("chat.delete.bad"))
            except Exception as e:
                logger.error(f"酒删除指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))

    @filter.command("酒加卡")
    @_access_required
    async def upload_chat_command(self, event: AstrMessageEvent):
        """添加角色卡至酒馆"""
        if self.status_running: # 判断运行状态
            self.status_running = False
            try:
                image_comp = bartender_crawler.find_card_comp(self, event)
                if image_comp: # 同条消息附带图片或引用了含图消息，直接进入处理流程
                    await bartender_crawler.process_image(self, image_comp) # process_image无返回值，无需yield
                    chats = '\n'.join(self.chats_name_id.keys())
                    yield event.plain_result(self.t("chat.list.roles", chats=chats))
                else: # 情况 B：指令和图片分条发送。为该用户开启等待状态，设定有效期
                    session_key = f"{event.get_group_id()}_{event.get_sender_id()}"
                    self.waiting_sessions[session_key] = time.time() + int(self.config['upload_interval'])
                    yield event.plain_result(self.t("chat.upload.wait", seconds=self.config['upload_interval']))
            except Exception as e:
                logger.error(f"酒加卡指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))


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
                    yield event.plain_result(self.t("chat.delete_char.no_name"))
                else:
                    user_message = (user_message.split()[1:])[0]
                    if user_message in self.chats_name_id:
                        await bartender_crawler.del_chat_png(self, user_message) # 删除对应名字角色卡
                        chats = '\n'.join(self.chats_name_id.keys())
                        yield event.plain_result(self.t("chat.list.roles_current", chats=chats))
                    elif user_message == "Seraphina":
                        yield event.plain_result(self.t("chat.delete_char.default_forbidden"))
                    else:
                        yield event.plain_result(self.t("chat.delete_char.not_found"))
            except Exception as e:
                logger.error(f"酒删卡指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.wait"))

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
                if self.config['thread_safe_mode']:
                    await bartender_crawler.open_browser_auto(self, False)
                    await bartender_crawler.check_1000page(self)
                    await bartender_crawler.get_all_chats(self)
                    await bartender_crawler.close_browser_auto(self)
                else:
                    await bartender_crawler.initialize_browser(self)
                    await bartender_crawler.check_1000page(self)
                    await bartender_crawler.get_all_chats(self)
                    await bartender_crawler.switch_chats(self, self.config['now_chats_name'])
                yield event.plain_result(f"{result}{self.t('chat.tavern.connected_suffix')}")
            except Exception as e:
                logger.error(f"酒启动指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒进程")
    async def chrome_status_command(self, event: AstrMessageEvent):
        """查看后台 chrome/chromium 进程数量与插件浏览器状态"""
        total, detail = bartender_crawler.count_chrome_processes(self)
        if self.browser and self.browser.is_connected():
            browser_state = self.t("chat.chrome.browser_connected")
        elif self.browser:
            browser_state = self.t("chat.chrome.browser_disconnected")
        else:
            browser_state = self.t("chat.chrome.not_started")
        driver_state = self.t("chat.chrome.driver_running") if getattr(self, 'p', None) else self.t("chat.chrome.not_started")
        lines = [self.t("chat.chrome.total", total=total)]
        if detail:
            lines.append(self.t("chat.chrome.detail", detail="，".join(detail)))
        lines.append(self.t("chat.chrome.browser", state=browser_state))
        lines.append(self.t("chat.chrome.driver", state=driver_state))
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
        self.config['now_chats_name'] = "Seraphina" # 当前角色切换至默认
        await bartender_crawler.get_all_chats(self) # 重新获取所有角色
        await bartender_crawler.switch_chats(self, "Seraphina") # 切换至默认卡
        await bartender_crawler.close_browser_auto(self)
        yield event.plain_result(self.t("chat.reset.done"))

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
                    yield event.plain_result(self.t("chat.new_chat.failed", status=self._t_status(result)))
                else:
                    remaining = await bartender_crawler.get_now_floor(self, 0) # 获取当前楼层数
                    yield event.plain_result(self.t("chat.new_chat.done", count=remaining))
            except Exception as e:
                logger.error(f"酒新建指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

    @filter.command("酒续写")
    @_access_required
    async def command_continue_message(self, event: AstrMessageEvent):
        """续写最新楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = self.config['now_chats_name']
                if user_message != "" and user_message != None:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                    cont_result = await bartender_crawler.continue_message(self)
                    if cont_result != "正常":
                        yield event.plain_result(self.t("chat.continue.failed", status=self._t_status(cont_result)))
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result(self.t("chat.status.empty_message"))
                else:
                    yield event.plain_result(self.t("chat.status.no_char"))
            except Exception as e:
                logger.error(f"酒续写指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

    @filter.command("酒停止生成")
    @_access_required
    async def command_stop_generation(self, event: AstrMessageEvent):
        """中断当前酒馆生成"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                result = await bartender_crawler.stop_generation(self)
                yield event.plain_result(self._t_status(result))
            except Exception as e:
                logger.error(f"酒停止指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

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
                user_message = self.config['now_chats_name']
                if user_message != "" and user_message != None:
                    ok_persona, err_persona = await bartender_crawler.apply_user_persona(self, event) # 应用该用户绑定的人设
                    if not ok_persona:
                        yield event.plain_result(err_persona)
                        return
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息
                    swipe_result = await bartender_crawler.swipe_message(self, direction)
                    if swipe_result != "正常":
                        yield event.plain_result(self._t_status(swipe_result))
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result(self.t("chat.status.empty_message"))
                else:
                    yield event.plain_result(self.t("chat.status.no_char"))
            except Exception as e:
                logger.error(f"酒备选指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

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
                    yield event.plain_result(self.t("chat.export.done"))
                    yield event.chain_result([File.fromFileSystem(str(path))])
                else:
                    yield event.plain_result(self.t("chat.export.failed"))
            except Exception as e:
                logger.error(f"酒导出指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

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
                    yield event.plain_result(self.t("chat.stats.failed"))
                    return
                name = data.get("name") or self.t("chat.stats.unknown_name")
                s = data.get("stats")
                if not s:
                    yield event.plain_result(self.t("chat.stats.no_stats", name=name))
                    return
                gen_sec = round((s.get("total_gen_time") or 0) / 1000, 1) # 毫秒转秒
                lines = [
                    self.t("chat.stats.character", name=name),
                    self.t("chat.stats.messages", user=s.get('user_msg_count', 0), role=s.get('non_user_msg_count', 0)),
                    self.t("chat.stats.words", user=s.get('user_word_count', 0), role=s.get('non_user_word_count', 0)),
                    self.t("chat.stats.swipes", count=s.get('total_swipe_count', 0)),
                    self.t("chat.stats.gen_time", seconds=gen_sec),
                    self.t("chat.stats.chat_size", size=s.get('chat_size', 0)),
                ]
                last = s.get("date_last_chat")
                first = s.get("date_first_chat")
                if last and last < 1e14: # 排除远期哨兵值
                    lines.append(self.t("chat.stats.last_chat", time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last / 1000))))
                if first and first < 1e14:
                    lines.append(self.t("chat.stats.first_chat", time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first / 1000))))
                yield event.plain_result("\n".join(lines))
            except Exception as e:
                logger.error(f"酒统计指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

    @filter.command("酒改名")
    @_access_required
    async def command_rename_character(self, event: AstrMessageEvent):
        """重命名角色卡：/酒改名 旧名 新名"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip()
                tokens = user_message.split()
                if len(tokens) < 3:
                    yield event.plain_result(self.t("chat.rename.usage"))
                    return
                old_name = tokens[1]
                new_name = " ".join(tokens[2:])
                if old_name == "Seraphina":
                    yield event.plain_result(self.t("chat.rename.default_forbidden"))
                    return
                ok, msg = await bartender_crawler.rename_character(self, old_name, new_name)
                if not ok:
                    yield event.plain_result(self.t("chat.rename.failed", msg=self._t_status(msg)))
                    return
                if self.config['now_chats_name'] == old_name: # 若改名的是当前角色，同步配置
                    self.config['now_chats_name'] = new_name
                    self.config.save_config()
                chats = '\n'.join(self.chats_name_id.keys())
                yield event.plain_result(self.t("chat.rename.done", old=old_name, new=new_name, chats=chats))
            except Exception as e:
                logger.error(f"酒改名指令异常: {e}")
                yield event.plain_result(self.t("chat.error.exec"))
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result(self.t("chat.busy.shake"))

    @filter.command("酒开始")
    @_access_required
    async def command_start_chat_mode(self, event: AstrMessageEvent):
        """开启酒馆聊天模式：直接发送消息即转酒馆，无需 /酒 前缀；带"群聊"按当前群生效"""
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        creator = f"{group_id}_{user_id}"
        if creator in self.chat_mode_creators: # 开始者只能一次，不能同时用户+群聊
            yield event.plain_result(self.t("chat.mode.already_started"))
            return
        user_message = event.message_str.strip()
        is_group_mode = "群聊" in user_message.split()
        if is_group_mode and not group_id: # 私聊不支持群聊模式
            yield event.plain_result(self.t("chat.mode.private_no_group"))
            is_group_mode = False
        if is_group_mode:
            gid = str(group_id)
            if gid in self.chat_mode_group_keys: # 本群已由他人开启群聊模式
                yield event.plain_result(self.t("chat.mode.group_taken"))
                return
            self.chat_mode_group_keys[gid] = creator
            self.chat_mode_creators[creator] = ("group", gid)
            scope = self.t("chat.mode.scope_group")
        else:
            user_key = f"{group_id}_{user_id}"
            self.chat_mode_user_keys.add(user_key)
            self.chat_mode_creators[creator] = ("user", user_key)
            scope = self.t("chat.mode.scope_user")
        chat = self.config.get('now_chats_name') or self.t("chat.status.no_char")
        yield event.plain_result(
            self.t("chat.mode.started", scope=scope, chat=chat)
        )

    @filter.command("酒结束")
    @_access_required
    async def command_end_chat_mode(self, event: AstrMessageEvent):
        """结束调用者自己创建的酒馆聊天模式"""
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        creator = f"{group_id}_{user_id}"
        if creator not in self.chat_mode_creators:
            yield event.plain_result(self.t("chat.mode.not_started"))
            return
        mode, scope = self.chat_mode_creators.pop(creator) # 结束这个用户创建的开始
        if mode == "user":
            self.chat_mode_user_keys.discard(scope)
        else:
            self.chat_mode_group_keys.pop(scope, None)
        yield event.plain_result(self.t("chat.mode.ended"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒权限")
    async def command_permissions(self, event: AstrMessageEvent):
        """管理酒命令访问权限：管理[开/关] / 白名单[群号|移除 群号] / 黑名单[群号|移除 群号]"""
        user_message = event.message_str.strip()
        tokens = user_message.split()
        if len(tokens) < 2: # 无子命令，查看当前设置
            admin_only = bool(self.config.get('admin_only'))
            whitelist = [str(x) for x in (self.config.get('whitelist_groups') or [])]
            blacklist = [str(x) for x in (self.config.get('blacklist_groups') or [])]
            yield event.plain_result(
                self.t("chat.perms.header") + "\n"
                + self.t("chat.perms.admin_mode", state=self.t("chat.state.on" if admin_only else "chat.state.off")) + "\n"
                + self.t("chat.perms.whitelist", list=", ".join(whitelist) or self.t("chat.state.none")) + "\n"
                + self.t("chat.perms.blacklist", list=", ".join(blacklist) or self.t("chat.state.none")) + "\n"
                + self.t("chat.perms.usage")
            )
            return
        sub = tokens[1]
        if sub == "管理":
            if len(tokens) < 3:
                yield event.plain_result(self.t("chat.perms.admin_current",
                                                 state=self.t("chat.state.on" if self.config.get('admin_only') else "chat.state.off")))
                return
            sw = tokens[2]
            if sw == "开":
                self.config['admin_only'] = True
            elif sw == "关":
                self.config['admin_only'] = False
            else:
                yield event.plain_result(self.t("chat.perms.admin_bad_arg"))
                return
            self.config.save_config()
            yield event.plain_result(self.t("chat.perms.admin_set",
                                             state=self.t("chat.state.enabled" if self.config['admin_only'] else "chat.state.disabled"),
                                             scope=self.t("chat.perms.scope_admin" if self.config['admin_only'] else "chat.perms.scope_all")))
            return
        if sub in ("白名单", "黑名单"):
            key = 'whitelist_groups' if sub == "白名单" else 'blacklist_groups'
            sub_label = self.t("chat.perms.label_whitelist" if sub == "白名单" else "chat.perms.label_blacklist")
            groups = [str(x) for x in (self.config.get(key) or [])]
            if len(tokens) >= 4 and tokens[2] in ("移除", "删除", "-"):
                gid = tokens[3]
                groups = [g for g in groups if g != gid]
                self.config[key] = groups
                self.config.save_config()
                yield event.plain_result(self.t("chat.perms.group_removed", sub=sub_label, gid=gid))
                return
            if len(tokens) >= 3 and tokens[2] not in ("移除", "删除", "-"):
                gid = tokens[2]
                if gid not in groups:
                    groups.append(gid)
                    self.config[key] = groups
                    self.config.save_config()
                yield event.plain_result(self.t("chat.perms.group_added", sub=sub_label, gid=gid,
                                                 list=", ".join(groups) or self.t("chat.state.none")))
                return
            yield event.plain_result(self.t("chat.perms.group_current", sub=sub_label,
                                            list=", ".join(groups) or self.t("chat.state.none")))
            return
        yield event.plain_result(self.t("chat.perms.unknown_sub"))

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
                        yield event.plain_result("请输入：/酒世界书 查看 [名字]")
                        return
                    name = " ".join(tokens[2:])
                    data = await bartender_crawler.get_world_info_detail(self, name)
                    if not data:
                        yield event.plain_result(f"未找到世界书：{name}")
                        return
                    entries = data.get("entries") or {}
                    if isinstance(entries, dict):
                        entry_list = list(entries.values())
                    elif isinstance(entries, list):
                        entry_list = entries
                    else:
                        entry_list = []
                    lines = [f"世界书：{name}", f"共 {len(entry_list)} 条目"]
                    for i, entry in enumerate(entry_list, 1):
                        enabled = not entry.get("disable", False)
                        keys = entry.get("key", "")
                        content = (entry.get("content", "") or "").strip()
                        lines.append(f"{i}. [{'启用' if enabled else '停用'}] 触发词：{keys}")
                        if content:
                            lines.append(f"   {content[:200]}")
                    yield event.plain_result("\n".join(lines))
                elif len(tokens) > 1 and tokens[1] == "切换":
                    if len(tokens) < 3:
                        yield event.plain_result("请输入：/酒世界书 切换 [名字]")
                        return
                    name = " ".join(tokens[2:])
                    await bartender_crawler.react_message(self, event)
                    ok, msg = await bartender_crawler.toggle_world_info(self, name)
                    if ok:
                        yield event.plain_result(f"世界书「{name}」{msg}")
                    else:
                        yield event.plain_result(f"切换失败：{msg}")
                else:
                    # 列出所有世界书 + 已启用
                    data = await bartender_crawler.list_world_infos(self)
                    if not data:
                        yield event.plain_result("获取世界书列表失败")
                        return
                    wi_list = data.get("list") or []
                    active = data.get("active") or []
                    chat_name = self.config.get('now_chats_name') or "无角色卡"
                    lines = [f"当前角色：{chat_name}"]
                    lines.append(f"已启用世界书：{', '.join(active) if active else '无'}")
                    if wi_list:
                        lines.append("---")
                        lines.append("所有世界书：")
                        for item in wi_list:
                            lines.append(f"- {item.get('name', item.get('file_id', '?'))}")
                    else:
                        lines.append("酒馆中暂无世界书")
                    yield event.plain_result("\n".join(lines))
            except Exception as e:
                logger.error(f"酒世界书指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("正在Shake~，请稍作等待")

    @filter.command("酒帮助")
    @_access_required
    async def help_command(self, event: AstrMessageEvent):
        """指令帮助指南"""
        yield event.plain_result(self.t("chat.help.header") + "\n" + self.t("chat.help.lines"))

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
                            yield event.plain_result(self.t("chat.send.failed", status=self._t_status(send_result)))
                            return
                        message_text = await bartender_crawler.get_new_message_text(self) # 获取最新消息文本
                        remaining = await bartender_crawler.get_now_floor(self, 0) # 获取当前楼层数
                        if message_text:
                            if self.config.get('show_floor_count'):
                                yield event.plain_result(f"{self.t('chat.floor.count', count=remaining)}\n\n{message_text}")
                            else:
                                yield event.plain_result(message_text)
                        else:
                            yield event.plain_result(self.t("chat.status.empty_message"))
                    except Exception as e:
                        logger.error(f"聊天模式转发异常: {e}")
                        yield event.plain_result(self.t("chat.error.exec"))
                    finally:
                        await bartender_crawler.close_browser_auto(self)
                        self.status_running = True
                else:
                    yield event.plain_result(self.t("chat.busy.shake"))
                return
            # 酒指令 / 含图片 / 空白：落至下方等待逻辑或放行
        session_key = f"{event.get_group_id()}_{event.get_sender_id()}" 
        if session_key not in self.waiting_sessions: # 如果不在等待列表，直接放行
            return
        if time.time() > self.waiting_sessions[session_key]: # 检查是否已经超时
            del self.waiting_sessions[session_key]
            yield event.plain_result(self.t("chat.upload.timeout"))
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
                    yield event.plain_result(self.t("chat.upload.received"))
                    await bartender_crawler.process_image(self, image_comp) # 进入统一处理流程
                    chats = '\n'.join(self.chats_name_id.keys())
                    yield event.plain_result(self.t("chat.list.roles_current", chats=chats))
                finally:
                    self.status_running = True
            else:
                yield event.plain_result(self.t("chat.busy.other_op"))
        else: # 发的是纯文字，静默忽略
            return 



    # 生命周期管理
    async def initialize(self):
        """异步的插件初始化方法，当插件被加载/启用时会调用。"""
        try:
            if self.config['thread_safe_mode']:
                await bartender_crawler.open_browser_auto(self, True)
                await bartender_crawler.check_1000page(self) # 检查是为1000分页
                await bartender_crawler.get_all_chats(self) # 获取角色列表
                await bartender_crawler.close_browser_auto(self)
            else:
                await bartender_crawler.initialize_browser(self) # 打开浏览器并访问页面
                await bartender_crawler.check_1000page(self) # 检查是为1000分页
                await bartender_crawler.get_all_chats(self) # 获取角色列表
                await bartender_crawler.switch_chats(self, self.config['now_chats_name']) # 角色切换保存
        except Exception as e:
            logger.error(f"插件初始化失败: {e}")
        self.status_running = True
        logger.info("插件初始化完成,浏览器已开启")

    async def terminate(self):
        """异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        await bartender_crawler.close_browser(self)
        logger.info("插件已被卸载，浏览器已关闭")
