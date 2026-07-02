# -*- coding: utf-8 -*-
import time, aiohttp, platform
import subprocess, os, shutil
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Node, Nodes, Plain, Image, File

# 设置环境变量以启用 Playwright 的调试模式，0为正常模式，1为调试模式
os.environ["PWDEBUG"] = "0"

# 插件注册，参数分别为：插件名（唯一标识符）、作者、简介、版本号    
@register("astrbot_plugin_bartender",
           "dragonuniverse8248",
            "基于playwright无头浏览器库,对酒馆进行操作和交互,达成通过机器人游玩酒馆",
            "1.0.0")



# 爬虫类定义
class bartender_crawler(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.ST_URL = f"{config['browser_ip']}:{config['browser_port']}" # 获取配置的本地酒馆地址
        self.chats_name_id = {} # 初始化角色字典
        self.default_chat = config['now_chats_name'] # 获取配置文件当前角色
        self.browser = None # 初始化浏览器类
        self.status_running = False # 消息状态初始化
        self.config = config # 初始化配置文件
        self.cache_dir = Path("data/temp/astrbot_plugin_bartender") # 初始化本地缓存文件夹路径
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.waiting_sessions = {} # 初始化会话状态字典，用于记录哪些用户正在等待发送图片，格式为: {"群号_用户ID": 过期时间戳}
        self.plugin_dir = Path(__file__).parent # 获取当前目录
        self.browser_dir = self.plugin_dir / "browser"

    async def initialize_browser(self):
        """使用 Playwright 来启动浏览器 手动管理线程"""
        await self.close_browser() # 判断并且关闭浏览器
        self.p = await async_playwright().start()
        if os.name == 'nt':
            exe_path = self.browser_dir / "chrome.exe"
        else:
            exe_path = self.browser_dir / "chrome"
        # 如果没有找到打包的浏览器，降级为使用 Playwright 默认下载的浏览器
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
        except Exception as e:
            logger.error(f"{self.ST_URL}页面加载失败: {e}")

    async def check_browser(self):
        """检查浏览器是否开启"""
        try:
            if (hasattr(self, 'browser') and self.browser and self.browser.is_connected())\
                    or (hasattr(self, 'playwright') and self.playwright):
                    self.page.locator("#rightNavDrawerIcon")
                    # logger.info("浏览器连接正常")
                    return True
            else:
                    await self.initialize_browser() # 重新打开浏览器
                    logger.info("浏览器重启成功") 
                    return True
        except Exception as e:
            logger.error(f"检测浏览器失败: {e}")
            return False

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
                    await options.select_option(value="1000")
                    logger.info("修改为1000分页")
                await self.close_chats()
                return True
            except Exception as e:
                logger.error(f"检查分页失败：{e}")
                return False
        else:
            logger.error("浏览器打开失败")
            return False

    async def get_all_chats(self):
        """获取所有的角色卡,最高1000张"""
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
                logger.errorr(f"获取角色列表失败")
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
        """获取最新消息"""
        if await self.check_browser() and await bartender_crawler.get_chat_Status(self): # 判断聊天栏状态
            message_box = self.page.locator("#chat > *") # 获取所有楼层
            # message_count = await message_box.count() - 1[mesid='{message_count}']
            message_new = await message_box.last.locator(".mes_block").locator(".mes_text").all_inner_texts()
            message_list = message_new[0].split("\n\n" and "\n")
            nodes_list = [ # 构建合并转发节点列表
                Node(
                    uin = bot_id,
                    name = self.config['now_chats_name'],
                    content = [Plain(str(item))]
                )
                for item in message_list]
            # logger.info(f"列表：{message_list[0]}")
            forward_message = Nodes(nodes=nodes_list) # Nodes包裹列表
            return forward_message
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
        """发送消息"""
        try:
            if await self.check_browser() and await self.get_chat_Status(): # 检测状态
                    await self.page.locator("#send_textarea").fill(user) # 将文本输入至聊天框
                    await self.page.locator("#send_but").click() # 点击发送按钮
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible") # 检测AI生成中
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="hidden",timeout=360000) # 检测生成完成
                    await self.page.wait_for_selector("#send_but",state="visible",timeout=360000) # 发送按钮已经复位
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
                    await self.page.locator("#options_button").click() # 打开菜单
                    await self.page.locator("#option_regenerate").click() # 点击重新生成按钮
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="visible") # 检测AI生成中
                    await self.page.wait_for_selector(".fa-solid.fa-circle-stop",state="hidden",timeout=360000) # 检测生成完成
                    await self.page.wait_for_selector("#send_but",state="visible",timeout=360000) # 发送按钮已经复位
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

    async def close_browser_auto(self):
        """线程安全模式判断关闭"""
        if self.config['thread_safe_mode']: # 判断并且关闭浏览器
            await self.close_browser()

    async def close_browser(self):
        """关闭浏览器"""
        if hasattr(self, 'browser') and self.browser and self.browser.is_connected(): # 检查是否存在浏览器
            await self.browser.close() # 关闭浏览器
        if hasattr(self, 'playwright') and self.playwright: # 检测是否存在浏览器
            await self.playwright.stop() # 关闭浏览器

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
        """上传角色卡,只支持png图片"""
        if self.status_running: # 判断运行状态
            self.status_running = False
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
            self.status_running = True

    async def del_chat_png(self, dal_name):
        """删除角色卡"""
        if self.check_browser():
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





# 机器人指令定义
    # @filter.command("test")
    # async def test(self, event: AstrMessageEvent):
    #     """这是一个测试指令"""
    #     logger.info("触发了 test 指令")
    #     await bartender_crawler.open_browser_auto(self, False)
    #     await bartender_crawler.switch_chats(self, "创世神喻")
    #     await bartender_crawler.close_browser_auto(self)
    #     yield event.plain_result(f"喵~这是测试指令的回复")

    @filter.command("酒关闭")
    async def command_close_browser(self, event: AstrMessageEvent):
        """关闭浏览器"""
        await bartender_crawler.close_browser(self)
        yield event.plain_result("浏览器已关闭")

    @filter.command("酒")
    async def command_send_message(self, event: AstrMessageEvent):
        """酒馆发送信息"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            user_message = event.message_str.strip()
            if user_message != "" and user_message != None:
                yield event.plain_result("调酒中~")
                user_message = (user_message.split()[1:])[0]
                bot_id =event.message_obj.self_id # 获取bot_id
                await bartender_crawler.send_message(self, user_message) # 发送消息至酒馆
                forward_message =  await bartender_crawler.get_new_message(self, bot_id) # 获取最新的消息
                remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
                if forward_message != None:
                    yield MessageEventResult(f"当前共{remaining}楼层")
                    yield MessageEventResult(chain=[forward_message])
                else:
                    yield event.plain_result("合并消息为空")
            else:
                yield event.plain_result("禁止输入为空")
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("正在Shake~，请稍作等待")

    @filter.command("酒重新")
    async def command_rest_message(self, event: AstrMessageEvent):
        """重新生成当前楼层"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            user_message = self.config['now_chats_name']
            if user_message != "" and user_message != None:
                yield MessageEventResult("重调中~")
                bot_id =event.message_obj.self_id # 获取bot_id
                await bartender_crawler.rest_message(self)
                forward_message =  await bartender_crawler.get_new_message(self, bot_id)
                if forward_message != None:
                    yield MessageEventResult(chain=[forward_message])
                else:
                    yield event.plain_result("合并消息为空")
            else:
                yield event.plain_result("禁止输入为空")
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("正在Shake~，请稍作等待")

    @filter.command("酒查看")
    async def command_get_message(self, event: AstrMessageEvent):
        """获取当前最新楼层"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            bot_id =event.message_obj.self_id # 获取bot_id
            # logger.info(f"当前id：{bot_id}")
            forward_message = await bartender_crawler.get_new_message(self, bot_id) # 获取信息
            remaining = await bartender_crawler.get_now_floor(self,0) # 获取当前楼层数
            if forward_message != None:
                yield MessageEventResult(f"当前共{remaining}楼层")
                yield MessageEventResult(chain=[forward_message])
            else:
                yield event.plain_result("合并消息为空")
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒状态")
    async def command_get_status(self, event: AstrMessageEvent):
        """获取当前所有状态"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            await self.get_chat_Status()
            if self.config['now_chats_name'] == None: 
                chat = "无角色卡"
            chat = self.config['now_chats_name']
            logger.info(f"角色卡：{chat}")
            if await bartender_crawler.check_browser(self):
                connect_status = "正常"
            else:
                connect_status = "失败"
            chats = '\n'.join(self.chats_name_id.keys())
            yield event.plain_result(f"当前角色卡为：{chat}\n"+f"链接状态：{connect_status}\n"+f"角色列表：\n{chats}")
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒切换")
    async def command_chat_switch(self, event: AstrMessageEvent):
        """酒馆切换角色卡"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            user_message = event.message_str.strip()
            if user_message != "酒切换":
                chat_name = (user_message.split()[1:])[0]
                if await bartender_crawler.switch_chats(self, chat_name):
                    # logger.info(f"切换角色卡至：{chat_name}")
                    yield event.plain_result(f"角色卡切换至：{chat_name}")
                else:
                    yield event.plain_result(f"未找到角色卡：{chat_name}")
            else:
                yield event.plain_result("消息不能为空")
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒删除")
    async def command_del_message(self, event: AstrMessageEvent):
        """删除聊天楼层"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            del_message = None
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
                    logger.info(f"错误{e}")
                    yield event.plain_result("请输入数字")
            if del_status and del_message != None:
                yield event.plain_result(f"已删除{abs(del_message)}楼层\n"+f"剩余{remaining}楼层")
            else:
                yield event.plain_result("输入楼层数异常或最低")
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.command("酒加卡")
    async def upload_chat_command(self, event: AstrMessageEvent):
        """添加角色卡至酒馆"""
        if self.status_running: # 判断运行状态
            image_comp = None
            for comp in event.get_messages(): # 1. 遍历当前指令的消息链，寻找是否在同一条消息里就带了图片
                if isinstance(comp, Image):
                    image_comp = comp
                    break
            if image_comp: # 情况 A：指令和图片在同一条消息，直接进入处理流程
                yield await bartender_crawler.process_image(self, image_comp)
                chats = '\n'.join(self.chats_name_id.keys())
                yield event.plain_result(f"角色列表：\n{chats}")
            else: # 情况 B：指令和图片分条发送。为该用户开启等待状态，设定有效期
                session_key = f"{event.get_group_id()}_{event.get_sender_id()}"
                self.waiting_sessions[session_key] = time.time() + int(self.config['upload_interval'])
                yield event.plain_result(f"请在{self.config['upload_interval']}秒内发送角色卡")
        else:
            yield event.plain_result("等待其他操作完成")


    @filter.command("酒删卡")
    async def del_chat_command(self, event: AstrMessageEvent):
        """删除聊天楼层"""
        if self.status_running:
            self.status_running = False
            await bartender_crawler.open_browser_auto(self, False)
            user_message = event.message_str.strip() # 获取输入消息
            if user_message == "酒删卡" : # 判断消息是否为空
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
            await bartender_crawler.close_browser_auto(self)
            self.status_running = True
        else:
            yield event.plain_result("等待其他操作完成")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒进程")
    async def del_chrome_command(self, event: AstrMessageEvent):
        """删除后台所有chrome进程"""
        if self.config['kill_Process']:
            await bartender_crawler.kill_chrome_process(self)
            yield event.plain_result("已尝试清理所有后台 Chrome/Chromium 进程")
        else:
            yield event.plain_result("请在配置文件中开启指令")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("酒重置")
    async def reset_plugin_command(self, event: AstrMessageEvent):
        """重置插件所有参数"""
        await bartender_crawler.open_browser_auto(self, False)
        self.chats_name_id = {} # 初始化角色字典
        self.status_running = False # 消息状态初始化
        self.cache_dir = Path("data/temp/astrbot_plugin_bartender") # 初始化本地缓存文件夹路径
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
            +"/酒加卡 [图片] or /酒加卡\n"+"添加角色卡到酒馆，由于某些渠道无法图片和指令一起发送，在直接发送后，将计时等待图片，计时内单发图片即可添加，计时长短在配置文件调整\n"
            +"/酒删卡 [名字]\n"+"删除指定角色卡，若删除角色卡为当前角色卡则自动切换至默认，禁止删除默认卡\n"
            +"/酒重新\n"+"将最新楼层的输入重新生成并且返回，不输入任何参数\n"
            +"/酒查看\n"+"查看最新楼层的消息，当最新为用户输入时也会返回\n"
            +"/酒状态\n"+"查看当前角色卡和角色卡列表以及浏览器的状态\n"
            +"/酒关闭\n"+"调试指令用于手动关闭还处于线程中的浏览器\n"
            +"/酒帮助\n"+"你现在不就在看我，你问我？\n"
            +"/酒重置[管理员指令]\n"+"用于重置所有全局变量，当变量混乱无法使用时，可进行尝试\n"
            +"/酒进程[管理员指令]\n"+"在配置文件开启后可用，将杀死后台所有的chrome进程，用于解决无头浏览器溢出"
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
            yield event.plain_result("已接收角色卡,添加中~")
            yield await bartender_crawler.process_image(self, image_comp) # 进入统一处理流程
            chats = '\n'.join(self.chats_name_id.keys())
            yield event.plain_result(f"当前角色列表：\n{chats}")
        else: # 发的是纯文字，静默忽略
            return 



    # 生命周期管理
    async def initialize(self):
        """异步的插件初始化方法，当插件被加载/启用时会调用。"""
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
        self.status_running = True
        logger.info("插件初始化完成,浏览器已开启")

    async def terminate(self):
        """异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        await bartender_crawler.close_browser(self)
        logger.info("插件已被卸载，浏览器已关闭")
