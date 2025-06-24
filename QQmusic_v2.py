import os
import time
import threading
import platform
import json
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import logging
import re
import sys
import psutil
import requests
import subprocess
import pyaudio
import wave
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from webdriver_manager.chrome import ChromeDriverManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("qqmusic_recorder.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置参数
MUSIC_PLATFORM_URL = "https://y.qq.com"
SONG_ID = "004Z8Ihr0JIu5s"  # 示例歌曲ID: 周杰伦 - 最伟大的作品
OUTPUT_DIR = "qqmusic_recordings"  # 输出目录
DEBUG_PORT = 9223  # 调试端口（避免与网易云冲突）
CONFIG_FILE = "qqmusic_config.json"  # 配置文件

# 跨平台浏览器配置
SYSTEM = platform.system()
if SYSTEM == "Windows":
    BROWSER_BINARY_PATHS = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    ]
    BROWSER_TYPE = "edge"  # 优先使用Edge
elif SYSTEM == "Darwin":  # macOS
    BROWSER_BINARY_PATHS = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium"
    ]
    BROWSER_TYPE = "chrome"  # macOS使用Chrome
else:  # Linux
    BROWSER_BINARY_PATHS = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chrome"
    ]
    BROWSER_TYPE = "chrome"

# 音频质量配置 (可调整以平衡质量和文件大小)
AUDIO_QUALITY = {
    "high": {"rate": 44100, "channels": 2, "format": pyaudio.paInt16},      # 高质量 (大文件)
    "medium": {"rate": 22050, "channels": 1, "format": pyaudio.paInt16},    # 中等质量 (文件大小减少75%)
    "low": {"rate": 11025, "channels": 1, "format": pyaudio.paInt8}         # 低质量 (最小文件)
}
SELECTED_QUALITY = "medium"  # 默认使用中等质量

# 全局变量
driver = None
browser_process = None

def setup_virtual_audio():
    """设置虚拟音频设备（Windows）"""
    logger.info("请确保已安装VB-Audio Virtual Cable并设置默认输出设备")
    try:
        # 获取所有音频设备
        devices = sd.query_devices()
        logger.info("可用的音频设备:")
        for i, device in enumerate(devices):
            device_name = device.get('name', 'Unknown Device')
            input_channels = device.get('max_input_channels', 0)
            logger.info(f"{i}: {device_name} - 输入通道: {input_channels}")
        
        # 尝试找到虚拟音频设备
        for device in devices:
            device_name = device.get('name', '')
            if device_name and ("vb-audio" in device_name.lower() or "virtual" in device_name.lower()):
                logger.info(f"使用虚拟音频设备: {device_name}")
                return device_name
        
        # 尝试找到立体声混音设备
        for device in devices:
            device_name = device.get('name', '')
            if device_name and ("立体声混音" in device_name or "Stereo Mix" in device_name):
                logger.info(f"使用立体声混音设备: {device_name}")
                return device_name
        
        logger.warning("未找到虚拟音频设备或立体声混音，将使用默认输出设备")
        return None
    except Exception as e:
        logger.error(f"查询音频设备失败: {str(e)}")
        return None

def get_song_info(driver, song_id):
    """获取QQ音乐歌曲信息和时长"""
    logger.info(f"获取歌曲信息和时长: ID={song_id}")
    try:
        # 导航到歌曲页面
        driver.get(f"{MUSIC_PLATFORM_URL}/n/ryqq/songDetail/{song_id}")
        
        # 等待页面加载完成
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("页面加载完成")
        
        # 等待歌曲信息加载
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".data__name_txt"))
        )
        
        # 额外等待确保内容完全加载
        time.sleep(2)
        
        # 等待歌手信息也加载完成
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".data__singer_txt"))
        )
        
        # 获取歌曲名
        song_name_element = driver.find_element(By.CSS_SELECTOR, ".data__name_txt")
        song_name = song_name_element.text.strip()
        
        # 获取歌手名
        artist_element = driver.find_element(By.CSS_SELECTOR, ".data__singer_txt")
        artist = artist_element.text.strip()
        
        # 组合完整的歌曲名称
        full_song_name = f"{song_name} - {artist}"
        
        return full_song_name
    
    except Exception as e:
        logger.error(f"获取歌曲信息失败: {str(e)}")
        # 保存截图
        driver.save_screenshot(f"qq_song_info_error_{song_id}.png")
        return None

def is_player_window(driver):
    """检查当前窗口是否为播放器窗口（增强版：优先检查URL）"""
    try:
        # 优先检查页面URL是否为播放器页面（最准确的判断方式）
        current_url = driver.current_url
        logger.debug(f"检查窗口URL: {current_url}")
        
        # 检查URL是否包含播放器路径
        if "/player" in current_url or "/ryqq/player" in current_url:
            logger.info("根据URL确认为播放器窗口！")
            return True
        
        # 次要检查：URL包含play相关路径
        if "play" in current_url.lower() and ("y.qq.com" in current_url or "music.qq.com" in current_url):
            logger.info("根据URL确认为音乐播放相关窗口！")
            return True
        
        # 备用检查：检查是否存在播放器相关元素
        player_elements = [
            ".player_music__time",  # 播放时间显示
            ".mod_player",          # 播放器模块
            ".progress",            # 进度条
            ".player__cover"        # 播放器封面
        ]
        
        for selector in player_elements:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and len(elements) > 0:
                    logger.debug(f"通过元素检测确认播放器窗口: {selector}")
                    return True
            except Exception:
                continue
        
        logger.debug("未检测到播放器特征")
        return False
        
    except Exception as e:
        logger.debug(f"检查播放器窗口失败: {str(e)}")
        return False

def get_new_window_handle(driver, original_handles):
    """获取新打开的播放器窗口句柄（增强版：优先URL检查）"""
    try:
        # 等待新窗口出现，最多等待15秒
        WebDriverWait(driver, 15).until(
            lambda d: len(d.window_handles) > len(original_handles)
        )
        
        current_handles = driver.window_handles
        new_handles = [h for h in current_handles if h not in original_handles]
        
        if new_handles:
            logger.info(f"检测到 {len(new_handles)} 个新窗口，开始验证播放器窗口...")
            
            # 遍历所有新窗口，使用增强版检查找到播放器窗口
            for i, handle in enumerate(new_handles):
                try:
                    logger.info(f"检查第 {i+1} 个新窗口...")
                    driver.switch_to.window(handle)
                    
                    # 等待窗口内容加载
                    WebDriverWait(driver, 5).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    
                    # 使用增强版is_player_window进行检查（优先URL检查）
                    if is_player_window(driver):
                        logger.info("找到并确认播放器窗口！后续操作将在此窗口进行")
                        return handle
                        
                except Exception as e:
                    logger.debug(f"检查窗口 {handle} 失败: {str(e)}")
                    continue
            
            # 如果没找到明确的播放器窗口，返回第一个新窗口
            logger.warning("未找到明确的播放器窗口，使用第一个新窗口")
            driver.switch_to.window(new_handles[0])
            return new_handles[0]
        else:
            logger.warning("未检测到新窗口")
            return None
            
    except Exception as e:
        logger.warning(f"等待新窗口超时: {str(e)}")
        return None

def load_song_to_player_with_existing_window(driver, existing_player_handle, song_id):
    """使用已存在的播放器窗口通过直接URL加载歌曲（原则二：直接URL加载，强制刷新状态）
    
    防爬机制对策：在加载新歌后主动刷新页面，避免QQ音乐的防爬卡顿问题
    """
    logger.info("使用已存在的播放器窗口通过直接URL加载歌曲...")
    try:
        # 验证已存在的窗口句柄是否仍然有效
        try:
            driver.switch_to.window(existing_player_handle)
            logger.info("成功切换到已保存的播放器窗口")
        except Exception as e:
            logger.warning(f"已保存的播放器窗口无效: {str(e)}")
            return False, None
        
        # 构建播放器URL
        player_url = f"https://y.qq.com/n/ryqq/player?songid={song_id}"
        logger.info(f"直接加载播放器URL: {player_url}")
        
        # 直接在播放器窗口中加载新歌URL，强制页面进入干净的初始状态
        driver.get(player_url)
        
        # 等待页面完全加载
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("播放器页面加载完成")
        
        # 防爬机制对策：刷新页面确保状态清洁
        logger.info("执行防爬对策：刷新页面确保播放器状态正常...")
        driver.refresh()
        
        # 等待刷新后页面重新加载
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("页面刷新完成，播放器状态已重置")
        
        # 等待播放器基本元素加载
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".player_music__time, .mod_player, .progress"))
        )
        logger.info("播放器元素已加载")
        
        # 验证加载是否成功并确认播放器窗口
        if is_player_window(driver):
            current_url = driver.current_url
            logger.info(f"直接URL加载成功，播放器窗口确认！URL: {current_url[:50]}...")
            return True, existing_player_handle
        else:
            logger.warning("直接URL加载成功，但窗口验证失败")
            return True, existing_player_handle
        
    except Exception as e:
        logger.error(f"使用已存在窗口直接加载URL失败: {str(e)}")
        driver.save_screenshot(f"qq_direct_load_error_{time.strftime('%H%M%S')}.png")
        return False, None

def load_song_to_player(driver):
    """加载歌曲到播放器 - 使用稳健的窗口切换策略"""
    logger.info("开始加载歌曲到播放器...")
    try:
        # 步骤1: 记录当前窗口句柄
        original_handles = driver.window_handles
        logger.info(f"记录当前窗口数量: {len(original_handles)}")
        
        # 等待播放按钮加载
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "mod_btn_green"))
        )
        logger.info("播放按钮已加载")
        
        # 额外等待确保按钮可点击
        time.sleep(2)
        
        # 步骤2: 点击播放按钮（加载歌曲到播放器）
        buttons = driver.find_elements(By.CLASS_NAME, "mod_btn_green")
        load_clicked = False
        
        for btn in buttons:
            try:
                # 等待按钮内的文本元素加载
                WebDriverWait(driver, 10).until(
                    lambda d: btn.find_element(By.CLASS_NAME, "btn__txt")
                )
                text_span = btn.find_element(By.CLASS_NAME, "btn__txt")
                if text_span.text.strip() == "播放":
                    # 确保按钮可点击
                    WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable(btn)
                    )
                    btn.click()
                    logger.info("点击加载按钮成功")
                    load_clicked = True
                    break
            except Exception as e:
                logger.debug(f"检查播放按钮失败: {str(e)}")
                continue
        
        if not load_clicked:
            logger.warning("未找到可点击的播放按钮")
            return False, None
        
        # 步骤3: 查找并切换到新窗口
        logger.info("等待播放器窗口打开...")
        new_window_handle = get_new_window_handle(driver, original_handles)
        
        if new_window_handle:
            # get_new_window_handle已经切换到播放器窗口并确认
            # 再次验证确保在正确的播放器窗口
            if is_player_window(driver):
                logger.info("播放器窗口确认成功，准备进行后续操作")
                current_url = driver.current_url
                logger.info(f"播放器窗口URL: {current_url}")
                return True, new_window_handle
            else:
                logger.warning("窗口验证失败，但继续尝试")
                return True, new_window_handle
        else:
            # 如果没有新窗口，可能是在同一窗口内播放
            logger.info("未检测到新窗口，可能在当前窗口加载")
            return True, None
        
    except Exception as e:
        logger.error(f"加载歌曲失败: {str(e)}")
        driver.save_screenshot(f"qq_load_error_{time.strftime('%H%M%S')}.png")
        return False, None

def ensure_playback_starts(driver):
    """确保播放器开始播放 - 耐心等待DOM稳定后检查播放状态"""
    logger.info("检查播放器播放状态...")
    try:
        # 步骤1: 等待播放器基础元素稳定加载
        logger.info("等待播放器基础元素稳定...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".player_music__time, .mod_player, .progress"))
        )
        
        # 步骤2: 耐心等待DOM重绘完成（弹窗消失后的状态稳定）
        logger.info("等待DOM重绘完成，确保页面状态稳定...")
        time.sleep(3)  # 给页面充分时间完成DOM重绘
        
        # 步骤3: 检查播放状态
        is_playing = False
        
        # 方法1: 检查播放/暂停按钮的状态
        logger.info("方法1: 检查播放/暂停按钮状态...")
        try:
            play_pause_buttons = driver.find_elements(By.CSS_SELECTOR, ".player__btn_play, .btn_play, .play_btn")
            for btn in play_pause_buttons:
                if btn.is_displayed():
                    # 检查按钮的class或其他属性来判断状态
                    btn_classes = btn.get_attribute("class")
                    btn_title = btn.get_attribute("title") or ""
                    
                    # 如果按钮显示"播放"相关文字，说明当前是暂停状态
                    if "play" in btn_classes.lower() or "播放" in btn_title:
                        logger.info("检测到播放按钮，当前为暂停状态")
                        is_playing = False
                        break
                    # 如果按钮显示"暂停"相关文字，说明当前是播放状态
                    elif "pause" in btn_classes.lower() or "暂停" in btn_title:
                        logger.info("检测到暂停按钮，当前为播放状态")
                        is_playing = True
                        break
        except Exception as e:
            logger.debug(f"方法1检查播放状态失败: {str(e)}")
        
        # 方法2: 检查进度条是否在变化
        if not is_playing:
            logger.info("方法2: 检查进度条元素...")
            try:
                progress_elements = driver.find_elements(By.CSS_SELECTOR, ".progress_bar, .progress__cur, .current_time")
                if progress_elements:
                    logger.debug("检测到进度条元素，假设正在播放")
                    is_playing = True
            except Exception as e:
                logger.debug(f"方法2检查播放状态失败: {str(e)}")
        
        # 步骤4: 如果没有在播放，耐心等待并点击主播放按钮
        if not is_playing:
            logger.info("播放器未在播放，开始耐心寻找主播放按钮...")
            
            # 更全面的主播放按钮选择器（按优先级排序）
            play_button_selectors = [
                ".btn_big_play",            # 大播放按钮
                ".player__btn_play",        # 播放器播放按钮
                ".btn_play",                # 通用播放按钮
                ".play_btn",                # 播放按钮
                ".mod_btn_play",            # 模块播放按钮
                "[title='播放']",            # 通过title属性
                "[aria-label='播放']",       # 通过aria-label属性
                ".icon_play",               # 播放图标
                ".player-play",             # 播放器播放
                ".music-play",              # 音乐播放
                ".btn[class*='play']"       # 包含play的按钮
            ]
            
            play_button_clicked = False
            
            # 对每个选择器，耐心等待并尝试点击
            for i, selector in enumerate(play_button_selectors):
                logger.info(f"尝试选择器 {i+1}/{len(play_button_selectors)}: {selector}")
                try:
                    # 耐心等待按钮出现并变为可点击状态
                    logger.debug(f"等待按钮变为可点击状态...")
                    buttons = WebDriverWait(driver, 8).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                    )
                    
                    for btn in buttons:
                        try:
                            # 确保按钮可见且可交互
                            if btn.is_displayed() and btn.is_enabled():
                                # 额外等待确保按钮完全准备好
                                WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable(btn)
                                )
                                
                                btn.click()
                                logger.info(f"成功点击主播放按钮: {selector}")
                                play_button_clicked = True
                                break
                                
                        except Exception as e:
                            logger.debug(f"按钮点击失败: {str(e)}")
                            continue
                    
                    if play_button_clicked:
                        break
                        
                except Exception as e:
                    logger.debug(f"选择器 {selector} 等待超时或失败: {str(e)}")
                    continue
            
            if not play_button_clicked:
                logger.warning("耐心等待后仍未找到可点击的播放按钮")
                # 最后的尝试：截图保存现场
                driver.save_screenshot(f"qq_no_play_button_{time.strftime('%H%M%S')}.png")
                return False
            
            # 步骤5: 播放按钮点击后，等待播放真正开始
            logger.info("播放按钮已点击，等待播放真正开始...")
            time.sleep(3)  # 给播放充分的启动时间
            
        else:
            logger.info("播放器已在播放状态，无需点击")
        
        # 步骤6: 最终验证播放是否真正开始
        logger.info("最终验证播放状态...")
        time.sleep(1)
        
        return True
        
    except Exception as e:
        logger.error(f"确保播放开始失败: {str(e)}")
        driver.save_screenshot(f"qq_ensure_play_error_{time.strftime('%H%M%S')}.png")
        return False

def ensure_playback_paused(driver):
    """确保播放器处于暂停状态"""
    logger.info("检查并确保播放器暂停状态...")
    try:
        # 查找暂停按钮的选择器（表示当前正在播放）
        pause_button_selectors = [
            ".btn_big_play--pause",      # QQ音乐的暂停按钮（播放状态时显示）
            ".player__btn_pause",        # 播放器暂停按钮
            ".btn_pause",                # 通用暂停按钮
            ".pause_btn",                # 暂停按钮
            "[title='暂停']",             # 通过title属性
            "[aria-label='暂停']"         # 通过aria-label属性
        ]
        
        # 尝试找到并点击暂停按钮
        for selector in pause_button_selectors:
            try:
                buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        btn.click()
                        logger.info(f"成功点击暂停按钮: {selector}")
                        time.sleep(1)  # 等待暂停生效
                        return True
            except Exception:
                continue
        
        # 如果没找到明确的暂停按钮，尝试找播放按钮（表示当前暂停状态）
        play_button_selectors = [
            ".btn_big_play:not(.btn_big_play--pause)",  # 播放按钮（暂停状态时显示）
            ".player__btn_play",
            ".btn_play",
            ".play_btn"
        ]
        
        for selector in play_button_selectors:
            try:
                buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        logger.info(f"检测到播放按钮 {selector}，说明已处于暂停状态")
                        return True
            except Exception:
                continue
        
        logger.info("无法明确确认暂停状态，假设已暂停")
        return True
        
    except Exception as e:
        logger.warning(f"确保暂停状态失败: {str(e)}")
        return False

def reset_playback_to_start(driver):
    """播放归零：点击进度条开头，将播放进度重置到00:00 - 增强版带JavaScript备用方案"""
    logger.info("执行播放归零操作...")
    try:
        # 等待进度条元素稳定
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".progress_bar, .progress__bar, .player_progress"))
        )
        
        # 查找最精确的进度条元素（按优先级排序，优先选择内层元素）
        progress_selectors = [
            ".player_progress__inner",    # 最精确的内层进度条
            ".progress__inner",           # 通用内层进度条
            ".progress_bar__inner",       # 进度条内层
            ".progress_bar",              # 主进度条
            ".progress__bar",             # 进度条变体
            ".player_progress",           # 播放器进度条
            ".mod_progress",              # 模块进度条
            ".timeline",                  # 时间轴
            ".seek-bar"                   # 搜索条
        ]
        
        progress_element = None
        
        for selector in progress_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if element.is_displayed() and element.size['width'] > 50:
                        progress_element = element
                        break
                if progress_element:
                    break
            except Exception:
                continue
        
        if progress_element:
            logger.info(f"找到进度条元素，宽度: {progress_element.size['width']}px")
            
            # 方法1: 使用ActionChains精确点击
            try:
                logger.info("方法1: 使用ActionChains点击进度条最左侧...")
                actions = ActionChains(driver)
                
                # 步骤1: 移动到元素中心点
                actions.move_to_element(progress_element)
                
                # 步骤2: 从中心点向左移动到起始位置（向右偏移8像素确保在有效区域）
                progress_width = progress_element.size['width']
                left_offset = -(progress_width // 2) + 8
                actions.move_by_offset(left_offset, 0)
                
                # 执行点击
                actions.click().perform()
                
                logger.info("ActionChains播放归零操作成功")
                time.sleep(2)  # 等待播放位置重置完成
                return True
                
            except Exception as e:
                logger.warning(f"ActionChains方法失败: {str(e)}, 尝试JavaScript方法...")
        
        # 方法2: JavaScript "核武器"方案 - 当标准点击失败时的终极解决方案
        logger.info("方法2: 使用JavaScript直接触发点击事件...")
        try:
            # 更全面的进度条选择器列表，用于JavaScript查找
            js_selectors = [
                ".player_progress__inner",
                ".progress__inner", 
                ".progress_bar__inner",
                ".progress_bar",
                ".progress__bar",
                ".player_progress",
                ".mod_progress"
            ]
            
            # JavaScript脚本：查找进度条并触发点击事件
            js_script = """
            var progressBar = null;
            var selectors = arguments[0];
            
            // 查找最佳的进度条元素
            for (var i = 0; i < selectors.length; i++) {
                var elements = document.querySelectorAll(selectors[i]);
                for (var j = 0; j < elements.length; j++) {
                    var element = elements[j];
                    if (element.offsetWidth > 50 && element.offsetHeight > 0) {
                        progressBar = element;
                        break;
                    }
                }
                if (progressBar) break;
            }
            
            if (progressBar) {
                // 计算左边界位置（距离左边8像素处）
                var rect = progressBar.getBoundingClientRect();
                var clickX = rect.left + 8;
                var clickY = rect.top + rect.height / 2;
                
                // 创建并触发鼠标事件
                var clickEvent = new MouseEvent('click', {
                    'view': window,
                    'bubbles': true,
                    'cancelable': true,
                    'clientX': clickX,
                    'clientY': clickY
                });
                
                progressBar.dispatchEvent(clickEvent);
                
                return {
                    'success': true, 
                    'element': progressBar.className,
                    'width': rect.width,
                    'clickPosition': clickX - rect.left
                };
            } else {
                return {'success': false, 'reason': 'No progress bar found'};
            }
            """
            
            # 执行JavaScript
            result = driver.execute_script(js_script, js_selectors)
            
            if result.get('success'):
                logger.info(f"JavaScript播放归零成功!")
                logger.info(f"使用元素: {result.get('element')}")
                logger.info(f"进度条宽度: {result.get('width')}px")
                logger.info(f"点击位置: {result.get('clickPosition')}px from left")
                time.sleep(2)  # 等待播放位置重置完成
                return True
            else:
                logger.warning(f"JavaScript方法也失败: {result.get('reason')}")
                
        except Exception as e:
            logger.warning(f"JavaScript方法执行失败: {str(e)}")
        
        # 如果所有方法都失败
        logger.warning("所有播放归零方法都失败了")
        driver.save_screenshot(f"qq_reset_playback_failed_{time.strftime('%H%M%S')}.png")
        return False
            
    except Exception as e:
        logger.warning(f"播放归零操作失败: {str(e)}")
        driver.save_screenshot(f"qq_reset_playback_error_{time.strftime('%H%M%S')}.png")
        return False

def get_song_duration(driver):
    """获取歌曲播放时长，添加等待机制"""
    logger.info("开始获取播放长度...")
    try:
        # 等待播放器时间元素加载
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "player_music__time"))
        )
        logger.info("播放器时间元素已加载")
        
        # 等待时间信息显示完整
        time.sleep(3)
        
        # 多次尝试获取时长信息
        for attempt in range(5):
            try:
                time_div = driver.find_element(By.CLASS_NAME, "player_music__time")
                time_text = time_div.text.strip()
                logger.info(f"获取到的时间文本: '{time_text}'")
                
                if " / " in time_text:
                    all_texts = time_text.split(" / ")
                    if len(all_texts) >= 2:
                        duration = all_texts[1].strip()
                        if ":" in duration:
                            minutes, seconds = map(int, duration.split(":"))
                            duration_seconds = minutes * 60 + seconds
                            logger.info(f"获取到的播放长度: {duration_seconds} 秒")
                            return duration_seconds
                
                logger.info(f"第{attempt + 1}次尝试，时间格式不正确，等待2秒后重试...")
                time.sleep(2)
                
            except Exception as e:
                logger.warning(f"第{attempt + 1}次获取时长失败: {str(e)}")
                time.sleep(2)
        
        logger.warning("多次尝试后仍无法获取歌曲时长，使用默认180秒")
        return 180
        
    except Exception as e:
        logger.error(f"获取播放长度失败: {str(e)}")
        driver.save_screenshot(f"qq_duration_error_{time.strftime('%H%M%S')}.png")
        return 180

def handle_autoplay_popup(driver):
    """处理"自动播放"弹窗（原则三：优先处理"自动播放"弹窗）"""
    logger.info("检查并处理自动播放弹窗...")
    try:
        # 使用显式等待检查弹窗按钮是否存在
        popup_handled = False
        
        # 尝试多种弹窗按钮的选择器
        popup_selectors = [
            ".mod_btn_green.mod_btn",    # 主要的绿色按钮
            ".popup_btn",                # 弹窗按钮
            ".btn_play_popup",           # 播放弹窗按钮
            "[class*='popup']",          # 包含popup的class
            ".dialog-btn",               # 对话框按钮
            ".modal-btn"                 # 模态框按钮
        ]
        
        for selector in popup_selectors:
            try:
                # 使用WebDriverWait等待元素出现，但超时时间较短
                WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                logger.info(f"检测到弹窗元素: {selector}")
                
                # 等待元素可点击
                buttons = WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                )
                
                for btn in buttons:
                    try:
                        # 确保按钮可见且可点击
                        if btn.is_displayed() and btn.is_enabled():
                            btn_text = btn.text.strip()
                            btn_classes = btn.get_attribute("class") or ""
                            
                            # 检查按钮文字或class是否与播放相关
                            play_keywords = ["开始播放", "播放", "play", "start", "确定", "确认"]
                            if any(keyword in btn_text for keyword in play_keywords) or \
                               any(keyword in btn_classes.lower() for keyword in ["play", "start"]):
                                
                                # 等待按钮真正可点击
                                WebDriverWait(driver, 3).until(
                                    EC.element_to_be_clickable(btn)
                                )
                                btn.click()
                                logger.info(f"成功点击自动播放弹窗按钮: '{btn_text}' (选择器: {selector})")
                                popup_handled = True
                                
                                # 关键等待：给DOM充分时间重绘和稳定
                                logger.info("弹窗已处理，等待DOM重绘和页面状态稳定...")
                                time.sleep(4)  # 给页面充分时间完成DOM重绘
                                return True
                                
                    except Exception as e:
                        logger.debug(f"点击按钮失败: {str(e)}")
                        continue
                        
                if popup_handled:
                    break
                    
            except Exception as e:
                logger.debug(f"选择器 {selector} 未找到弹窗元素: {str(e)}")
                continue
        
        if not popup_handled:
            logger.info("未检测到需要处理的自动播放弹窗")
            return True  # 没有弹窗也算成功
        
        return popup_handled
        
    except Exception as e:
        logger.warning(f"处理自动播放弹窗时出错: {str(e)}")
        driver.save_screenshot(f"qq_popup_error_{time.strftime('%H%M%S')}.png")
        return False

# 更新音频设备选择逻辑
def select_recording_method():
    """选择录制方式"""
    # 加载配置
    config = load_config()
    saved_method = config.get('recording_method', None)
    
    logger.info("="*60)
    logger.info("请选择录制方式:")
    logger.info("1. 系统声卡录制 - 直接录制系统播放的声音")
    logger.info("2. 虚拟声卡录制 (推荐) - 使用VB-Audio Virtual Cable等虚拟声卡")
    logger.info("3. 立体声混音录制 - 使用Windows立体声混音功能")
    logger.info("4. 手动选择设备 - 查看所有可用设备并手动选择")
    
    if saved_method:
        method_names = {
            "1": "系统声卡录制",
            "2": "虚拟声卡录制", 
            "3": "立体声混音录制",
            "4": "手动选择设备"
        }
        logger.info(f"上次选择: {method_names.get(saved_method, saved_method)}")
    
    logger.info("="*60)
    
    while True:
        if saved_method:
            choice = input("请选择录制方式 (1-4, 直接回车使用上次选择): ").strip()
            if not choice:
                logger.info(f"使用上次选择: {saved_method}")
                return saved_method
        else:
            choice = input("请选择录制方式 (1-4, 默认为2): ").strip()
            if not choice:
                choice = "2"  # 默认虚拟声卡
        
        if choice in ["1", "2", "3", "4"]:
            # 保存用户选择
            config['recording_method'] = choice
            save_config(config)
            return choice
        else:
            logger.warning("无效选择，请输入1、2、3或4")

def select_audio_device():
    """根据用户选择的录制方式选择音频设备"""
    method = select_recording_method()
    
    p = pyaudio.PyAudio()
    devices = []
    
    # 列出所有输入设备
    logger.info("扫描可用的音频输入设备...")
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        max_input_channels = dev_info.get("maxInputChannels", 0)
        if int(max_input_channels) > 0:
            devices.append(dev_info)
    
    if not devices:
        logger.error("未找到可用的输入设备")
        p.terminate()
        return None
    
    # 根据选择的方式处理
    if method == "1":  # 系统声卡录制
        logger.info("选择了系统声卡录制模式")
        # 寻找默认输入设备或者最适合的设备
        default_device = None
        try:
            default_info = p.get_default_input_device_info()
            default_device = default_info
            device_name = default_info.get('name', 'Unknown Device')
            logger.info(f"使用默认输入设备: {device_name}")
            logger.info(f"✓ 系统声卡设备配置成功: {device_name}")
        except Exception as e:
            logger.warning(f"无法获取默认输入设备: {str(e)}")
            # 使用第一个可用设备
            default_device = devices[0]
            device_name = default_device.get('name', 'Unknown Device')
            logger.info(f"使用第一个可用设备: {device_name}")
            logger.info(f"✓ 系统声卡设备配置成功: {device_name}")
        
        p.terminate()
        return default_device
    
    elif method == "2":  # 虚拟声卡录制
        logger.info("选择了虚拟声卡录制模式")
        virtual_device = None
        
        # 更全面的虚拟声卡设备检测
        for i, dev in enumerate(devices):
            device_name = dev.get("name", "")
            if device_name:
                device_upper = device_name.upper()
                # 检测VB-Audio Cable
                if ("CABLE" in device_upper and "VB" in device_upper) or "VB-AUDIO" in device_upper:
                    virtual_device = dev
                    logger.info(f"找到VB-Audio设备: {device_name}")
                    break
                # 检测其他虚拟音频设备
                elif any(keyword in device_upper for keyword in ["VIRTUAL", "LOOPBACK", "SOUNDFLOWER", "BLACKHOLE"]):
                    virtual_device = dev
                    logger.info(f"找到虚拟音频设备: {device_name}")
                    break
        
        if virtual_device:
            device_name = virtual_device.get('name', 'Unknown Device')
            logger.info(f"✓ 虚拟声卡设备配置成功: {device_name}")
            p.terminate()
            return virtual_device
        else:
            logger.error("="*60)
            logger.error("未找到虚拟声卡设备！")
            logger.error("虚拟声卡录制需要安装虚拟音频设备，推荐:")
            logger.error("• Windows: VB-Audio Virtual Cable")
            logger.error("• macOS: BlackHole 或 SoundFlower")
            logger.error("• Linux: PulseAudio虚拟设备")
            logger.error("="*60)
            logger.info("将显示所有设备供您选择...")
            method = "4"  # 转为手动选择
    
    elif method == "3":  # 立体声混音录制
        logger.info("选择了立体声混音录制模式")
        stereo_mix_device = None
        for i, dev in enumerate(devices):
            device_name = dev.get("name", "")
            if device_name and ("立体声混音" in device_name or "STEREO MIX" in device_name.upper()):
                stereo_mix_device = dev
                logger.info(f"找到立体声混音设备: {device_name}")
                break
        
        if stereo_mix_device:
            device_name = stereo_mix_device.get('name', 'Unknown Device')
            logger.info(f"✓ 立体声混音设备配置成功: {device_name}")
            p.terminate()
            return stereo_mix_device
        else:
            logger.warning("未找到立体声混音设备，请在Windows声音设置中启用立体声混音")
            logger.info("将显示所有设备供您选择...")
            method = "4"  # 转为手动选择
    
    # 手动选择设备 (method == "4" 或上述方法失败时)
    if method == "4":
        logger.info("="*60)
        logger.info("所有可用的音频输入设备:")
        for i, dev in enumerate(devices):
            device_name = dev.get('name', 'Unknown Device')
            max_input_channels = dev.get("maxInputChannels", 0)
            logger.info(f"{i}: {device_name} (输入通道: {max_input_channels})")
        logger.info("="*60)
        
        while True:
            selection = input(f"请输入设备编号 (0-{len(devices)-1}): ").strip()
            try:
                index = int(selection)
                if 0 <= index < len(devices):
                    selected_device = devices[index]
                    device_name = selected_device.get('name', 'Unknown Device')
                    logger.info(f"已选择设备: {device_name}")
                    logger.info(f"✓ 手动选择设备配置成功: {device_name}")
                    p.terminate()
                    return selected_device
                else:
                    logger.warning(f"无效编号，请输入0到{len(devices)-1}之间的数字")
            except ValueError:
                logger.warning("请输入有效的数字")
    
    # 如果所有方法都失败，使用第一个设备
    logger.info("使用第一个可用设备作为默认选择")
    default_device = devices[0]
    device_name = default_device.get('name', 'Unknown Device')
    logger.info(f"使用设备: {device_name}")
    logger.info(f"✓ 默认设备配置成功: {device_name}")
    p.terminate()
    return default_device

def record_audio(duration, output_file, device):
    """录制系统音频 - 简化稳定版本"""
    if not device:
        logger.error("未提供音频设备")
        return False
    
    # 使用配置的音频参数以优化文件大小
    quality_config = AUDIO_QUALITY[SELECTED_QUALITY]
    FORMAT = quality_config["format"]
    CHANNELS = quality_config["channels"]
    RATE = quality_config["rate"]
    CHUNK = 1024
    DEVICE_INDEX = int(device.get("index", 0))
    
    device_name = device.get('name', 'Unknown Device')
    logger.info(f"使用设备: {device_name}")
    logger.info(f"音频质量: {SELECTED_QUALITY} (采样率: {RATE}Hz, 声道: {CHANNELS}, 格式: {'16位' if FORMAT == pyaudio.paInt16 else '8位'})")
    logger.info(f"开始录制音频，时长: {duration:.2f}秒...")
    
    p = pyaudio.PyAudio()
    stream = None
    stream_opened = False  # 状态标志：记录流是否真正成功打开
    
    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=DEVICE_INDEX,
            frames_per_buffer=CHUNK
        )
        stream_opened = True  # 只有在成功打开后才设置为True
        
        frames = []
        start_time = time.time()
        
        # 动态计算录制时长
        while time.time() - start_time < duration:
            try:
                data = stream.read(CHUNK)
                frames.append(data)
            except IOError as e:
                # 处理缓冲区溢出
                if e.errno == pyaudio.paInputOverflowed:
                    frames.append(b'\x00' * CHUNK * CHANNELS * 2)  # 静音填充
                else:
                    raise
        
        # 保存录音
        wf = wave.open(output_file, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        logger.info(f"录音完成，保存到: {output_file}")
        return True
    
    except Exception as e:
        logger.error(f"录音出错: {str(e)}")
        return False
    finally:
        # 严谨的资源清理：只对真正成功打开的流进行操作
        if stream and stream_opened:
            try:
                stream.stop_stream()
                stream.close()
                logger.debug("音频流已安全关闭")
            except Exception as cleanup_error:
                logger.warning(f"关闭音频流时出错: {str(cleanup_error)}")
        elif stream and not stream_opened:
            logger.debug("跳过未成功打开的音频流清理")
        
        try:
            p.terminate()
            logger.debug("PyAudio已终止")
        except Exception as terminate_error:
            logger.warning(f"终止PyAudio时出错: {str(terminate_error)}")

# 更新登录提示函数
def manual_login_prompt():
    """提示用户手动登录QQ音乐"""
    global driver
    
    if driver is None:
        logger.error("浏览器驱动未初始化")
        return
    
    logger.info("="*60)
    logger.info("请手动登录QQ音乐")
    logger.info("1. 浏览器已打开，请切换到QQ音乐标签页")
    logger.info("2. 登录您的VIP账户")
    logger.info("3. 登录完成后，在此窗口按回车键继续")
    
    # 导航到QQ音乐主页
    driver.get("https://y.qq.com")
    
    # 等待用户操作
    input("按回车键继续...")
    logger.info("继续录制流程...")

def check_debug_port():
    """检查调试端口是否可用"""
    try:
        response = requests.get(f"http://localhost:{DEBUG_PORT}/json/version", timeout=5)
        if response.status_code == 200:
            logger.info(f"调试端口 {DEBUG_PORT} 可用")
            return True
    except requests.ConnectionError:
        logger.error(f"无法连接到调试端口 {DEBUG_PORT}")
    except Exception as e:
        logger.error(f"检查调试端口时出错: {str(e)}")
    return False

def find_browser_binary():
    """查找可用的浏览器二进制文件"""
    for path in BROWSER_BINARY_PATHS:
        if os.path.exists(path):
            logger.info(f"找到浏览器: {path}")
            return path
    return None

def launch_browser_with_debug():
    """启动带有调试端口的浏览器（跨平台支持）"""
    global browser_process
    
    browser_name = "Chrome" if BROWSER_TYPE == "chrome" else "Edge"
    logger.info(f"尝试启动{browser_name}浏览器...")
    
    # 检查浏览器是否已运行
    process_names = ['chrome', 'chromium'] if BROWSER_TYPE == "chrome" else ['msedge', 'edge']
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            proc_name = proc.name().lower()
            if any(name in proc_name for name in process_names):
                cmdline = ' '.join(proc.cmdline())
                if f'--remote-debugging-port={DEBUG_PORT}' in cmdline:
                    logger.info("浏览器已在运行，无需重新启动")
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # 查找浏览器二进制文件
    browser_binary = find_browser_binary()
    if not browser_binary:
        logger.error(f"未找到{browser_name}浏览器")
        return False
        
    # 启动浏览器
    try:
        # 创建用户数据目录
        profile_dir = os.path.join(os.getcwd(), f'{BROWSER_TYPE}_profile_qqmusic')
        os.makedirs(profile_dir, exist_ok=True)
        
        cmd = [
            browser_binary,
            f"--remote-debugging-port={DEBUG_PORT}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}"
        ]
        
        # 平台特定的启动参数
        if SYSTEM == "Windows":
            browser_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:  # macOS and Linux
            browser_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        
        logger.info(f"{browser_name}浏览器已启动")
        time.sleep(5)  # 等待浏览器启动
        return True
    except Exception as e:
        logger.error(f"启动浏览器失败: {str(e)}")
        return False

def attach_to_browser():
    """附加到浏览器实例（跨平台支持）"""
    global driver
    
    try:
        # 确保端口可用
        if not check_debug_port():
            if not launch_browser_with_debug():
                return None
        
        if BROWSER_TYPE == "edge":
            # 配置Edge选项
            options = EdgeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-infobars")
            options.add_argument("--start-maximized")
            
            # 使用webdriver-manager自动管理驱动
            try:
                driver_path = EdgeChromiumDriverManager().install()
            except Exception as e:
                logger.error(f"无法获取Edge驱动: {str(e)}")
                return None
            
            # 创建服务和驱动
            service = EdgeService(driver_path)
            driver = webdriver.Edge(service=service, options=options)
            
        else:  # chrome
            # 配置Chrome选项
            options = ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-infobars")
            options.add_argument("--start-maximized")
            options.add_argument("--no-sandbox")  # 对Linux/macOS有帮助
            options.add_argument("--disable-dev-shm-usage")
            
            # 使用webdriver-manager自动管理驱动
            try:
                driver_path = ChromeDriverManager().install()
            except Exception as e:
                logger.error(f"无法获取Chrome驱动: {str(e)}")
                return None
            
            # 创建服务和驱动
            service = ChromeService(driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        
        # 验证连接
        driver.get("https://www.qq.com")
        logger.info(f"当前页面标题: {driver.title}")
        logger.info(f"成功附加到{BROWSER_TYPE.title()}浏览器")
        return driver
        
    except Exception as e:
        logger.error(f"附加到浏览器失败: {str(e)}")
        return None

def qqmusic_recorder(song_id, selected_device, player_window_handle=None, is_first_song=False):
    """QQ音乐录制主函数 - 防爬+同步录制版（页面刷新对策+播放录制并发）"""
    global driver
    
    if driver is None:
        logger.error("浏览器驱动未初始化")
        return None
    
    try:
        # 获取歌曲信息
        song_name = get_song_info(driver, song_id)
        if not song_name:
            logger.error("无法获取歌曲信息")
            return
        
        # 生成输出文件名（包含质量信息）
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # 清理文件名中的非法字符
        safe_song_name = re.sub(r'[\\/*?:"<>|]', "", str(song_name))
        output_file = os.path.join(OUTPUT_DIR, f"{safe_song_name}_{SELECTED_QUALITY}_{timestamp}.wav")
        
        # 显示当前录制配置（只在第一首歌或用户要求时显示详细信息）
        logger.info("="*60)
        logger.info(f"准备录制歌曲: {song_name}")
        logger.info("="*60)
        
        if is_first_song:
            # 只在第一首歌时显示详细的设备配置信息
            device_name = selected_device.get('name', 'Unknown Device')
            device_index = selected_device.get('index', 0)
            max_input_channels = selected_device.get('maxInputChannels', 0)
            
            logger.info("使用预配置的音频设备:")
            logger.info(f"• 设备名称: {device_name}")
            logger.info(f"• 设备索引: {device_index}")
            logger.info(f"• 输入通道: {max_input_channels}")
            logger.info(f"• 录制质量: {SELECTED_QUALITY} ({AUDIO_QUALITY[SELECTED_QUALITY]['rate']}Hz)")
            logger.info("="*60)
            
            # 给用户一点时间查看配置信息
            logger.info("设备配置确认，3秒后开始播放歌曲...")
            time.sleep(3)
        else:
            # 后续歌曲只显示简要信息
            device_name = selected_device.get('name', 'Unknown Device')
            logger.info(f"使用设备: {device_name} | 质量: {SELECTED_QUALITY}")
            logger.info("="*60)
            time.sleep(1)  # 短暂等待
        
        logger.info("步骤1: 点击加载歌曲到播放器...")
        
        # 根据是否已有播放器窗口来决定加载策略
        if player_window_handle:
            logger.info("检测到已保存的播放器窗口，使用直接URL加载方式...")
            load_success, new_player_handle = load_song_to_player_with_existing_window(driver, player_window_handle, song_id)
            # 如果使用已存在窗口失败，尝试寻找新窗口
            if not load_success:
                logger.warning("使用已存在播放器窗口失败，尝试寻找新窗口...")
                load_success, new_player_handle = load_song_to_player(driver)
            
            # 更新播放器窗口句柄（可能是原有的，也可能是新找到的）
            if new_player_handle:
                player_window_handle = new_player_handle
        else:
            logger.info("首次录制，寻找新的播放器窗口...")
            load_success, player_window_handle = load_song_to_player(driver)
        
        if not load_success:
            logger.error("加载歌曲到播放器失败，跳过当前歌曲")
            return player_window_handle
        
        logger.info("步骤2: 确认和切换到播放器窗口...")
        
        # 确保我们在正确的窗口上（播放器窗口）
        if player_window_handle:
            try:
                driver.switch_to.window(player_window_handle)
                logger.info("切换到已保存的播放器窗口")
                
                # 立即确认是否为播放器窗口
                if is_player_window(driver):
                    logger.info("播放器窗口确认成功！")
                else:
                    logger.warning("已保存的窗口不再是播放器窗口")
                    
            except Exception as e:
                logger.warning(f"切换到播放器窗口失败: {str(e)}")
                # 尝试备用方案：切换到最后一个窗口
                try:
                    handles = driver.window_handles
                    driver.switch_to.window(handles[-1])
                    logger.info("使用备用方案切换到最后一个窗口")
                    
                    # 确认备用窗口
                    if is_player_window(driver):
                        logger.info("备用窗口确认为播放器窗口！")
                    else:
                        logger.warning("备用窗口也不是播放器窗口")
                        
                except Exception as e2:
                    logger.error(f"备用窗口切换方案也失败: {str(e2)}")
        else:
            logger.info("在当前窗口继续操作")
            
            # 确认当前窗口是否为播放器窗口
            if is_player_window(driver):
                logger.info("当前窗口确认为播放器窗口！")
            else:
                logger.warning("当前窗口不是播放器窗口")
        
        logger.info("步骤3: 获取歌曲播放时长...")
        duration_seconds = get_song_duration(driver)
        if duration_seconds is None:
            duration_seconds = 180
        
        logger.info("步骤4: 优先处理自动播放弹窗（最关键步骤）...")
        
        # 优先处理自动播放弹窗（原则三：这是解锁后续所有操作的前提）
        popup_handled = handle_autoplay_popup(driver)
        if not popup_handled:
            logger.warning("自动播放弹窗处理失败，但将继续录制流程")
        else:
            logger.info("自动播放弹窗处理成功，解锁后续操作")
        
        # 额外的缓冲等待：确保弹窗处理完全完成
        logger.info("等待页面完全稳定后再进行播放状态检查...")
        time.sleep(2)  # 弹窗处理和播放检查之间的缓冲时间
        
        logger.info("步骤5: 检查播放状态并确保开始播放（双重保险）...")
        
        # 在处理完弹窗后，调用ensure_playback_starts作为双重保险（原则四）
        playback_started = ensure_playback_starts(driver)
        if not playback_started:
            logger.warning("无法确保播放开始，但将继续录制流程")
        else:
            logger.info("播放状态确认成功，音频流已开始")
        
        logger.info(f"歌曲时长: {duration_seconds}秒")
        
        logger.info("步骤6: 智能播放控制 - 暂停→归零→播放 三步走...")
        
        # 第一步：确保播放器暂停状态
        logger.info("6.1 确保播放器处于暂停状态...")
        pause_success = ensure_playback_paused(driver)
        if pause_success:
            logger.info("✅ 播放器已暂停")
        else:
            logger.warning("⚠️ 无法确认暂停状态，但继续流程")
        
        # 第二步：拖动进度条到开头（暂停状态下不会自动播放）
        logger.info("6.2 拖动进度条归零...")
        reset_success = reset_playback_to_start(driver)
        if reset_success:
            logger.info("✅ 进度条已重置到00:00")
        else:
            logger.warning("⚠️ 进度条重置失败，但继续流程")
        
        logger.info("步骤7: 播放+录制同步启动（真正零延时）...")
        
        # 高效录制函数：与播放按钮同时启动
        def synchronized_recording_thread():
            logger.info("🎵 录制线程已准备，等待播放同步信号...")
            if record_audio(duration_seconds + 1, output_file, selected_device):
                logger.info("同步录制成功完成")
            else:
                logger.error("同步录制失败")
        
        # 第一步：启动录制线程（准备状态）
        logger.info("7.1 启动录制线程...")
        rec_thread = threading.Thread(target=synchronized_recording_thread)
        rec_thread.start()
        
        # 第二步：短暂延时确保录制线程已启动
        time.sleep(0.2)  # 200ms确保录制线程准备就绪
        
        # 第三步：点击播放按钮（与录制几乎同时）
        logger.info("7.2 点击播放按钮（与录制同步）...")
        play_success = ensure_playback_starts(driver)
        if play_success:
            logger.info("✅ 播放+录制同步启动成功")
        else:
            logger.warning("⚠️ 播放启动失败，可能遇到防爬机制，尝试页面刷新...")
            
            # 防爬机制应急处理：刷新页面重试
            try:
                logger.info("执行应急防爬对策：刷新页面重置状态...")
                driver.refresh()
                
                # 等待页面重新加载
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                
                # 重新尝试播放
                logger.info("页面刷新完成，重新尝试播放...")
                retry_play_success = ensure_playback_starts(driver)
                if retry_play_success:
                    logger.info("✅ 刷新后播放启动成功")
                else:
                    logger.warning("⚠️ 刷新后仍无法播放，继续录制流程")
                    
            except Exception as refresh_error:
                logger.warning(f"页面刷新重试失败: {str(refresh_error)}")
                logger.warning("将继续当前录制流程")
        
        # 等待录音完成
        logger.info("等待录制完成...")
        rec_thread.join()
        
        # 检查录制文件
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            file_size_mb = file_size / (1024 * 1024)
            logger.info(f"歌曲录制完成: {song_name}")
            logger.info(f"文件保存至: {output_file}")
            logger.info(f"文件大小: {file_size_mb:.2f} MB")
        else:
            logger.error(f"录制文件未找到: {output_file}")
        
        # 返回播放器窗口句柄供下次使用
        return player_window_handle
        
    except Exception as e:
        logger.error(f"录制过程中出错: {str(e)}")
        if driver:
            driver.save_screenshot("qq_recording_error.png")
        # 即使出错也返回播放器窗口句柄，可能下次还能用
        return player_window_handle
    finally:
        try:
            # 不要关闭浏览器，因为用户可能希望继续使用
            logger.info("录制完成，浏览器保持打开状态")
        except:
            pass

def cleanup():
    """清理资源"""
    global driver, browser_process
    
    try:
        if driver:
            driver.quit()
            logger.info("浏览器已关闭")
    except:
        pass
    
    try:
        if browser_process:
            browser_process.terminate()
            logger.info("浏览器进程已终止")
    except:
        pass

def load_config():
    """加载配置文件"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"已加载配置文件: {CONFIG_FILE}")
                return config
    except Exception as e:
        logger.warning(f"加载配置文件失败: {str(e)}")
    return {}

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"配置已保存到: {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")

def select_audio_quality():
    """让用户选择音频质量"""
    global SELECTED_QUALITY
    
    # 加载配置
    config = load_config()
    saved_quality = config.get('audio_quality', None)
    
    logger.info("="*60)
    logger.info("选择音频质量:")
    logger.info("1. 高质量 (44.1kHz, 立体声, 16位) - 文件最大")
    logger.info("2. 中等质量 (22.05kHz, 单声道, 16位) - 文件大小减少约75%")
    logger.info("3. 低质量 (11.025kHz, 单声道, 8位) - 文件最小")
    
    if saved_quality:
        quality_names = {"high": "高质量", "medium": "中等质量", "low": "低质量"}
        logger.info(f"上次选择: {quality_names.get(saved_quality, saved_quality)}")
    
    logger.info("="*60)
    
    quality_map = {"1": "high", "2": "medium", "3": "low"}
    
    while True:
        if saved_quality:
            choice = input("请选择音频质量 (1-3, 直接回车使用上次选择): ").strip()
            if not choice:
                SELECTED_QUALITY = saved_quality
                logger.info(f"使用上次选择: {saved_quality}")
                break
        else:
            choice = input("请选择音频质量 (1-3, 默认为2): ").strip()
            if not choice:
                choice = "2"  # 默认中等质量
        
        if choice in quality_map:
            SELECTED_QUALITY = quality_map[choice]
            config['audio_quality'] = SELECTED_QUALITY
            save_config(config)
            break
        else:
            logger.warning("无效选择，请输入1、2或3")
    
    audio_config = AUDIO_QUALITY[SELECTED_QUALITY]
    logger.info(f"已选择: {SELECTED_QUALITY}质量 (采样率: {audio_config['rate']}Hz, 声道: {audio_config['channels']}, 位深: {'16位' if audio_config['format'] == pyaudio.paInt16 else '8位'})")

def main():
    """主程序"""
    global driver
    
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    logger.info("="*60)
    logger.info("QQ音乐VIP歌曲录制系统 (防爬+同步录制版)")
    logger.info("="*60)
    logger.info(f"检测到操作系统: {SYSTEM}")
    logger.info(f"将使用浏览器: {BROWSER_TYPE.title()}")
    
    # 检查浏览器是否可用
    browser_binary = find_browser_binary()
    if not browser_binary:
        logger.error(f"未找到{BROWSER_TYPE.title()}浏览器，请确保已安装")
        logger.info("支持的浏览器路径:")
        for path in BROWSER_BINARY_PATHS:
            logger.info(f"  - {path}")
        return
    
    logger.info(f"使用浏览器路径: {browser_binary}")
    
    # 检查是否存在配置文件
    config = load_config()
    if config:
        logger.info("\n" + "="*60)
        logger.info("检测到已保存的配置")
        logger.info("="*60)
        if 'audio_quality' in config:
            quality_names = {"high": "高质量", "medium": "中等质量", "low": "低质量"}
            logger.info(f"音频质量: {quality_names.get(config['audio_quality'], config['audio_quality'])}")
        if 'recording_method' in config:
            method_names = {
                "1": "系统声卡录制",
                "2": "虚拟声卡录制", 
                "3": "立体声混音录制",
                "4": "手动选择设备"
            }
            logger.info(f"录制方式: {method_names.get(config['recording_method'], config['recording_method'])}")
        
        logger.info("="*60)
        reset_config = input("是否重新配置所有设置？(y/n, 默认n): ").strip().lower()
        if reset_config == 'y':
            logger.info("将重新配置所有设置...")
            # 清空配置
            config = {}
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
                logger.info("已清除原有配置")
        else:
            logger.info("将使用保存的配置（可在选择时修改）")
    
    # 选择音频质量
    select_audio_quality()
    
    # 附加到浏览器
    driver = attach_to_browser()
    if not driver:
        logger.error("无法附加到浏览器，程序退出")
        return
    
    # 提示用户手动登录
    manual_login_prompt()
    
    # 在录制前统一配置音频设备
    logger.info("\n" + "="*60)
    logger.info("配置音频录制设备（此配置将用于所有歌曲）")
    logger.info("="*60)
    
    selected_device = select_audio_device()
    if not selected_device:
        logger.error("音频设备选择失败，程序退出")
        return
    
    device_name = selected_device.get('name', 'Unknown Device')
    device_index = selected_device.get('index', 0)
    max_input_channels = selected_device.get('maxInputChannels', 0)
    
    logger.info("\n音频设备配置完成!")
    logger.info(f"• 设备名称: {device_name}")
    logger.info(f"• 设备索引: {device_index}")
    logger.info(f"• 输入通道: {max_input_channels}")
    logger.info(f"• 录制质量: {SELECTED_QUALITY} ({AUDIO_QUALITY[SELECTED_QUALITY]['rate']}Hz)")
    logger.info("该配置将用于录制所有歌曲")
    
    # 询问用户是否要为每首歌重新配置设备
    logger.info("="*60)
    reconfigure_choice = input("是否希望为每首歌重新选择设备？(y/n, 默认n): ").strip().lower()
    reconfigure_each_song = reconfigure_choice == 'y'
    
    if reconfigure_each_song:
        logger.info("将为每首歌单独选择录制设备")
    else:
        logger.info("将使用相同配置录制所有歌曲")
    
    # 创建"记忆"变量来保存播放器窗口句柄
    memory_player_window_handle = None
    logger.info("创建播放器窗口记忆变量...")
    
    # 开始录制
    start_time = time.time()
    
    # 可以录制多首歌曲
    song_ids = [
        "000aoWC10Pn1cw",
        "0039MnYb0qxYhV"
    ]
    
    for idx, song_id in enumerate(song_ids):
        logger.info(f"\n开始录制第 {idx+1}/{len(song_ids)} 首歌曲 (ID: {song_id})")
        
        # 显示录制进度
        progress = f"[{idx+1}/{len(song_ids)}]"
        logger.info(f"{progress} 当前进度: {((idx+1)/len(song_ids)*100):.1f}%")
        logger.info("7步同步录制流程（智能控制+防爬对策+播放录制并发）：")
        
        # 显示播放器窗口记忆状态
        if memory_player_window_handle:
            logger.info(f"记忆状态: 已保存播放器窗口 (第{idx}首后获得)")
        else:
            logger.info("记忆状态: 首次录制，将寻找新的播放器窗口")
        
        # 如果用户选择为每首歌重新配置，则重新选择设备
        if reconfigure_each_song and idx > 0:
            logger.info("重新选择音频设备...")
            new_device = select_audio_device()
            if new_device:
                selected_device = new_device
                device_name = selected_device.get('name', 'Unknown Device')
                logger.info(f"设备已更换为: {device_name}")
            else:
                logger.warning("设备选择失败，继续使用之前的设备")
        
        # 传递记忆的播放器窗口句柄，并接收更新后的句柄
        memory_player_window_handle = qqmusic_recorder(
            song_id, 
            selected_device, 
            player_window_handle=memory_player_window_handle,
            is_first_song=(idx == 0)
        )
        
        # 记录播放器窗口记忆状态更新
        if memory_player_window_handle:
            logger.info(f"记忆更新: 播放器窗口句柄已保存，后续录制将直接使用")
        else:
            logger.warning("记忆更新: 未获得播放器窗口句柄")
        
        if idx < len(song_ids) - 1:  # 不是最后一首歌
            logger.info(f"歌曲 {idx+1} 录制完成，等待3秒后录制下一首...")
            time.sleep(3)  # 歌曲间间隔
        else:
            logger.info(f"最后一首歌曲录制完成！")
    
    elapsed = time.time() - start_time
    logger.info(f"\n所有歌曲录制完成，总耗时: {elapsed:.2f}秒")
    
    # 显示录制总结
    logger.info("\n" + "="*60)
    logger.info("录制任务总结")
    logger.info("="*60)
    logger.info(f"录制歌曲数量: {len(song_ids)}")
    logger.info(f"使用设备: {device_name}")
    logger.info(f"音频质量: {SELECTED_QUALITY} ({AUDIO_QUALITY[SELECTED_QUALITY]['rate']}Hz)")
    logger.info(f"输出目录: {OUTPUT_DIR}")
    logger.info(f"总耗时: {elapsed:.2f}秒")
    
    # 显示播放器窗口记忆使用情况
    if memory_player_window_handle:
        logger.info("播放器窗口记忆: 成功保存并复用，提升了录制效率")
    else:
        logger.info("播放器窗口记忆: 未能保存，每首歌都需要重新寻找窗口")
    
    logger.info("="*60)
    
    # 询问用户是否关闭浏览器
    close_browser = input("是否关闭浏览器？(y/n): ").strip().lower()
    if close_browser == 'y':
        cleanup()
    else:
        logger.info("浏览器保持打开状态")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
        cleanup()
    except Exception as e:
        logger.error(f"程序运行出错: {str(e)}")
        cleanup()