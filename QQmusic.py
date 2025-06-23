import os
import time
import threading
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging
import re
import sys
import psutil
import requests
import subprocess
import pyaudio
import wave
from webdriver_manager.microsoft import EdgeChromiumDriverManager

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
EDGE_BINARY_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# 全局变量
driver = None
browser_process = None
recording_started = threading.Event()

def setup_virtual_audio():
    """设置虚拟音频设备（Windows）"""
    logger.info("请确保已安装VB-Audio Virtual Cable并设置默认输出设备")
    try:
        # 获取所有音频设备
        devices = sd.query_devices()
        logger.info("可用的音频设备:")
        for i, device in enumerate(devices):
            logger.info(f"{i}: {device['name']} - 输入通道: {device['max_input_channels']}")
        
        # 尝试找到虚拟音频设备
        for device in devices:
            if "vb-audio" in device['name'].lower() or "virtual" in device['name'].lower():
                logger.info(f"使用虚拟音频设备: {device['name']}")
                return device['name']
        
        # 尝试找到立体声混音设备
        for device in devices:
            if "立体声混音" in device['name'] or "Stereo Mix" in device['name']:
                logger.info(f"使用立体声混音设备: {device['name']}")
                return device['name']
        
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
        return None, 180

def play_qq_song(driver):
    """播放QQ音乐歌曲 - 针对新页面结构"""
    logger.info("开始播放歌曲...")
    try:
        buttons = driver.find_elements(By.CLASS_NAME, "mod_btn_green")
        for btn in buttons:
            try:
                text_span = btn.find_element(By.CLASS_NAME, "btn__txt")
                if text_span.text.strip() == "播放":
                    btn.click()
                    logger.info("点击播放按钮成功")
                    return True
                    break
            except Exception as e:
                continue
    except Exception as e:
        logger.error(f"播放歌曲失败: {str(e)}")
        driver.save_screenshot(f"qq_play_error_{time.strftime('%H%M%S')}.png")
        return False
    
def get_song_duration(driver):
    logger.info("开始获取播放长度...")
    try:
        time_div = driver.find_element(By.CLASS_NAME, "player_music__time")
        all_texts = time_div.text.strip().split(" / ")
        logger.info(len(all_texts))
        if len(all_texts) >= 2:
            duration = all_texts[1].strip()
            minutes, seconds = map(int, duration.split(":"))
            duration_seconds = minutes * 60 + seconds
            logger.info(f"获取到的播放长度: {duration_seconds} 秒")
            return duration_seconds
    except Exception as e:
        logger.error(f"获取播放长度失败: {str(e)}")
        driver.save_screenshot(f"qq_duration_error_{time.strftime('%H%M%S')}.png")
        return 180

def close_popups(driver):
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, ".mod_btn_green.mod_btn")
        for btn in buttons:
            if btn.text.strip() == "开始播放":
                btn.click()
                logger.info("点击了‘开始播放’按钮")
                return
        logger.warning("未找到‘开始播放’按钮")
    except Exception as e:
        logger.error(f"关闭弹窗失败: {str(e)}")

# 更新音频设备选择逻辑
def select_audio_device():
    """交互式选择音频设备"""
    logger.info("请选择录音设备:")
    
    p = pyaudio.PyAudio()
    devices = []
    
    # 列出所有输入设备
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        if dev_info["maxInputChannels"] > 0:
            devices.append(dev_info)
            logger.info(f"{len(devices)-1}: {dev_info['name']} (输入通道: {dev_info['maxInputChannels']})")
    
    if not devices:
        logger.error("未找到可用的输入设备")
        return None
    
    # 自动选择推荐设备
    recommended = None
    for i, dev in enumerate(devices):
        if "立体声混音" in dev["name"] or "Stereo Mix" in dev["name"]:
            recommended = i
            break
        if "CABLE" in dev["name"] and "VB" in dev["name"]:
            recommended = i
            break
    
    if recommended is not None:
        logger.info(f"推荐设备: {devices[recommended]['name']} (自动选择)")
        return devices[recommended]
    
    # 手动选择
    selection = input(f"请输入设备编号 (0-{len(devices)-1}): ")
    try:
        index = int(selection)
        if 0 <= index < len(devices):
            return devices[index]
    except:
        pass
    
    logger.info("使用默认设备")
    return devices[0]

# 更新录制函数
def record_audio(duration, output_file):
    """录制系统音频 - 交互式设备选择"""
    # 选择设备
    device = select_audio_device()
    if not device:
        return False
    
    # 音频参数
    FORMAT = pyaudio.paInt16
    CHANNELS = device["maxInputChannels"] if device["maxInputChannels"] <= 2 else 2
    RATE = 44100
    CHUNK = 1024
    DEVICE_INDEX = device["index"]
    
    logger.info(f"使用设备: {device['name']}")
    logger.info(f"开始录制音频，时长: {duration:.2f}秒...")
    
    p = pyaudio.PyAudio()
    stream = None
    
    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=DEVICE_INDEX,
            frames_per_buffer=CHUNK
        )
        
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
        if stream:
            stream.stop_stream()
            stream.close()
        p.terminate()

# 更新登录提示函数
def manual_login_prompt():
    """增强版登录提示"""
    global driver
    
    logger.info("="*60)
    logger.info("请手动登录QQ音乐")
    logger.info("重要提示:")
    logger.info("1. 确保使用VIP账号登录")
    logger.info("2. 登录完成后请留在当前页面")
    logger.info("3. 如果看到'VIP试听'提示，请关闭弹窗")
    logger.info("4. 按回车键继续录制")
    logger.info("="*60)
    
    # 导航到QQ音乐并打开目标歌曲
    driver.get(f"https://y.qq.com/n/ryqq/songDetail/{SONG_ID}")
    
    # 等待页面加载
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".data__name_txt"))
    )
    
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

def launch_browser_with_debug():
    """启动带有调试端口的浏览器"""
    global browser_process
    
    logger.info("尝试启动Edge浏览器...")
    
    # 检查浏览器是否已运行
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if 'msedge' in proc.name().lower() and f'--remote-debugging-port={DEBUG_PORT}' in ' '.join(proc.cmdline()):
                logger.info("浏览器已在运行，无需重新启动")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # 启动浏览器
    try:
        if not os.path.exists(EDGE_BINARY_PATH):
            logger.error(f"Edge浏览器路径不存在: {EDGE_BINARY_PATH}")
            return False
        
        # 创建用户数据目录
        profile_dir = os.path.join(os.getcwd(), 'edge_profile_qqmusic')
        os.makedirs(profile_dir, exist_ok=True)
        
        cmd = [
            EDGE_BINARY_PATH,
            f"--remote-debugging-port={DEBUG_PORT}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}"
        ]
        
        # 启动浏览器进程
        browser_process = subprocess.Popen(
            cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        logger.info("Edge浏览器已启动")
        time.sleep(5)  # 等待浏览器启动
        return True
    except Exception as e:
        logger.error(f"启动浏览器失败: {str(e)}")
        return False

def attach_to_browser():
    """附加到浏览器实例"""
    global driver
    
    try:
        # 确保端口可用
        if not check_debug_port():
            if not launch_browser_with_debug():
                return None
        
        # 配置Edge选项
        edge_options = Options()
        edge_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
        edge_options.add_argument("--disable-blink-features=AutomationControlled")
        edge_options.add_argument("--disable-infobars")
        edge_options.add_argument("--start-maximized")
        
        # 使用webdriver-manager自动管理驱动
        try:
            driver_path = EdgeChromiumDriverManager().install()
        except Exception as e:
            logger.error(f"无法获取Edge驱动: {str(e)}")
            return None
        
        # 创建服务
        service = Service(driver_path)
        
        # 创建浏览器驱动
        driver = webdriver.Edge(service=service, options=edge_options)
        
        # 验证连接
        driver.get("https://www.qq.com")
        logger.info(f"当前页面标题: {driver.title}")
        logger.info("成功附加到浏览器")
        return driver
    except Exception as e:
        logger.error(f"附加到浏览器失败: {str(e)}")
        return None

def manual_login_prompt():
    """提示用户手动登录QQ音乐"""
    global driver
    
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

def qqmusic_recorder(song_id):
    """QQ音乐录制主函数"""
    global driver, recording_started
    
    try:
        # 重置事件
        recording_started.clear()
        
        # 获取歌曲信息
        song_name = get_song_info(driver, song_id)
        if not song_name:
            logger.error("无法获取歌曲信息")
            return
        
        # 生成输出文件名
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # 清理文件名中的非法字符
        safe_song_name = re.sub(r'[\\/*?:"<>|]', "", song_name)
        output_file = os.path.join(OUTPUT_DIR, f"{safe_song_name}_{timestamp}.wav")
        
        play_qq_song(driver)
        
        time.sleep(1)
        
        handles = driver.window_handles
        driver.switch_to.window(handles[-1])
        
        duration_seconds = get_song_duration(driver)
        
        time.sleep(5)
        
        # 创建录音线程
        def recording_thread():
            logger.info("录音线程启动")
            # 增加10秒缓冲时间
            if record_audio(duration_seconds + 1, output_file):
                logger.info("录音成功")
            else:
                logger.error("录音失败")
        
        # 启动录音线程
        logger.info("启动录音线程...")
        rec_thread = threading.Thread(target=recording_thread)
        rec_thread.start()
        
        # 确保录音线程已启动
        time.sleep(1)
        
        close_popups(driver)
        
        # 等待录音完成
        rec_thread.join()
        
        logger.info(f"歌曲录制完成: {song_name}")
        
    except Exception as e:
        logger.error(f"录制过程中出错: {str(e)}")
        driver.save_screenshot("qq_recording_error.png")
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

def main():
    """主程序"""
    global driver
    
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    logger.info("="*60)
    logger.info("QQ音乐VIP歌曲录制系统")
    logger.info("="*60)
    logger.info("使用说明:")
    logger.info("1. 程序将自动启动浏览器")
    logger.info("2. 请手动登录您的QQ音乐VIP账号")
    logger.info("3. 登录完成后按回车键开始录制")
    
    # 附加到浏览器
    driver = attach_to_browser()
    if not driver:
        logger.error("无法附加到浏览器，程序退出")
        return
    
    # 提示用户手动登录
    manual_login_prompt()
    
    # 开始录制
    start_time = time.time()
    
    # 可以录制多首歌曲
    song_ids = [
        "004Z8Ihr0JIu5s",
        "0039MnYb0qxYhV"
    ]
    
    for idx, song_id in enumerate(song_ids):
        logger.info(f"\n开始录制第 {idx+1}/{len(song_ids)} 首歌曲 (ID: {song_id})")
        qqmusic_recorder(song_id)
        time.sleep(3)  # 歌曲间间隔
    
    elapsed = time.time() - start_time
    logger.info(f"\n所有歌曲录制完成，总耗时: {elapsed:.2f}秒")
    
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