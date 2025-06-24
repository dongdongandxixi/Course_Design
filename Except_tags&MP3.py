# -*- coding: utf-8 -*-
"""
@Project: QQ Music Scraper (Pro Version - Artist Edition)
@File:    qq_music_scraper_pro_v19_ceiling.py
@Author:
@Date:    2025-06-24
@Description:
    一个通过QQ音乐【歌手ID】，爬取其名下特定比例的歌曲、评论、歌词、封面并导出到Excel的Python爬虫。
    本版本根据用户需求进行修改，主要变更包括：
    1. 【V19核心工作】: 将根据权重计算待爬取歌曲数量的方式，从默认的向下取整修改为向上取整。
    2. 程序可自动检测并兼容 .xlsx 和 .csv 两种格式的输入文件。
    3. 从外部Excel/CSV文件读取歌手任务列表（包含抓取权重）。
    4. 移除了MP3音频文件的下载功能。
    5. 移除了语种、流派等标签的爬取逻辑。
    6. 新增将最终数据库结果导出为Excel表格的功能。
    7. 修复了因系统环境存在无效代理配置而导致的ProxyError问题。
"""

# --- 模块导入 ---
import requests  # 用于发送HTTP网络请求
import sqlite3  # 用于操作SQLite数据库
import time  # 用于实现程序延时，防止请求过快被封
import json  # 用于处理JSON格式的数据
import os  # 用于操作系统级别的功能，如创建目录、检查文件路径
import sys  # 用于访问系统特定的参数和功能，如此处的错误输出
import base64  # 用于解码API返回的Base64编码的歌词
import pandas as pd  # 用于读取CSV/Excel文件和导出到Excel
import math  # 新增：导入math模块以使用向上取整功能

# --- 全局配置 (Global Configuration) ---

# 1. 数据库和文件存储配置
DB_FILE = 'qq_music_library_final.db'  # 定义数据库文件的名称
MUSIC_STORAGE_DIR = 'qq_music_library_final'  # 定义存放封面等文件的总目录
COVER_STORAGE_DIR = os.path.join(MUSIC_STORAGE_DIR, 'covers')  # 封面图片的专属子目录

# 2. 输出文件配置 (输入文件配置已改为自动检测)
OUTPUT_EXCEL_FILE = 'qq_music_output.xlsx'

# 3. 伪装请求头 (Request Headers)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Referer': 'https://y.qq.com/',
    'Content-Type': 'application/json'
}

# 4. 评论抓取配置 (Comment Fetching Settings)
COMMENTS_PER_PAGE = 25  # 每次API请求获取的评论数量
MAX_COMMENTS_PER_SONG = 200  # 每首歌最多抓取的评论总数

# 5. 代理修复配置
NO_PROXY = {'http': None, 'https': None}


# --- 核心功能函数 ---

def find_input_file():
    """
    自动查找 'artists.xlsx' 或 'artists.csv' 文件。
    优先使用 .xlsx 文件。如果都找不到，则返回 None。
    """
    if os.path.exists('artists.xlsx'):
        print("检测到输入文件: artists.xlsx")
        return 'artists.xlsx'
    elif os.path.exists('artists.csv'):
        print("检测到输入文件: artists.csv")
        return 'artists.csv'
    else:
        return None


def init_environment():
    """
    初始化程序运行环境。
    """
    if not os.path.exists(MUSIC_STORAGE_DIR):
        print(f"创建主存储目录: {MUSIC_STORAGE_DIR}")
        os.makedirs(MUSIC_STORAGE_DIR)
    if not os.path.exists(COVER_STORAGE_DIR):
        print(f"创建封面存储目录: {COVER_STORAGE_DIR}")
        os.makedirs(COVER_STORAGE_DIR)

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                song_id TEXT PRIMARY KEY, name TEXT NOT NULL, album_name TEXT,
                album_mid TEXT, artist_names TEXT, cover_path TEXT, tags TEXT, lrc TEXT
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                comment_id TEXT PRIMARY KEY, song_id TEXT NOT NULL, user_nickname TEXT,
                content TEXT, liked_count INTEGER, comment_time INTEGER,
                FOREIGN KEY (song_id) REFERENCES songs (song_id)
            )''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_song_id ON comments (song_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_liked_count ON comments (liked_count DESC)')
            conn.commit()
            print(f"数据库 '{DB_FILE}' 初始化或检查完成。")
    except sqlite3.Error as e:
        print(f"数据库初始化错误: {e}", file=sys.stderr)
        sys.exit(1)


def execute_db_query(query, params=(), fetch=None):
    """
    通用的数据库执行函数。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch == 'one': return cursor.fetchone()
            if fetch == 'all': return cursor.fetchall()
            conn.commit()
    except sqlite3.Error as e:
        print(f"数据库操作错误: {e}", file=sys.stderr)
        return None


def download_cover(song_name, song_id, cover_url):
    """
    下载封面图片。
    """
    if not cover_url:
        print(f"  -> 歌曲 '{song_name}' 的封面链接为空，跳过下载。")
        return None
    try:
        response = requests.get(cover_url, headers=HEADERS, stream=True, timeout=30, proxies=NO_PROXY)
        response.raise_for_status()
        safe_song_name = "".join(i for i in song_name if i not in r'\/:*?"<>|')
        file_name = f"{safe_song_name} - {song_id}.jpg"
        file_path = os.path.join(COVER_STORAGE_DIR, file_name)
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  -> 成功下载封面到 {file_path}")
        return file_path
    except requests.exceptions.RequestException as e:
        print(f"  -> 下载封面 '{song_name}' 失败: {e}", file=sys.stderr)
        return None


def read_input_file(filepath):
    """
    从指定的CSV或Excel文件读取歌手任务列表。
    """
    try:
        if filepath.lower().endswith('.csv'):
            df = pd.read_csv(filepath, dtype={'singer_mid': str})
        else:  # .xlsx or .xls
            df = pd.read_excel(filepath, dtype={'singer_mid': str})

        if 'singer_mid' not in df.columns or 'weight' not in df.columns:
            print(f"错误：输入文件 '{filepath}' 必须包含 'singer_mid' 和 'weight' 列。", file=sys.stderr)
            sys.exit(1)

        df['weight'] = df['weight'].astype(str).str.replace('%', '', regex=False).astype(float)
        df['weight'] = df['weight'].clip(0, 1)
        print(f"成功从 '{filepath}' 读取 {len(df)} 个歌手任务。")
        return df.to_dict('records')
    except Exception as e:
        print(f"读取或解析输入文件 '{filepath}' 时出错: {e}", file=sys.stderr)
        sys.exit(1)


def export_to_excel():
    """
    将数据库内容导出到Excel文件。
    """
    print(f"\n--- 开始将数据导出到Excel文件: {OUTPUT_EXCEL_FILE} ---")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            songs_df = pd.read_sql_query("SELECT * FROM songs", conn)
            print(f"从数据库读取了 {len(songs_df)} 条歌曲记录。")
            comments_df = pd.read_sql_query("SELECT * FROM comments", conn)
            print(f"从数据库读取了 {len(comments_df)} 条评论记录。")
        with pd.ExcelWriter(OUTPUT_EXCEL_FILE, engine='openpyxl') as writer:
            songs_df.to_excel(writer, sheet_name='Songs', index=False)
            comments_df.to_excel(writer, sheet_name='Comments', index=False)
        print(f"数据成功导出！请查看文件: {OUTPUT_EXCEL_FILE}")
    except Exception as e:
        print(f"导出到Excel失败: {e}", file=sys.stderr)


# --- QQ音乐API请求函数 ---

def get_artist_songs_api(artist_id):
    """
    获取歌手的所有歌曲列表。
    """
    print(f"\n正在获取歌手详情: ID={artist_id}")
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
    all_songs, page_num, artist_name, total_songs_count = [], 0, "", 0
    songs_per_page = 80  # 每次(页)爬取歌曲数
    while True:
        req_data = {"comm": {"ct": 24, "cv": 0},
                    "req_1": {"module": "musichall.song_list_server", "method": "GetSingerSongList",
                              "param": {"singerMid": artist_id, "begin": page_num * songs_per_page,
                                        "num": songs_per_page, "order": 1}}}
        try:
            res = requests.post(url, headers=HEADERS, data=json.dumps(req_data), timeout=20, proxies=NO_PROXY)
            res.raise_for_status()
            data = res.json()
            if data.get('code') == 0 and data.get('req_1', {}).get('code') == 0:
                api_data = data['req_1']['data']
                if not artist_name:
                    artist_name = api_data.get('singerName', '未知歌手')
                    total_songs_count = api_data.get('totalNum', 0)
                    print(f"成功锁定歌手: '{artist_name}'，官方记录总歌曲数: {total_songs_count}")
                song_list = api_data.get('songList', [])
                if not song_list:
                    print("  -> 已获取该歌手所有歌曲。")
                    break
                all_songs.extend(song_list)
                print(f"  -> 已获取 {len(song_list)} 首歌曲，累计: {len(all_songs)} / {total_songs_count}")
                page_num += 1
                time.sleep(1)
            else:
                print(f"获取歌手 {artist_id} 的歌曲列表时，API返回错误: {data}", file=sys.stderr)
                break
        except Exception as e:
            print(f"获取歌手 {artist_id} 歌曲列表时出错: {e}", file=sys.stderr)
            break
    if all_songs:
        return {"artist_name": artist_name, "songs": all_songs}
    return None


def get_lyrics_api(song_id):
    """
    获取歌曲的歌词。
    """
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
    req_data = {"comm": {"ct": 24, "cv": 0, "g_tk": 5381},
                "req_lyric": {"module": "music.musichallSong.PlayLyricInfo", "method": "GetPlayLyricInfo",
                              "param": {"songMID": song_id}}}
    try:
        res = requests.post(url, headers=HEADERS, data=json.dumps(req_data), timeout=10, proxies=NO_PROXY)
        res.raise_for_status()
        data = res.json()
        if data.get('code') == 0 and data.get('req_lyric', {}).get('code') == 0:
            lyric_base64 = data['req_lyric']['data'].get('lyric')
            if lyric_base64:
                return base64.b64decode(lyric_base64).decode('utf-8')
    except Exception as e:
        print(f"  -> 获取ID={song_id}的歌词失败: {e}", file=sys.stderr)
    return None


def get_all_comments_api(song_id_num, song_id):
    """
    分页获取一首歌的所有评论。
    """
    print(f"    -> 开始获取歌曲 {song_id} 的评论...")
    all_comments, page = [], 0
    while len(all_comments) < MAX_COMMENTS_PER_SONG:
        comment_url = 'https://c.y.qq.com/base/fcgi-bin/fcg_global_comment_h5.fcg'
        params = {'biztype': 1, 'topid': song_id_num, 'cmd': 8, 'pagenum': page, 'pagesize': COMMENTS_PER_PAGE,
                  'format': 'json', 'g_tk': 5381}
        try:
            res = requests.get(comment_url, headers=HEADERS, params=params, timeout=10, proxies=NO_PROXY)
            res.raise_for_status()
            data = res.json()
            if data.get('code') == 0:
                comments = data.get('comment', {}).get('commentlist', [])
                if not comments:
                    print(f"    -> 已无更多评论。")
                    break
                for cmt in comments:
                    all_comments.append(
                        {'comment_id': cmt.get('commentid'), 'song_id': song_id, 'user_nickname': cmt.get('nick'),
                         'content': cmt.get('rootcommentcontent'), 'liked_count': cmt.get('praisenum'),
                         'comment_time': cmt.get('time')})
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
    print("--- QQ音乐爬虫启动 (V19 - 向上取整版) ---")
    init_environment()

    # 调用 find_input_file 函数自动查找输入文件
    input_filepath = find_input_file()
    if not input_filepath:
        print("\n错误：在程序目录下未找到 'artists.xlsx' 或 'artists.csv' 文件。", file=sys.stderr)
        print("请确保您的歌手列表文件存在，并已正确命名。", file=sys.stderr)
        sys.exit(1)

    artists_to_process_raw = read_input_file(input_filepath)

    # 清洗数据，去除 singer_mid 为空的行
    df_cleaned = pd.DataFrame(artists_to_process_raw)
    df_cleaned.dropna(subset=['singer_mid'], inplace=True)
    artists_to_process = df_cleaned.to_dict('records')

    for artist_task in artists_to_process:
        artist_id, artist_weight = artist_task['singer_mid'], artist_task['weight']

        # 确保 artist_id 不是浮点数 NaN (虽然 dropna 已处理，但作为双重保障)
        if pd.isna(artist_id):
            continue

        artist_data = get_artist_songs_api(str(artist_id))  # 确保ID是字符串
        if not artist_data:
            print(f"跳过无法获取歌曲的歌手: {artist_id}")
            continue

        full_song_list = artist_data.get('songs', [])
        artist_name = artist_data.get('artist_name', artist_id)

        # 修改：使用 math.ceil 进行向上取整
        num_to_process = int(math.ceil(len(full_song_list) * artist_weight))

        songs_to_process = full_song_list[:num_to_process]
        total_to_process = len(songs_to_process)

        print(f"\n--- 开始处理歌手 '{artist_name}' 的 {total_to_process} 首歌曲 (权重: {artist_weight:.2%}) ---")

        for index, song in enumerate(songs_to_process):
            try:
                song_data = song['songInfo']
                song_id, song_id_num, song_name = song_data['mid'], song_data['id'], song_data['name']
                album_mid = song_data.get('album', {}).get('mid')
                album_name = song_data.get('album', {}).get('name')
                artist_names_json = json.dumps([s.get('name') for s in song_data.get('singer', [])], ensure_ascii=False)
                cover_url = f"https://y.qq.com/music/photo_new/T002R500x500M000{album_mid}.jpg" if album_mid else ""
            except KeyError as e:
                print(f"解析歌曲基础信息时缺少关键字段: {e}，跳过此歌曲。歌曲数据: {song}", file=sys.stderr)
                continue
            print(
                f"\n[歌手 '{artist_name}' 歌曲进度 {index + 1}/{total_to_process}] 正在处理: {song_name} (ID: {song_id})")
            existing_song = execute_db_query("SELECT song_id FROM songs WHERE song_id = ?", (song_id,), fetch='one')
            if existing_song:
                print(f"  -> 歌曲 '{song_name}' 已存在于数据库中，跳过处理。")
                continue
            execute_db_query(
                'INSERT OR IGNORE INTO songs (song_id, name, album_name, album_mid, artist_names, tags) VALUES (?, ?, ?, ?, ?, NULL)',
                (song_id, song_name, album_name, album_mid, artist_names_json))
            cover_path = download_cover(song_name, song_id, cover_url)
            if cover_path:
                execute_db_query("UPDATE songs SET cover_path = ? WHERE song_id = ?", (cover_path, song_id))
            time.sleep(0.5)
            comments = get_all_comments_api(song_id_num, song_id)
            if comments:
                for cmt in comments:
                    execute_db_query(
                        'INSERT OR IGNORE INTO comments (comment_id, song_id, user_nickname, content, liked_count, comment_time) VALUES (?, ?, ?, ?, ?, ?)',
                        (cmt['comment_id'], cmt['song_id'], cmt['user_nickname'], cmt['content'], cmt['liked_count'],
                         cmt['comment_time']))
                print(f"  -> 已完成 {len(comments)} 条评论的存储。")
            lyrics = get_lyrics_api(song_id)
            if lyrics:
                execute_db_query("UPDATE songs SET lrc = ? WHERE song_id = ?", (lyrics, song_id))
                print(f"  -> 成功获取并存储歌词。")
            else:
                print(f"  -> 未找到该歌曲的歌词。")
            print(f"  -> 歌曲 '{song_name}' 处理完毕，等待2秒...")
            time.sleep(2)
    print("\n--- 所有任务处理完毕 ---")
    print(f"数据已存储在数据库文件: {DB_FILE}")
    export_to_excel()


# --- 程序入口 ---
if __name__ == '__main__':
    main()
