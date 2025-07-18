# -*- encoding: utf-8 -*-

"""
Author: Hmily
GitHub: https://github.com/ihmily
Date: 2023-07-15 23:15:00
Update: 2025-02-06 02:28:00
Copyright (c) 2023-2025 by Hmily, All Rights Reserved.
Function: Get live stream data.
"""
import base64
import hashlib
import json
import time
import random
import re
from operator import itemgetter
import urllib.parse
import urllib.request
from .utils import trace_error_decorator
from .spider import (
    get_douyu_stream_data, get_bilibili_stream_data
)
from .http_clients.async_http import get_response_status

QUALITY_MAPPING = {"OD": 0, "BD": 0, "UHD": 1, "HD": 2, "SD": 3, "LD": 4}


def get_quality_index(quality) -> tuple:
    if not quality:
        return list(QUALITY_MAPPING.items())[0]

    quality_str = str(quality).upper()
    if quality_str.isdigit():
        quality_int = int(quality_str[0])
        quality_str = list(QUALITY_MAPPING.keys())[quality_int]
    return quality_str, QUALITY_MAPPING.get(quality_str, 0)


@trace_error_decorator
async def get_douyin_stream_url(json_data: dict, video_quality: str, proxy_addr: str) -> dict:
    anchor_name = json_data.get('anchor_name')

    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }

    status = json_data.get("status", 4)

    if status == 2:
        stream_url = json_data['stream_url']
        flv_url_dict = stream_url['flv_pull_url']
        flv_url_list: list = list(flv_url_dict.values())
        m3u8_url_dict = stream_url['hls_pull_url_map']
        m3u8_url_list: list = list(m3u8_url_dict.values())

        while len(flv_url_list) < 5:
            flv_url_list.append(flv_url_list[-1])
            m3u8_url_list.append(m3u8_url_list[-1])

        video_quality, quality_index = get_quality_index(video_quality)
        m3u8_url = m3u8_url_list[quality_index]
        flv_url = flv_url_list[quality_index]
        ok = await get_response_status(url=m3u8_url, proxy_addr=proxy_addr)
        if not ok:
            index = quality_index + 1 if quality_index < 4 else quality_index - 1
            m3u8_url = m3u8_url_list[index]
            flv_url = flv_url_list[index]
        result |= {
            'is_live': True,
            'title': json_data['title'],
            'quality': video_quality,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': m3u8_url or flv_url,
        }
    return result


@trace_error_decorator
async def get_tiktok_stream_url(json_data: dict, video_quality: str, proxy_addr: str) -> dict:
    if not json_data:
        return {"anchor_name": None, "is_live": False}

    def get_video_quality_url(stream, q_key) -> list:
        play_list = []
        for key in stream:
            url_info = stream[key]['main']
            sdk_params = url_info['sdk_params']
            sdk_params = json.loads(sdk_params)
            vbitrate = int(sdk_params['vbitrate'])
            v_codec = sdk_params.get('VCodec', '')

            play_url = ''
            if url_info.get(q_key):
                if url_info[q_key].endswith(".flv") or url_info[q_key].endswith(".m3u8"):
                    play_url = url_info[q_key] + '?codec=' + v_codec
                else:
                    play_url = url_info[q_key] + '&codec=' + v_codec

            resolution = sdk_params['resolution']
            if vbitrate != 0 and resolution:
                width, height = map(int, resolution.split('x'))
                play_list.append({'url': play_url, 'vbitrate': vbitrate, 'resolution': (width, height)})

        play_list.sort(key=itemgetter('vbitrate'), reverse=True)
        play_list.sort(key=lambda x: (-x['vbitrate'], -x['resolution'][0], -x['resolution'][1]))
        return play_list

    live_room = json_data['LiveRoom']['liveRoomUserInfo']
    user = live_room['user']
    anchor_name = f"{user['nickname']}-{user['uniqueId']}"
    status = user.get("status", 4)

    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }

    if status == 2:
        stream_data = live_room['liveRoom']['streamData']['pull_data']['stream_data']
        stream_data = json.loads(stream_data).get('data', {})
        flv_url_list = get_video_quality_url(stream_data, 'flv')
        m3u8_url_list = get_video_quality_url(stream_data, 'hls')

        while len(flv_url_list) < 5:
            flv_url_list.append(flv_url_list[-1])
        while len(m3u8_url_list) < 5:
            m3u8_url_list.append(m3u8_url_list[-1])
        video_quality, quality_index = get_quality_index(video_quality)
        flv_dict: dict = flv_url_list[quality_index]
        m3u8_dict: dict = m3u8_url_list[quality_index]

        check_url = m3u8_dict.get('url') or flv_dict.get('url')
        ok = await get_response_status(url=check_url, proxy_addr=proxy_addr, http2=False)

        if not ok:
            index = quality_index + 1 if quality_index < 4 else quality_index - 1
            flv_dict: dict = flv_url_list[index]
            m3u8_dict: dict = m3u8_url_list[index]

        flv_url = flv_dict['url']
        m3u8_url = m3u8_dict['url']
        result |= {
            'is_live': True,
            'title': live_room['liveRoom']['title'],
            'quality': video_quality,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': m3u8_url or flv_url,
        }
    return result


@trace_error_decorator
async def get_kuaishou_stream_url(json_data: dict, video_quality: str) -> dict:
    if json_data['type'] == 1 and not json_data["is_live"]:
        return json_data
    live_status = json_data['is_live']

    result = {
        "type": 2,
        "anchor_name": json_data['anchor_name'],
        "is_live": live_status,
    }

    if live_status:
        quality_mapping_bit = {'OD': 99999, 'BD': 4000, 'UHD': 2000, 'HD': 1000, 'SD': 800, 'LD': 600}
        if video_quality in QUALITY_MAPPING:

            quality, quality_index = get_quality_index(video_quality)
            if 'm3u8_url_list' in json_data:
                m3u8_url_list = json_data['m3u8_url_list'][::-1]
                while len(m3u8_url_list) < 5:
                    m3u8_url_list.append(m3u8_url_list[-1])
                m3u8_url = m3u8_url_list[quality_index]['url']
                result['m3u8_url'] = m3u8_url

            if 'flv_url_list' in json_data:
                if 'bitrate' in json_data['flv_url_list'][0]:
                    flv_url_list = json_data['flv_url_list']
                    flv_url_list = sorted(flv_url_list, key=lambda x: x['bitrate'], reverse=True)
                    quality_str = str(video_quality).upper()
                    if quality_str.isdigit():
                        video_quality, quality_index_bitrate_value = list(quality_mapping_bit.items())[int(quality_str)]
                    else:
                        quality_index_bitrate_value = quality_mapping_bit.get(quality_str, 99999)
                        video_quality = quality_str
                    quality_index = next(
                        (i for i, x in enumerate(flv_url_list) if x['bitrate'] <= quality_index_bitrate_value), None)
                    if quality_index is None:
                        quality_index = len(flv_url_list) - 1
                    flv_url = flv_url_list[quality_index]['url']

                    result['flv_url'] = flv_url
                    result['record_url'] = flv_url
                else:
                    flv_url_list = json_data['flv_url_list'][::-1]
                    while len(flv_url_list) < 5:
                        flv_url_list.append(flv_url_list[-1])
                    flv_url = flv_url_list[quality_index]['url']
                    result |= {'flv_url': flv_url, 'record_url': flv_url}
            result['is_live'] = True
            result['quality'] = video_quality
    return result


@trace_error_decorator
async def get_huya_stream_url(json_data: dict, video_quality: str) -> dict:
    game_live_info = json_data['data'][0]['gameLiveInfo']
    live_title = game_live_info['introduction']
    stream_info_list = json_data['data'][0]['gameStreamInfoList']
    anchor_name = game_live_info.get('nick', '')

    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }

    if stream_info_list:
        select_cdn = stream_info_list[0]
        flv_url = select_cdn.get('sFlvUrl')
        stream_name = select_cdn.get('sStreamName')
        flv_url_suffix = select_cdn.get('sFlvUrlSuffix')
        hls_url = select_cdn.get('sHlsUrl')
        hls_url_suffix = select_cdn.get('sHlsUrlSuffix')
        flv_anti_code = select_cdn.get('sFlvAntiCode')

        def get_anti_code(old_anti_code: str) -> str:

            # js地址：https://hd.huya.com/cdn_libs/mobile/hysdk-m-202402211431.js

            params_t = 100
            sdk_version = 2403051612

            # sdk_id是13位数毫秒级时间戳
            t13 = int(time.time()) * 1000
            sdk_sid = t13

            # 计算uuid和uid参数值
            init_uuid = (int(t13 % 10 ** 10 * 1000) + int(1000 * random.random())) % 4294967295  # 直接初始化
            uid = random.randint(1400000000000, 1400009999999)  # 经过测试uid也可以使用init_uuid代替
            seq_id = uid + sdk_sid  # 移动端请求的直播流地址中包含seqId参数

            # 计算ws_time参数值(16进制) 可以是当前毫秒时间戳，当然也可以直接使用url_query['wsTime'][0]
            # 原始最大误差不得慢240000毫秒
            target_unix_time = (t13 + 110624) // 1000
            ws_time = f"{target_unix_time:x}".lower()

            # fm参数值是经过url编码然后base64编码得到的，解码结果类似 DWq8BcJ3h6DJt6TY_$0_$1_$2_$3
            # 具体细节在上面js中查看，大概在32657行代码开始，有base64混淆代码请自行替换
            url_query = urllib.parse.parse_qs(old_anti_code)
            ws_secret_pf = base64.b64decode(urllib.parse.unquote(url_query['fm'][0]).encode()).decode().split("_")[0]
            ws_secret_hash = hashlib.md5(f'{seq_id}|{url_query["ctype"][0]}|{params_t}'.encode()).hexdigest()
            ws_secret = f'{ws_secret_pf}_{uid}_{stream_name}_{ws_secret_hash}_{ws_time}'
            ws_secret_md5 = hashlib.md5(ws_secret.encode()).hexdigest()

            anti_code = (
                f'wsSecret={ws_secret_md5}&wsTime={ws_time}&seqid={seq_id}&ctype={url_query["ctype"][0]}&ver=1'
                f'&fs={url_query["fs"][0]}&uuid={init_uuid}&u={uid}&t={params_t}&sv={sdk_version}'
                f'&sdk_sid={sdk_sid}&codec=264'
            )
            return anti_code

        new_anti_code = get_anti_code(flv_anti_code)
        flv_url = f'{flv_url}/{stream_name}.{flv_url_suffix}?{new_anti_code}&ratio='
        m3u8_url = f'{hls_url}/{stream_name}.{hls_url_suffix}?{new_anti_code}&ratio='

        quality_list = flv_anti_code.split('&exsphd=')
        if len(quality_list) > 1 and video_quality not in ["OD", "BD"]:
            pattern = r"(?<=264_)\d+"
            quality_list = list(re.findall(pattern, quality_list[1]))[::-1]
            while len(quality_list) < 5:
                quality_list.append(quality_list[-1])

            video_quality_options = {
                "UHD": quality_list[0],
                "HD": quality_list[1],
                "SD": quality_list[2],
                "LD": quality_list[3]
            }

            if video_quality not in video_quality_options:
                raise ValueError(
                    f"Invalid video quality. Available options are: {', '.join(video_quality_options.keys())}")

            flv_url = flv_url + str(video_quality_options[video_quality])
            m3u8_url = m3u8_url + str(video_quality_options[video_quality])

        result |= {
            'is_live': True,
            'title': live_title,
            'quality': video_quality,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': flv_url or m3u8_url
        }
    return result


@trace_error_decorator
async def get_douyu_stream_url(json_data: dict, video_quality: str, cookies: str, proxy_addr: str) -> dict:
    if not json_data["is_live"]:
        return json_data

    video_quality_options = {
        "OD": '0',
        "BD": '0',
        "UHD": '3',
        "HD": '2',
        "SD": '1',
        "LD": '1'
    }

    rid = str(json_data["room_id"])
    json_data.pop("room_id")
    rate = video_quality_options.get(video_quality, '0')
    flv_data = await get_douyu_stream_data(rid, rate, cookies=cookies, proxy_addr=proxy_addr)
    rtmp_url = flv_data['data'].get('rtmp_url')
    rtmp_live = flv_data['data'].get('rtmp_live')
    if rtmp_live:
        flv_url = f'{rtmp_url}/{rtmp_live}'
        json_data |= {'quality': video_quality, 'flv_url': flv_url, 'record_url': flv_url}
    return json_data


@trace_error_decorator
async def get_yy_stream_url(json_data: dict) -> dict:
    anchor_name = json_data.get('anchor_name', '')
    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }
    if 'avp_info_res' in json_data:
        stream_line_addr = json_data['avp_info_res']['stream_line_addr']
        cdn_info = list(stream_line_addr.values())[0]
        flv_url = cdn_info['cdn_info']['url']
        result |= {
            'is_live': True,
            'title': json_data['title'],
            'quality': 'OD',
            'flv_url': flv_url,
            'record_url': flv_url
        }
    return result


@trace_error_decorator
async def get_bilibili_stream_url(json_data: dict, video_quality: str, proxy_addr: str, cookies: str) -> dict:
    anchor_name = json_data["anchor_name"]
    if not json_data["live_status"]:
        return {
            "anchor_name": anchor_name,
            "is_live": False
        }

    room_url = json_data['room_url']

    video_quality_options = {
        "OD": '10000',
        "BD": '400',
        "UHD": '250',
        "HD": '150',
        "SD": '80',
        "LD": '80'
    }

    select_quality = video_quality_options[video_quality]
    play_url = await get_bilibili_stream_data(
        room_url, qn=select_quality, platform='web', proxy_addr=proxy_addr, cookies=cookies)
    return {
        'anchor_name': json_data['anchor_name'],
        'is_live': True,
        'title': json_data['title'],
        'quality': video_quality,
        'record_url': play_url
    }


@trace_error_decorator
async def get_netease_stream_url(json_data: dict, video_quality: str) -> dict:
    if not json_data['is_live']:
        return json_data

    m3u8_url = json_data['m3u8_url']
    flv_url = None
    if json_data.get('stream_list'):
        stream_list = json_data['stream_list']['resolution']
        order = ['blueray', 'ultra', 'high', 'standard']
        sorted_keys = [key for key in order if key in stream_list]
        while len(sorted_keys) < 5:
            sorted_keys.append(sorted_keys[-1])
        video_quality, quality_index = get_quality_index(video_quality)
        selected_quality = sorted_keys[quality_index]
        flv_url_list = stream_list[selected_quality]['cdn']
        selected_cdn = list(flv_url_list.keys())[0]
        flv_url = flv_url_list[selected_cdn]

    return {
        "is_live": True,
        "anchor_name": json_data['anchor_name'],
        "title": json_data['title'],
        'quality': video_quality,
        "m3u8_url": m3u8_url,
        "flv_url": flv_url,
        "record_url": flv_url or m3u8_url
    }


async def get_stream_url(json_data: dict, video_quality: str, url_type: str = 'm3u8', spec: bool = False,
                         hls_extra_key: str | int = None, flv_extra_key: str | int = None) -> dict:
    if not json_data['is_live']:
        return json_data

    play_url_list = json_data['play_url_list']
    while len(play_url_list) < 5:
        play_url_list.append(play_url_list[-1])

    video_quality, selected_quality = get_quality_index(video_quality)
    data = {
        "anchor_name": json_data['anchor_name'],
        "is_live": True
    }

    def get_url(key):
        play_url = play_url_list[selected_quality]
        return play_url[key] if key else play_url

    if url_type == 'all':
        m3u8_url = get_url(hls_extra_key)
        flv_url = get_url(flv_extra_key)
        data |= {
            "m3u8_url": json_data['m3u8_url'] if spec else m3u8_url,
            "flv_url": json_data['flv_url'] if spec else flv_url,
            "record_url": m3u8_url
        }
    elif url_type == 'm3u8':
        m3u8_url = get_url(hls_extra_key)
        data |= {"m3u8_url": json_data['m3u8_url'] if spec else m3u8_url, "record_url": m3u8_url}
    else:
        flv_url = get_url(flv_extra_key)
        data |= {"flv_url": flv_url, "record_url": flv_url}
    data['title'] = json_data.get('title')
    data['quality'] = video_quality
    return data