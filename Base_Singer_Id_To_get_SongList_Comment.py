# -*- coding: utf-8 -*-
"""
@Project: QQ Music Scraper (Pro Version - Artist Edition)
@File:    qq_music_scraper_pro_v15_commented.py
@Author:
@Date:    2025-06-23
@Description:
    一个通过QQ音乐【歌手ID】，爬取其名下所有歌曲、评论、歌词、封面并自动生成风格标签的Python爬虫。
    本版本由歌单ID模式修改而来，核心入口变更为歌手ID，其余功能保持不变。
    【V15核心工作】: 为团队协作添加了全面、详细的中文注释，提升代码的可读性和可维护性。
"""

# --- 模块导入 ---
import requests  # 用于发送HTTP网络请求
import sqlite3  # 用于操作SQLite数据库
import time  # 用于实现程序延时，防止请求过快被封
import json  # 用于处理JSON格式的数据
import os  # 用于操作系统级别的功能，如创建目录、检查文件路径
import hashlib  # 用于计算文件的MD5值，校验文件完整性
import sys  # 用于访问系统特定的参数和功能，如此处的错误输出
import base64  # 用于解码API返回的Base64编码的歌词

# --- 全局配置 (Global Configuration) ---

# 1. 数据库和文件存储配置
DB_FILE = 'qq_music_library_final.db'  # 定义数据库文件的名称
MUSIC_STORAGE_DIR = 'qq_music_library_final'  # 定义存放音乐文件和封面的主目录
COVER_STORAGE_DIR = os.path.join(MUSIC_STORAGE_DIR, 'covers')  # 封面图片的专属子目录

# 2. 起始歌手ID列表 (STARTING_ARTIST_IDS)
# 这是爬虫的入口点。程序将依次处理这个列表中的每一个歌手。
# 团队成员可以在此列表中添加或修改歌手的'mid'。
STARTING_ARTIST_IDS = [
    "003Nz2So3XXYek",  # 陈奕迅 Eason Chan
    # "0025NhlN2yWrP4", # 周杰伦 Jay Chou (示例)
]

# 3. 伪装请求头 (Request Headers)
# 模拟浏览器发送请求，这是反爬虫策略中最基本的一步。
# 'User-Agent' 告诉服务器我们是普通用户通过浏览器访问。
# 'Referer' 告诉服务器请求是从QQ音乐官网页面跳转过来的，增加请求的“合法性”。
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Referer': 'https://y.qq.com/',
    'Content-Type': 'application/json'  # 明确告诉服务器我们发送的是JSON格式数据
}

# 4. 评论抓取配置 (Comment Fetching Settings)
COMMENTS_PER_PAGE = 25  # 每次API请求获取的评论数量
MAX_COMMENTS_PER_SONG = 200  # 每首歌最多抓取的评论总数，防止无限抓取


# --- 数据库与文件操作核心函数 (Core DB & File Functions) ---

def init_environment():
    """
    初始化程序运行环境。
    1. 检查并创建主存储目录和封面子目录，如果它们不存在。
    2. 连接或创建SQLite数据库，并执行建表语句，确保'songs'和'comments'表结构正确。
    这个函数在主程序开始时调用，确保万事俱备。
    """
    # 检查并创建目录
    if not os.path.exists(MUSIC_STORAGE_DIR):
        print(f"创建音乐存储目录: {MUSIC_STORAGE_DIR}")
        os.makedirs(MUSIC_STORAGE_DIR)
    if not os.path.exists(COVER_STORAGE_DIR):
        print(f"创建封面存储目录: {COVER_STORAGE_DIR}")
        os.makedirs(COVER_STORAGE_DIR)

    try:
        # 使用 'with' 语句连接数据库，可以确保操作结束后自动关闭连接，非常安全。
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            # --- 创建 'songs' 表 ---
            # 使用 'IF NOT EXISTS' 避免重复创建。
            # 'song_id' (即songmid) 设置为文本主键 (TEXT PRIMARY KEY)，确保唯一性。
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                song_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                album_name TEXT,
                album_mid TEXT,
                artist_names TEXT,
                cover_path TEXT,
                tags TEXT,
                lrc TEXT,
                file_path TEXT,
                file_size INTEGER,
                file_md5 TEXT
            )''')

            # --- 创建 'comments' 表 ---
            # 'song_id' 设置为外键 (FOREIGN KEY)，关联到 'songs' 表的主键。
            # 这有助于维护数据完整性，但在此脚本中主要起结构性作用。
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                comment_id TEXT PRIMARY KEY,
                song_id TEXT NOT NULL,
                user_nickname TEXT,
                content TEXT,
                liked_count INTEGER,
                comment_time INTEGER,
                FOREIGN KEY (song_id) REFERENCES songs (song_id)
            )''')

            # --- 创建索引 (Indexes) ---
            # 索引可以极大地提升查询速度，特别是对于经常用于查询条件的字段。
            # 这里为评论表的 'song_id' 和 'liked_count' 创建索引。
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_song_id ON comments (song_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_liked_count ON comments (liked_count DESC)')

            conn.commit()  # 提交事务，使建表和建索引操作生效
            print(f"数据库 '{DB_FILE}' 初始化或检查完成。")

    except sqlite3.Error as e:
        # 如果数据库操作出现任何错误，打印错误信息并退出程序。
        print(f"数据库初始化错误: {e}", file=sys.stderr)
        sys.exit(1)


def execute_db_query(query, params=(), fetch=None):
    """
    一个通用的数据库执行函数，用于简化数据库的增、删、改、查操作。
    :param query: str, 要执行的SQL语句。
    :param params: tuple, SQL语句中用于替换'?'占位符的参数。
    :param fetch: str or None, 'one'表示获取一条记录，'all'表示获取所有记录，None表示执行非查询操作（如INSERT, UPDATE）。
    :return: 查询结果或None。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch == 'one':
                return cursor.fetchone()  # 返回单条记录 (元组)
            if fetch == 'all':
                return cursor.fetchall()  # 返回所有记录 (列表，元素为元组)
            conn.commit()  # 如果不是查询操作，则提交事务
    except sqlite3.Error as e:
        print(f"数据库操作错误: {e}", file=sys.stderr)
        return None


def download_cover(song_name, song_id, cover_url):
    """
    根据给定的URL下载封面图片，并保存到 'covers' 目录。
    :param song_name: str, 歌曲名，用于构建文件名，便于识别。
    :param song_id: str, 歌曲ID，也用于构建文件名，确保唯一性。
    :param cover_url: str, 封面的完整下载地址。
    :return: 成功则返回文件本地路径，失败则返回None。
    """
    if not cover_url:
        print(f"  -> 歌曲 '{song_name}' 的封面链接为空，跳过下载。")
        return None
    try:
        # 使用 stream=True 进行流式下载，特别适合大文件，可以避免一次性将所有内容读入内存。
        response = requests.get(cover_url, headers=HEADERS, stream=True, timeout=30)
        response.raise_for_status()  # 如果请求返回错误状态码(如404, 500)，则会抛出异常。

        # 清理文件名中的非法字符，防止创建文件时出错。
        safe_song_name = "".join(i for i in song_name if i not in r'\/:*?"<>|')
        file_name = f"{safe_song_name} - {song_id}.jpg"
        file_path = os.path.join(COVER_STORAGE_DIR, file_name)

        # 以二进制写模式('wb')打开文件，并分块写入。
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  -> 成功下载封面到 {file_path}")
        return file_path
    except requests.exceptions.RequestException as e:
        print(f"  -> 下载封面 '{song_name}' 失败: {e}", file=sys.stderr)
        return None


def download_file(song_name, song_id, download_url):
    """
    根据给定的URL下载音频文件，并保存到主存储目录。
    同时计算文件的大小和MD5值。
    :param song_name: str, 歌曲名。
    :param song_id: str, 歌曲ID。
    :param download_url: str, 音频文件的完整下载地址。
    :return: 成功则返回包含路径、大小、MD5的字典，失败则返回None。
    """
    if not download_url:
        print(f"  -> 歌曲 '{song_name}' 的下载链接为空，跳过下载。")
        return None
    try:
        response = requests.get(download_url, headers=HEADERS, stream=True, timeout=60)
        response.raise_for_status()

        safe_song_name = "".join(i for i in song_name if i not in r'\/:*?"<>|')
        file_name = f"{safe_song_name} - {song_id}.m4a"
        file_path = os.path.join(MUSIC_STORAGE_DIR, file_name)

        # 使用一个字节数组来缓存下载的内容，以便后续计算MD5。
        content_buffer = bytearray()
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # 过滤掉空的chunk
                    f.write(chunk)
                    content_buffer.extend(chunk)

        # 计算文件大小和MD5
        file_size = len(content_buffer)
        file_md5 = hashlib.md5(content_buffer).hexdigest()

        print(f"  -> 成功下载歌曲 '{song_name}' 到 {file_path}")
        return {"path": file_path, "size": file_size, "md5": file_md5}
    except requests.exceptions.RequestException as e:
        print(f"  -> 下载歌曲 '{song_name}' 失败: {e}", file=sys.stderr)
        return None


# --- QQ音乐API请求函数 (QQ Music API Functions) ---

def get_artist_songs_api(artist_id):
    """
    通过歌手ID，分页获取其名下的所有歌曲列表。
    这是整个爬虫的数据来源。
    :param artist_id: str, 歌手的 mid，如陈奕迅的 '003Nz2So3XXYek'。
    :return: 成功则返回包含歌手名和歌曲列表的字典，失败则返回None。
    """
    print(f"\n正在获取歌手详情: ID={artist_id}")
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'  # QQ音乐通用数据接口
    all_songs = []  # 用于存储所有获取到的歌曲信息
    page_num = 0  # 页码，从0开始
    songs_per_page = 80  # 每次请求获取的歌曲数，80是比较稳妥的最大值
    artist_name = ""  # 存储歌手名
    total_songs_count = 0  # 存储官方记录的总歌曲数

    while True:  # 使用无限循环，直到取完所有页或发生错误
        # 这是请求体(payload)的构造，是API逆向分析的核心成果。
        # 'module' 和 'method' 告诉服务器我们要调用哪个功能。
        # 'param' 包含了具体的请求参数，如歌手ID、起始位置(begin)、数量(num)。
        req_data = {
            "comm": {"ct": 24, "cv": 0},
            "req_1": {
                "module": "musichall.song_list_server",
                "method": "GetSingerSongList",
                "param": {
                    "singerMid": artist_id,
                    "begin": page_num * songs_per_page,
                    "num": songs_per_page,
                    "order": 1  # 1: 按发布时间排序, 2: 按热度排序
                }
            }
        }
        try:
            res = requests.post(url, headers=HEADERS, data=json.dumps(req_data), timeout=20)
            res.raise_for_status()
            data = res.json()

            # 检查返回码，确保业务逻辑也成功
            if data.get('code') == 0 and data.get('req_1', {}).get('code') == 0:
                api_data = data['req_1']['data']

                # 首次成功请求时，获取歌手名和总歌曲数并打印
                if not artist_name:
                    artist_name = api_data.get('singerName', '未知歌手')
                    total_songs_count = api_data.get('totalNum', 0)
                    print(f"成功锁定歌手: '{artist_name}'，官方记录总歌曲数: {total_songs_count}")

                song_list = api_data.get('songList', [])
                if not song_list:  # 如果返回的歌曲列表为空，说明已经取完
                    print("  -> 已获取该歌手所有歌曲。")
                    break

                # 【V13修复点】直接添加 song_item，而不是错误的 song_item['musicData']
                for song_item in song_list:
                    all_songs.append(song_item)

                print(f"  -> 已获取 {len(song_list)} 首歌曲，累计: {len(all_songs)} / {total_songs_count}")
                page_num += 1  # 页码+1，准备获取下一页
                time.sleep(1)  # 礼貌性延迟，避免请求过快
            else:
                print(f"获取歌手 {artist_id} 的歌曲列表时，API返回错误: {data}", file=sys.stderr)
                break
        except Exception as e:
            print(f"获取歌手 {artist_id} 歌曲列表时出错: {e}", file=sys.stderr)
            break

    if all_songs:
        return {"artist_name": artist_name, "songs": all_songs}
    return None


def get_song_details_api(song_id):
    """
    获取单曲的详细信息，主要用于提取语种、流派等标签信息。
    :param song_id: str, 歌曲的 mid。
    :return: 成功则返回歌曲的 'track_info' 字典，失败则返回None。
    """
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
    req_data = {
        "comm": {"ct": 24, "cv": 0, "g_tk": 5381},
        "req_1": {
            "module": "music.trackInfo.TrackInfoServer",
            "method": "GetTrackInfo",
            "param": {"song_mid": song_id}
        }
    }
    try:
        res = requests.post(url, headers=HEADERS, data=json.dumps(req_data), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get('code') == 0 and data.get('req_1', {}).get('code') == 0:
            return data['req_1']['data']['track_info']
    except Exception as e:
        print(f"  -> 获取歌曲详情(ID={song_id})时出错: {e}", file=sys.stderr)
    return None


def generate_tags(playlist_info, song_details):
    """
    标签生成引擎，聚合歌单标签（已兼容移除）和歌曲自身属性（语种、流派）。
    :param playlist_info: dict or None, 歌单信息，在歌手模式下为None。
    :param song_details: dict or None, 单曲详情信息。
    :return: set, 一个包含所有提取到的标签的集合。
    """
    tags = set()  # 使用集合可以自动去重

    # 1. 从歌单信息中提取标签 (在当前歌手模式下，此部分逻辑不会执行，但保留了兼容性)
    if playlist_info and 'tags' in playlist_info and isinstance(playlist_info['tags'], list):
        for tag_item in playlist_info['tags']:
            if 'name' in tag_item:
                tags.add(tag_item['name'].strip())

    # 2. 从歌曲详情中提取语种(lan)和流派(genre)
    if song_details and 'info' in song_details and isinstance(song_details['info'], list):
        # 歌曲的详情信息存储在一个列表中，需要遍历查找
        for info_item in song_details['info']:
            # 检查是否是语种信息
            if info_item.get('name') == 'lan' and info_item.get('content'):
                for content_item in info_item.get('content', []):
                    lang_value = content_item.get('value', '')
                    for lang in lang_value.split(','):  # 有的语种可能是 "国语,粤语" 这种形式
                        if lang: tags.add(lang.strip())
            # 检查是否是流派信息
            if info_item.get('name') == 'genre' and info_item.get('content'):
                for content_item in info_item.get('content', []):
                    genre_info = content_item.get('value', '')
                    if isinstance(genre_info, str) and genre_info:
                        tags.add(genre_info.strip())

    tags.discard('')  # 清理可能产生的空标签
    return tags


def get_song_url_api(song_id):
    """
    获取歌曲的音频播放链接 (purl)。
    这是能否下载歌曲的关键。
    :param song_id: str, 歌曲的 mid。
    :return: 成功则返回完整的下载URL，失败则返回None。
    """
    vkey_url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
    # 'guid' 是一个设备标识符，可以随机生成。
    # 'purl' 是API返回的部分URL，需要和 'sip' (服务器地址)拼接才是完整链接。
    req_data = {"req_0": {"module": "vkey.GetVkeyServer", "method": "CgiGetVkey",
                          "param": {"guid": "1234567890", "songmid": [song_id], "songtype": [0], "uin": "0",
                                    "loginflag": 1, "platform": "20"}},
                "comm": {"uin": "0", "format": "json", "ct": 24, "cv": 0}}
    try:
        res = requests.post(vkey_url, headers=HEADERS, data=json.dumps(req_data), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get('code') == 0 and data.get('req_0', {}).get('code') == 0:
            mid_info = data['req_0']['data']['midurlinfo']
            if mid_info and mid_info[0]:
                purl = mid_info[0].get('purl')
                if purl:  # 只有purl存在，才能拼接下载链接
                    server_host = data['req_0']['data'].get('sip', ["http://ws.stream.qqmusic.qq.com/"])[0]
                    return server_host + purl
    except Exception as e:
        print(f"  -> 获取ID={song_id}的URL失败: {e}", file=sys.stderr)
    return None


def get_lyrics_api(song_id):
    """
    获取歌曲的歌词。
    返回的歌词是Base64编码的，需要解码。
    :param song_id: str, 歌曲的 mid。
    :return: 成功则返回UTF-8编码的歌词字符串，失败则返回None。
    """
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
    req_data = {"comm": {"ct": 24, "cv": 0, "g_tk": 5381},
                "req_lyric": {"module": "music.musichallSong.PlayLyricInfo", "method": "GetPlayLyricInfo",
                              "param": {"songMID": song_id}}}
    try:
        res = requests.post(url, headers=HEADERS, data=json.dumps(req_data), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get('code') == 0 and data.get('req_lyric', {}).get('code') == 0:
            lyric_base64 = data['req_lyric']['data'].get('lyric')
            if lyric_base64:
                # 使用 base64.b64decode 解码，再用 .decode('utf-8') 转为字符串。
                return base64.b64decode(lyric_base64).decode('utf-8')
    except Exception as e:
        print(f"  -> 获取ID={song_id}的歌词失败: {e}", file=sys.stderr)
    return None


def get_all_comments_api(song_id_num, song_id):
    """
    分页获取一首歌的所有评论，直到达到上限或没有更多评论。
    :param song_id_num: int, 歌曲的数字ID (songid)，评论API需要这个ID。
    :param song_id: str, 歌曲的文本ID (mid)，用于存入数据库。
    :return: list, 包含所有评论信息的字典列表。
    """
    print(f"    -> 开始获取歌曲 {song_id} 的评论...")
    all_comments = []
    page = 0
    while len(all_comments) < MAX_COMMENTS_PER_SONG:
        # 这是一个较旧的API，但目前依然有效。
        comment_url = 'https://c.y.qq.com/base/fcgi-bin/fcg_global_comment_h5.fcg'
        params = {'biztype': 1, 'topid': song_id_num, 'cmd': 8, 'pagenum': page, 'pagesize': COMMENTS_PER_PAGE,
                  'format': 'json', 'g_tk': 5381}
        try:
            res = requests.get(comment_url, headers=HEADERS, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get('code') == 0:
                comments = data.get('comment', {}).get('commentlist', [])
                if not comments:  # 如果返回的评论列表为空，说明没有更多了
                    print(f"    -> 已无更多评论。")
                    break
                # 整理评论数据并添加到总列表中
                for cmt in comments:
                    all_comments.append({
                        'comment_id': cmt.get('commentid'),
                        'song_id': song_id,  # 关联到我们的文本主键
                        'user_nickname': cmt.get('nick'),
                        'content': cmt.get('rootcommentcontent'),
                        'liked_count': cmt.get('praisenum'),
                        'comment_time': cmt.get('time')
                    })
                print(f"    -> 已获取 {len(comments)} 条评论，累计: {len(all_comments)}")
                page += 1
                time.sleep(0.5)
            else:
                break
        except Exception as e:
            print(f"    -> 获取评论失败: {e}", file=sys.stderr)
            break
    return all_comments


# --- 主程序逻辑 (Main Logic) ---

def main():
    """主程序执行入口，负责调度所有爬取任务。"""
    print("--- QQ音乐爬虫启动 (V15 - 歌手模式注释增强版) ---")
    init_environment()

    # 1. 遍历待处理的歌手列表
    for artist_id in STARTING_ARTIST_IDS:
        artist_data = get_artist_songs_api(artist_id)
        if not artist_data:
            print(f"跳过无法获取歌曲的歌手: {artist_id}")
            continue  # 处理下一个歌手

        song_list = artist_data.get('songs', [])
        artist_name = artist_data.get('artist_name', artist_id)
        total_songs = len(song_list)
        print(f"\n--- 开始处理歌手 '{artist_name}' 的 {total_songs} 首歌曲 ---")

        # 2. 遍历该歌手的每一首歌曲
        for index, song in enumerate(song_list):
            try:
                # --- 数据解析 ---
                # 【V14修复点】API返回的歌曲信息在外层'songInfo'中，需要先提取出来。
                song_data = song['songInfo']

                # 从解析后的数据中提取我们需要的核心字段
                song_id = song_data['mid']  # 文本ID，用作主键
                song_id_num = song_data['id']  # 数字ID，仅供评论API使用
                song_name = song_data['name']  # 歌名
                album_mid = song_data.get('album', {}).get('mid')  # 安全地获取专辑mid
                album_name = song_data.get('album', {}).get('name')
                # 将歌手列表转为JSON字符串存储
                artist_names_json = json.dumps([s.get('name') for s in song_data.get('singer', [])], ensure_ascii=False)
                # 拼接封面URL
                cover_url = f"https://y.qq.com/music/photo_new/T002R500x500M000{album_mid}.jpg" if album_mid else ""
            except KeyError as e:
                # 如果缺少关键字段，打印错误并跳过这首歌，避免程序崩溃。
                print(f"解析歌曲基础信息时缺少关键字段: {e}，跳过此歌曲。歌曲数据: {song}", file=sys.stderr)
                continue

            print(f"\n[歌手 '{artist_name}' 歌曲进度 {index + 1}/{total_songs}] 正在处理: {song_name} (ID: {song_id})")

            # 3. 检查歌曲是否已下载过，如果已下载则跳过，实现断点续传。
            existing_song = execute_db_query(
                "SELECT file_path FROM songs WHERE song_id = ? AND file_path IS NOT NULL AND file_path != ''",
                (song_id,), fetch='one'
            )
            if existing_song:
                print(f"  -> 歌曲 '{song_name}' 的文件已存在于数据库记录中，跳过处理。")
                continue

            # --- 分步执行爬取任务 ---

            # 步骤A: 预先插入歌曲基础信息
            # 使用 INSERT OR IGNORE，如果歌曲已存在，则忽略本次插入，避免主键冲突。
            execute_db_query('''
                INSERT OR IGNORE INTO songs (song_id, name, album_name, album_mid, artist_names)
                VALUES (?, ?, ?, ?, ?)
            ''', (song_id, song_name, album_name, album_mid, artist_names_json))

            # 步骤B: 处理标签（获取、聚合、更新）
            song_details = get_song_details_api(song_id)
            new_tags = generate_tags(None, song_details)  # 在歌手模式下，第一个参数传None
            tags_json = json.dumps(list(new_tags), ensure_ascii=False)
            print(f"  -> 生成标签: {list(new_tags)}")

            # 步骤C: 下载封面并更新数据库
            # 先检查数据库中是否已有封面路径
            cover_record = execute_db_query("SELECT cover_path FROM songs WHERE song_id = ?", (song_id,), fetch='one')
            if not (cover_record and cover_record[0]):
                cover_path = download_cover(song_name, song_id, cover_url)
                # 将标签和封面路径一次性更新到数据库
                execute_db_query("UPDATE songs SET tags = ?, cover_path = ? WHERE song_id = ?",
                                 (tags_json, cover_path, song_id))
            else:
                # 如果已有封面，则只更新标签
                execute_db_query("UPDATE songs SET tags = ? WHERE song_id = ?", (tags_json, song_id))

            time.sleep(0.5)

            # 步骤D: 获取并存储评论
            comments = get_all_comments_api(song_id_num, song_id)
            if comments:
                # 遍历所有获取到的评论并插入数据库
                for cmt in comments:
                    execute_db_query(
                        '''INSERT OR IGNORE INTO comments (comment_id, song_id, user_nickname, content, liked_count, comment_time) 
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        (cmt['comment_id'], cmt['song_id'], cmt['user_nickname'], cmt['content'],
                         cmt['liked_count'], cmt['comment_time'])
                    )
                print(f"  -> 已完成 {len(comments)} 条评论的增量存储。")

            # 步骤E: 获取并存储歌词
            lyrics_record = execute_db_query("SELECT lrc FROM songs WHERE song_id = ?", (song_id,), fetch='one')
            if not (lyrics_record and lyrics_record[0]):  # 检查是否已有歌词
                lyrics = get_lyrics_api(song_id)
                if lyrics:
                    execute_db_query("UPDATE songs SET lrc = ? WHERE song_id = ?", (lyrics, song_id))
                    print(f"  -> 成功获取并存储歌词。")
                else:
                    print(f"  -> 未找到该歌曲的歌词。")
            else:
                print(f"  -> 歌词已存在于数据库中，跳过获取。")

            time.sleep(0.5)

            # 步骤F: 获取下载链接并下载文件 (最核心的步骤)
            download_url = get_song_url_api(song_id)
            if download_url:
                file_info = download_file(song_name, song_id, download_url)
                if file_info:  # 下载成功后，更新数据库记录
                    execute_db_query(
                        "UPDATE songs SET file_path = ?, file_size = ?, file_md5 = ? WHERE song_id = ?",
                        (file_info['path'], file_info['size'], file_info['md5'], song_id)
                    )
            else:
                print(f"  -> 未能获取歌曲 '{song_name}' 的下载链接，标记为无法下载。")
                # 即使无法下载，也更新一下数据库记录，避免下次重复尝试。
                execute_db_query("UPDATE songs SET file_path = ? WHERE song_id = ?", ('UNAVAILABLE', song_id))

            print(f"  -> 歌曲 '{song_name}' 处理完毕，等待3秒...")
            time.sleep(3)  # 完成一首歌的全部流程后，进行较长时间的等待

    print("\n--- 所有任务处理完毕 ---")
    print(f"数据已存储在数据库文件: {DB_FILE}")
    print(f"音乐和封面文件已下载至目录: {MUSIC_STORAGE_DIR}")


# --- 程序入口 ---
if __name__ == '__main__':
    # 只有当这个脚本被直接执行时，main()函数才会被调用。
    # 如果它被其他脚本作为模块导入，则不会自动运行。
    main()
