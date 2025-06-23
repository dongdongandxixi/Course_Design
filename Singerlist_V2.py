import requests
import json
import csv
from time import sleep


def fetch_singer_list():
    # 请求头设置
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://y.qq.com/n/ryqq/singer_list',
        'Content-Type': 'application/json'
    }

    # 基础URL
    url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'

    singers = []
    page = 1
    per_page = 80  # 每页数量

    while True:
        # 构造POST请求的JSON数据
        payload = {
            "comm": {"ct": "24", "cv": "10000"},
            "singerList": {
                "module": "Music.SingerListServer",
                "method": "get_singer_list",
                "param": {
                    "area": -100,  # -100表示全部地区
                    "sex": -100,  # -100表示全部性别
                    "genre": -100,  # -100表示全部流派
                    "index": -100,  # -100表示全部索引
                    "sin": (page - 1) * per_page,  # 起始位置
                    "cur_page": page  # 当前页码
                }
            }
        }

        # 发送POST请求
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()  # 检查请求是否成功
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
            break
        except json.JSONDecodeError:
            print("JSON解析失败")
            break

        # 提取歌手列表
        singer_list = data.get('singerList', {}).get('data', {}).get('singerlist', [])

        # 如果没有数据，终止循环
        if not singer_list:
            print("没有更多数据，爬取结束")
            break

        # 提取歌手信息
        for singer in singer_list:
            singer_mid = singer.get('singer_mid')  # 使用singer_mid代替singer_id
            singer_name = singer.get('singer_name')
            if singer_mid and singer_name:
                singers.append({
                    'singer_mid': singer_mid,
                    'singer_name': singer_name
                })

        print(f'已爬取第 {page} 页，共 {len(singer_list)} 位歌手')
        page += 1

        # 添加延迟避免请求过快
        sleep(0.5)

    return singers


def save_to_csv(singers, filename):
    """将歌手数据保存为CSV文件"""
    with open(filename, 'w', encoding='utf-8-sig', newline='') as f:  # utf-8-sig处理Excel中文乱码
        fieldnames = ['singer_mid', 'singer_name']
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        writer.writeheader()
        for singer in singers:
            writer.writerow(singer)


if __name__ == '__main__':
    # 获取歌手列表
    print("开始爬取QQ音乐歌手数据...")
    singer_data = fetch_singer_list()

    # 保存结果到CSV文件
    csv_filename = 'qq_music_singers.csv'
    save_to_csv(singer_data, csv_filename)

    print(f'共爬取 {len(singer_data)} 位歌手信息，已保存到 {csv_filename}')
    print(f"文件格式: singer_mid, singer_name")
    print(f"示例数据:\n{singer_data[0] if singer_data else '无数据'}")