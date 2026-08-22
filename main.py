# -*- coding: utf-8 -*-
import re
import time, aiohttp, platform
import subprocess, os, shutil, asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Node, Nodes, Plain, Image, File, Reply

# 设置环境变量以启用 Playwright 的调试模式，0为正常模式，1为调试模式
os.environ["PWDEBUG"] = "0"

# 插件注册，参数分别为：插件名（唯一标识符）、作者、简介、版本号    
@register("astrbot_plugin_bartender_extra",
           "dragonuniverse8248编写 GML5.2 & deepseek指导",
            "基于playwright无头浏览器库，对sillytavern项目进行操作和交互，达成通过机器人远程游玩Sillytavern，以及高于联机脚本的游玩体验貂蝉在一起",
             "1.0.6")



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
        self.cache_dir = Path("data/temp/astrbot_plugin_bartender_extra") # 初始化本地缓存文件夹路径
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.waiting_sessions = {} # 初始化会话状态字典，用于记录哪些用户正在等待发送图片，格式为: {"群号_用户ID": 过期时间戳}
        self.plugin_dir = Path(__file__).parent # 获取当前目录
        self.browser_dir = self.plugin_dir / "browser"

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
                    content = [Plain("（内容过长，已截断）")]
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
        if sep and re.match(r"^当前共\d+楼层$", head.strip()) and rest.strip():
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
            return True, "酒馆已在运行"
        except Exception:
            pass
        # 定位目录
        st_dir = self.plugin_dir / "SillyTavern"
        if not (st_dir / "server.js").exists():
            return False, "未在插件目录找到 SillyTavern，请先运行 download_sillytavern 脚本下载"
        # Node 检查
        node_path = shutil.which("node")
        if not node_path:
            if os.name == "nt":
                return False, "未检测到 Node.js，SillyTavern 需要 Node.js 18 或更高版本。请安装: winget install OpenJS.NodeJS.LTS"
            return False, "未检测到 Node.js，SillyTavern 需要 Node.js 18 或更高版本。请通过 nvm 或官网安装"
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
            return False, f"启动失败: {e}"
        # 等待就绪（最长约 60 秒）
        for _ in range(30):
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2)
                writer.close()
                await writer.wait_closed()
                return True, "酒馆已启动"
            except Exception:
                await asyncio.sleep(2)
        return False, f"酒馆启动超时，请查看日志: {log_path}"



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
    async def command_close_browser(self, event: AstrMessageEvent):
        """关闭插件浏览器并清理后台所有 chrome/chromium 进程"""
        await bartender_crawler.close_browser(self) # 先优雅关闭插件自己的浏览器
        await bartender_crawler.kill_chrome_process(self) # 再兜底清理残留进程
        yield event.plain_result("已关闭浏览器并清理所有后台 Chrome/Chromium 进程")

    @filter.command("酒")
    async def command_send_message(self, event: AstrMessageEvent):
        """酒馆发送信息"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip()
                if user_message and len(user_message.split()) > 1:
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息（QQ不支持流式输出）
                    user_message = ' '.join(user_message.split()[1:])
                    send_result = await bartender_crawler.send_message(self, user_message) # 发送消息至酒馆
                    if send_result != "正常":
                        yield event.plain_result(f"发送失败: {send_result}")
                        return
                    message_text = await bartender_crawler.get_new_message_text(self) # 获取最新的消息文本
                    remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                    if message_text:
                        if self.config.get('show_floor_count'):
                            yield event.plain_result(f"当前共{remaining}楼层\n\n{message_text}")
                        else:
                            yield event.plain_result(message_text)
                    else:
                        yield event.plain_result("合并消息为空")
                else:
                    yield event.plain_result("禁止输入为空")
            except Exception as e:
                logger.error(f"酒指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("正在Shake~，请稍作等待")

    @filter.command("酒重新")
    async def command_rest_message(self, event: AstrMessageEvent):
        """重新生成当前楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = self.config['now_chats_name']
                if user_message != "" and user_message != None:
                    await bartender_crawler.react_message(self, event) # 贴表情回应代替占位消息（QQ不支持流式输出）
                    rest_result = await bartender_crawler.rest_message(self)
                    if rest_result != "正常":
                        yield event.plain_result(f"重调失败: {rest_result}")
                        return
                    message_text = await bartender_crawler.get_new_message_text(self)
                    if message_text:
                        yield event.plain_result(message_text)
                    else:
                        yield event.plain_result("合并消息为空")
                else:
                    yield event.plain_result("禁止输入为空")
            except Exception as e:
                logger.error(f"酒重新指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("正在Shake~，请稍作等待")

    @filter.command("酒查看")
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
                        yield event.plain_result("浏览器连接失败")
                        return
                    matches = await bartender_crawler.get_floor_by_quote(self, quoted_text)
                    if not matches:
                        yield event.plain_result("未在酒馆中找到与引用消息匹配的楼层")
                    elif len(matches) == 1:
                        yield event.plain_result(f"引用消息为第 {matches[0]} 层")
                    else:
                        yield event.plain_result("引用消息匹配到多层：第 " + "、".join(str(m) for m in matches) + " 层")
                    return
                bot_id =event.message_obj.self_id # 获取bot_id
                forward_message = await bartender_crawler.get_new_message(self, bot_id) # 获取信息
                remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                if forward_message != None:
                    yield event.plain_result(f"当前共{remaining}楼层")
                    yield MessageEventResult(chain=[forward_message])
                else:
                    yield event.plain_result("合并消息为空")
            except Exception as e:
                logger.error(f"酒查看指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒状态")
    async def command_get_status(self, event: AstrMessageEvent):
        """获取当前所有状态"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                await self.get_chat_Status()
                if self.config['now_chats_name'] == None:
                    chat = "无角色卡"
                else:
                    chat = self.config['now_chats_name']
                logger.info(f"角色卡：{chat}")
                if await bartender_crawler.check_browser(self):
                    connect_status = "正常"
                else:
                    connect_status = "失败"
                chats = '\n'.join(self.chats_name_id.keys())
                yield event.plain_result(f"当前角色卡为：{chat}\n"+f"链接状态：{connect_status}\n"+f"角色列表：\n{chats}")
            except Exception as e:
                logger.error(f"酒状态指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒切换")
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
                        yield event.plain_result(f"角色卡切换至：{chat_name}")
                    else:
                        yield event.plain_result(f"未找到角色卡：{chat_name}")
                else:
                    yield event.plain_result("消息不能为空")
            except Exception as e:
                logger.error(f"酒切换指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒删除")
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
                        yield event.plain_result("请输入数字")
                        return
                if del_status and del_message != None:
                    yield event.plain_result(f"已删除{abs(del_message)}楼层\n"+f"剩余{remaining}楼层")
                else:
                    yield event.plain_result("输入楼层数异常或最低")
            except Exception as e:
                logger.error(f"酒删除指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒加卡")
    async def upload_chat_command(self, event: AstrMessageEvent):
        """添加角色卡至酒馆"""
        if self.status_running: # 判断运行状态
            self.status_running = False
            try:
                image_comp = bartender_crawler.find_card_comp(self, event)
                if image_comp: # 同条消息附带图片或引用了含图消息，直接进入处理流程
                    await bartender_crawler.process_image(self, image_comp) # process_image无返回值，无需yield
                    chats = '\n'.join(self.chats_name_id.keys())
                    yield event.plain_result(f"角色列表：\n{chats}")
                else: # 情况 B：指令和图片分条发送。为该用户开启等待状态，设定有效期
                    session_key = f"{event.get_group_id()}_{event.get_sender_id()}"
                    self.waiting_sessions[session_key] = time.time() + int(self.config['upload_interval'])
                    yield event.plain_result(f"请在{self.config['upload_interval']}秒内发送角色卡")
            except Exception as e:
                logger.error(f"酒加卡指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")


    @filter.command("酒删卡")
    async def del_chat_command(self, event: AstrMessageEvent):
        """删除聊天楼层"""
        if self.status_running:
            self.status_running = False
            try:
                await bartender_crawler.open_browser_auto(self, False)
                user_message = event.message_str.strip() # 获取输入消息
                if user_message == "酒删卡" or len(user_message.split()) <= 1: # 判断消息是否为空
                    yield event.plain_result("请输入角色卡名称")
                else:
                    user_message = (user_message.split()[1:])[0]
                    if user_message in self.chats_name_id:
                        await bartender_crawler.del_chat_png(self, user_message) # 删除对应名字角色卡
                        chats = '\n'.join(self.chats_name_id.keys())
                        yield event.plain_result(f"当前角色列表：\n{chats}")
                    elif user_message == "Seraphina":
                        yield event.plain_result("禁止删除默认角色")
                    else:
                        yield event.plain_result("未查找到角色卡名称")
            except Exception as e:
                logger.error(f"酒删卡指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

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
                yield event.plain_result(f"{result}，已自动连接")
            except Exception as e:
                logger.error(f"酒启动指令异常: {e}")
                yield event.plain_result("指令执行异常，请稍后重试")
            finally:
                await bartender_crawler.close_browser_auto(self)
                self.status_running = True
        else:
            yield event.plain_result("正在Shake~，请稍作等待")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒进程")
    async def chrome_status_command(self, event: AstrMessageEvent):
        """查看后台 chrome/chromium 进程数量与插件浏览器状态"""
        total, detail = bartender_crawler.count_chrome_processes(self)
        if self.browser and self.browser.is_connected():
            browser_state = "已连接"
        elif self.browser:
            browser_state = "连接已断开"
        else:
            browser_state = "未启动"
        driver_state = "运行中" if getattr(self, 'p', None) else "未启动"
        lines = [f"系统 chrome/chromium 进程总数：{total}"]
        if detail:
            lines.append("明细：" + "，".join(detail))
        lines.append(f"插件浏览器：{browser_state}")
        lines.append(f"playwright 驱动：{driver_state}")
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
        self.config['now_chats_name'] = "Seraphina" # 当前角色切换至默认
        await bartender_crawler.get_all_chats(self) # 重新获取所有角色
        await bartender_crawler.switch_chats(self, "Seraphina") # 切换至默认卡
        await bartender_crawler.close_browser_auto(self)
        yield event.plain_result("已重置获取所有变量")

    @filter.command("酒帮助")
    async def help_command(self, event: AstrMessageEvent):
        """指令帮助指南"""
        yield event.plain_result(
            "指令帮助\n"\
            +"/酒 [文字内容]\n"+"用于将用户输入转义给酒馆并且返回结果，不支持图片输入，禁止输入为空\n"
            +"/酒切换 [名字]\n"+"切换角色卡，若角色列表中无则不进行操作，禁止输入数字\n"
            +"/酒删除 [楼层数]\n"+"删除楼层，当不输入任何楼层数时默认删除一层，建议两层进行删除包括用户输入\n"
            +"/酒加卡 [图片] or /酒加卡\n"+"添加角色卡到酒馆，支持直接附带图片、引用(回复)含图消息、或指令后计时内单发图片三种方式\n"
            +"/酒删卡 [名字]\n"+"删除指定角色卡，若删除角色卡为当前角色卡则自动切换至默认，禁止删除默认卡\n"
            +"/酒重新\n"+"将最新楼层的输入重新生成并且返回，不输入任何参数\n"
            +"/酒查看\n"+"查看最新楼层的消息，当最新为用户输入时也会返回；引用一条消息后发送本指令，可定位其对应的楼层数\n"
            +"/酒状态\n"+"查看当前角色卡和角色卡列表以及浏览器的状态\n"
            +"/酒帮助\n"+"你现在不就在看我，你问我？\n"
            +"/酒启动[管理员指令]\n"+"用于启动插件目录中的酒馆，启动后自动连接\n"
            +"/酒重置[管理员指令]\n"+"用于重置所有全局变量，当变量混乱无法使用时，可进行尝试\n"
            +"/酒停止[管理员指令]\n"+"关闭插件浏览器并清理后台所有 chrome/chromium 进程\n"
            +"/酒进程[管理员指令]\n"+"查看当前 chrome/chromium 进程数量与浏览器状态"
            )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_received(self, event: AstrMessageEvent):
        """全局监听消息，用于捕捉等待状态下用户单独发送的角色卡"""
        messages = event.get_messages() # 过滤掉空白消息
        if not messages:
            return
        session_key = f"{event.get_group_id()}_{event.get_sender_id()}" 
        if session_key not in self.waiting_sessions: # 如果不在等待列表，直接放行
            return
        if time.time() > self.waiting_sessions[session_key]: # 检查是否已经超时
            del self.waiting_sessions[session_key]
            yield event.plain_result("等待超时，操作已取消")
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
                    yield event.plain_result("已接收角色卡,添加中~")
                    await bartender_crawler.process_image(self, image_comp) # 进入统一处理流程
                    chats = '\n'.join(self.chats_name_id.keys())
                    yield event.plain_result(f"当前角色列表：\n{chats}")
                finally:
                    self.status_running = True
            else:
                yield event.plain_result("有其他操作进行中，请稍后重试")
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
