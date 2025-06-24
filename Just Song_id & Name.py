# -*- coding: utf-8 -*-
"""
@Project: QQ Music Scraper (Pro Version - Artist Edition)
@File:    qq_music_scraper_pro_v17_minimal_proxyfix.py
@Author:
@Date:    2025-06-23
@Description:
    【超精简可行性分析版】
    一个通过QQ音乐【歌手ID】，仅爬取其名下所有歌曲的ID(song_id)和歌名(name)的Python爬虫。
    本版本为可行性分析专用，移除了所有下载、歌词、标签等附加功能，专注于以最快速度获取核心数据。
    【新增功能】：1. 将结果导出为Excel。 2. 禁用系统代理，防止ProxyError。
"""

# --- 模块导入 ---
import requests  # 用于发送HTTP网络请求
import sqlite3  # 用于操作SQLite数据库
import time  # 用于实现程序延时
import json  # 用于处理JSON格式的数据
import sys  # 用于访问系统特定的参数和功能
import pandas as pd
import math

# --- 全局配置 (Global Configuration) ---

# 1. 数据库与输出文件配置
DB_FILE = 'qq_music_ids_library.db'
OUTPUT_EXCEL_FILE = 'qq_music_song_list.xlsx'

# 2. 伪装请求头 (Request Headers)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Referer': 'https://y.qq.com/',
    'Content-Type': 'application/json'
}

# 3. 代理配置
# 新增：定义一个空的代理字典，以覆盖并禁用系统代理，解决 ProxyError 问题
NO_PROXY = {'http': None, 'https': None}

# 4. 导入excel
try:
    df = pd.read_csv("test.csv")
    df.dropna(subset=['singer_mid'], inplace=True)
except FileNotFoundError:
    print("错误：未找到 'test.csv' 文件。请确保该文件与脚本在同一目录下。", file=sys.stderr)
    sys.exit(1)


# --- 核心功能函数 ---

def init_environment():
    """
    初始化运行环境：连接或创建SQLite数据库，并创建精简版的 'songs' 表。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            print(f"正在连接数据库 '{DB_FILE}' 并创建 'songs' 表...")
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                song_id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )''')
            conn.commit()
            print("数据库和表已准备就绪。")
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
            if fetch == 'one':
                return cursor.fetchone()
            if fetch == 'all':
                return cursor.fetchall()
            conn.commit()
    except sqlite3.Error as e:
        print(f"数据库操作错误: {e}", file=sys.stderr)
        return None


def export_to_excel():
    """
    将数据库中的 'songs' 表的所有数据导出到一个Excel文件中。
    """
    print(f"\n--- 正在将结果导出到Excel文件: {OUTPUT_EXCEL_FILE} ---")
    try:
        conn = sqlite3.connect(DB_FILE)
        songs_df = pd.read_sql_query("SELECT * FROM songs", conn)
        conn.close()
        songs_df.to_excel(OUTPUT_EXCEL_FILE, index=False, engine='openpyxl')
        print(f"✔ 成功导出 {len(songs_df)} 条记录到 {OUTPUT_EXCEL_FILE}")
    except Exception as e:
        print(f"导出到Excel时发生错误: {e}", file=sys.stderr)


def get_artist_songs_api(artist_id):
    """
    通过歌手ID，分页获取其名下的所有歌曲列表。
    """
    print(f"\n正在获取歌手详情: ID={artist_id}")
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
    all_songs, page_num, artist_name, total_songs_count = [], 0, "", 0
    songs_per_page = 80

    while True:
        req_data = {
            "comm": {"ct": 24, "cv": 0},
            "req_1": {
                "module": "musichall.song_list_server",
                "method": "GetSingerSongList",
                "param": {"singerMid": artist_id, "begin": page_num * songs_per_page, "num": songs_per_page, "order": 1}
            }
        }
        try:
            # 修改：增加了 proxies=NO_PROXY 参数，以忽略系统代理
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
                time.sleep(0.5)
            else:
                print(f"获取歌手 {artist_id} 的歌曲列表时，API返回错误: {data}", file=sys.stderr)
                break
        except Exception as e:
            print(f"获取歌手 {artist_id} 歌曲列表时出错: {e}", file=sys.stderr)
            break

    if all_songs:
        return {"artist_name": artist_name, "songs": all_songs}
    return None


# --- 主程序逻辑 (Main Logic) ---

def main():
    """
    主程序执行入口。
    """
    print("--- QQ音乐爬虫启动 (V17 - 超精简可行性分析版) ---")
    init_environment()

    for artist_id, weight in zip(df["singer_mid"], df["song_weight"]):
        # 修正：使用 pd.isna() 来判断是否为 NaN
        if not pd.isna(artist_id):
            artist_data = get_artist_songs_api(artist_id)
            if not artist_data:
                print(f"跳过无法获取歌曲的歌手: {artist_id}")
                continue

            song_list = artist_data.get('songs', [])
            artist_name = artist_data.get('artist_name', artist_id)
            total_num = len(song_list)
            need_song_num = math.ceil(total_num * weight)
            new_songs_count = 0
            print(f"\n--- 开始处理歌手 '{artist_name}' 的 {need_song_num} 首歌曲，并存入数据库 ---")

            for index, song in enumerate(song_list):
                if index + 1 <= need_song_num:
                    try:
                        song_data = song['songInfo']
                        song_id = song_data['mid']
                        song_name = song_data['name']
                    except KeyError as e:
                        print(f"解析歌曲基础信息时缺少关键字段: {e}，跳过。", file=sys.stderr)
                        continue

                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("INSERT OR IGNORE INTO songs (song_id, name) VALUES (?, ?)", (song_id, song_name))
                    if cursor.rowcount > 0:
                        new_songs_count += 1
                    conn.commit()
                    conn.close()

            print(f"\n--- 歌手 '{artist_name}' 处理完毕 ---")
            print(f"总共发现 {total_num} 首歌曲，记录 {need_song_num} 首歌， {new_songs_count} 首为新歌")

    print(f"\n--- 所有任务处理完毕 ---")
    print(f"所有歌曲ID和名称已存储在数据库文件: {DB_FILE}")

    export_to_excel()


# --- 程序入口 ---
if __name__ == '__main__':
    main()
