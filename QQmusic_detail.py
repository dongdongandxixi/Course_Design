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
import pandas as pd

#df = pd.read_csv(test.csv)

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

# 全局变量
driver = None
browser_process = None


def find_browser_binary():
    """查找可用的浏览器二进制文件"""
    for path in BROWSER_BINARY_PATHS:
        if os.path.exists(path):
            logger.info(f"找到浏览器: {path}")
            return path
    return None

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

def get_playlist_info(driver, playlist_id):
    logger.info(f"获取歌单信息：ID = {playlist_id}")
    print(playlist_id)
    playlist = {
        "id" : playlist_id,
        "name" : "",
        "tags" : "",
        "description" : "",
    }
    
    try:
        time.sleep(2)
        # 导航到歌单页面
        driver.get(playlist_id)
        driver.refresh()
        
        # 等待页面加载完成
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("页面加载完成")
        
        # 等待歌单名字加载完成
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "data__name_txt"))
        )
        logger.info("歌单名字加载完成")
        playlist_name_element = driver.find_element(By.CLASS_NAME, "data__name_txt")
        playlist["name"] = playlist_name_element.text.strip()
        logger.info(f"歌单名字：{playlist["name"]}")
        
        try:
            # 等待歌曲标签加载完成
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "data_info__tags"))
            )
            logger.info("歌单标签加载完成")
            # 获取歌曲标签
            tag_elements = driver.find_elements(By.CSS_SELECTOR, ".data_info__tags")
            tags = [tag.text.strip() for tag in tag_elements]
            playlist["tags"] = " ".join(tags)
        except Exception as e:
            logger.error(f"歌单没有标签")
        
        try:
            # 等待歌曲简介加载完成
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "about__cont"))
            )
            logger.info("歌单简介加载完成")
            # 获取歌曲简介
            content_element = driver.find_element(By.CLASS_NAME, "about__cont")
            playlist["description"] = content_element.text.strip()
        except Exception as e:
            logger.error(f"歌单没有简介")
    
    except Exception as e:
        logger.error(f"获取歌单信息失败: {str(e)}")
        driver.save_screenshot(f"qq_playlist_info_error_{playlist_id}.png")
    
    return playlist
    

def get_song_info(driver, song_id):
    """获取QQ音乐歌曲信息和时长"""
    logger.info(f"获取歌曲信息和时长: ID={song_id}")
    
    song_data = {
        "id" : song_id,
        "name" : "",
        "artist": "",
        "album" : "",
        "language" : "",
        "genre" : "",
        "company" : "",
        "release_date" : "",
        "intro" : "",
        "playlist" : []
    }
    
    try:
        # 导航到歌曲页面
        driver.get(f"{MUSIC_PLATFORM_URL}/n/ryqq/songDetail/{song_id}")
        driver.refresh()
        
        # 等待页面加载完成
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("页面加载完成")
        
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".c_tx_thin.part__tit_desc"))
            )
            logger.info("歌曲评论数量已经加载完成")
            comment_num = driver.find_element(By.CSS_SELECTOR, ".c_tx_thin.part__tit_desc").text.strip()
            match_ = re.search(r'\d+', comment_num)
            if match_:
                number = match_.group()
                number_int = int(number)
            if number_int < 5000:
                logger.info("歌曲评论数量小于5000，跳过")
                return None
        except Exception as e:
            logger.error("歌曲评论数量未加载完成")
            return None
            
        # 等待歌曲名字加载
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".data__name_txt"))
        )
        
        # 等待歌手信息也加载完成
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".data__singer_txt"))
        )
        
        # 等待歌曲信息加载
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "data_info__item_song"))
        )
        logger.info("歌曲信息等内容已加载")
        
        # 获取歌曲名
        song_name_element = driver.find_element(By.CSS_SELECTOR, ".data__name_txt")
        song_data["name"] = song_name_element.text.strip()
        
        # 获取歌手名
        artist_element = driver.find_element(By.CSS_SELECTOR, ".data__singer_txt")
        song_data["artist"] = artist_element.text.strip()
        
        # 获得一些歌曲信息
        info_items = driver.find_elements(By.CSS_SELECTOR, ".data_info__item_song")
        for item in info_items:
            text_content = item.text.strip() # 获取元素的可见文本内容并去除空白 
            # 映射到对应的字段
            if "专辑" in text_content:
                song_data["album"] = text_content
            elif "语种" in text_content:
                song_data["language"] = text_content
            elif "流派" in text_content:
                song_data["genre"] = text_content
            elif "唱片公司" in text_content:
                song_data["company"] = text_content
            elif "发行时间" in text_content:
                song_data["release_date"] = text_content
        
    except Exception as e:
        logger.error(f"获取歌曲信息失败: {str(e)}")
        # 保存截图
        driver.save_screenshot(f"qq_song_info_error_{song_id}.png")
        return None
    
    try:
        # 等待歌曲简介加载
        WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "about__cont"))
        )
        # 获取歌曲简介
        about_cont_element = driver.find_element(By.CLASS_NAME, "about__cont")
        song_data["intro"] = about_cont_element.text.strip()
        logger.info("歌曲简介已加载")
    except Exception as e:
        logger.error("歌曲没有简介")
    
    try:
        # 等待歌单加载
        WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".mod_playlist"))
        )
        logger.info("歌单列表已加载")
        hrefs = driver.find_elements(By.CSS_SELECTOR, '.playlist__title_txt a')
        href_list = [href_d.get_attribute('href') for href_d in hrefs]
        logger.info("歌单链接已获取成功")
        
        # 获取歌单信息（最多3个）
        for href in href_list[:3]:
            playlist_data = get_playlist_info(driver, href)
            song_data["playlist"].append(playlist_data)
            
    except Exception as e:
        logger.warning("歌单信息不存在")
    
    time.sleep(3)
        
    return song_data

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

def main():
    """主程序"""
    global driver
    
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    all_songs_data = []
    
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
    
    # 附加到浏览器
    driver = attach_to_browser()
    if not driver:
        logger.error("无法附加到浏览器，程序退出")
        return
    
    # 提示用户手动登录
    manual_login_prompt()
    
    # 多首歌曲
    song_ids = [
        "000aoWC10Pn1cw",
        "0039MnYb0qxYhV"
    ]
    
    for idx, song_id in enumerate(song_ids):
        logger.info(f"\n开始获取第 {idx+1}/{len(song_ids)} 首歌曲 (ID: {song_id})的信息")
        
        song_data = get_song_info(driver, song_id)
        if song_data:
            all_songs_data.append(song_data)
    
    # 保存为JSON文件
    output_file = "all_songs_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_songs_data, f, ensure_ascii=False, indent=4)
    
    logger.info(f"歌曲信息已保存到: {output_file}")
    
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