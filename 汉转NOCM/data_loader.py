"""数据下载与加载模块：负责从远程或本地获取 json.gz 音标数据。"""

import os
import gzip
import json
import urllib.request
from typing import Dict, List, Any, Optional


def get_data_dir() -> str:
    """返回数据文件所在目录：打包为 exe 时取 exe 所在目录，否则取脚本目录。"""
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_JSON_GZ_URL = 'https://qwert-ly.github.io/xtext/base.json.gz'
EXTRA_JSON_GZ_URL = 'https://qwert-ly.github.io/xtext/extra.json.gz'


def _local_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def _get_remote_last_modified(url: str) -> Optional[float]:
    """获取远程文件的 Last-Modified 时间戳，失败返回 None。"""
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            lm = resp.headers.get('Last-Modified')
            if lm:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(lm).timestamp()
    except Exception:
        pass
    return None


def _needs_update(url: str, local_path: str) -> bool:
    """比较远程和本地文件时间，判断是否需要更新。"""
    if not os.path.exists(local_path):
        return True
    remote_ts = _get_remote_last_modified(url)
    if remote_ts is None:
        return True
    local_ts = os.path.getmtime(local_path)
    return remote_ts > local_ts


def download_and_update(on_status=None, on_progress=None):
    """下载 base.json.gz 和 extra.json.gz 到数据目录，静默失败。

    on_status(msg):         状态文本回调
    on_progress(pct, name): 下载百分比回调 0-100，-1 表示未知大小
    """
    def _status(msg):
        print(msg)
        if on_status:
            on_status(msg)

    def _progress(pct, name):
        if on_progress:
            on_progress(pct, name)

    for url, filename in [
        (BASE_JSON_GZ_URL, 'base.json.gz'),
        (EXTRA_JSON_GZ_URL, 'extra.json.gz'),
    ]:
        local_path = _local_path(filename)
        try:
            _status(f'正在检查 {filename} ...')
            if not _needs_update(url, local_path):
                _status(f'[跳过] {filename} 已是最新')
                continue

            _status(f'正在下载 {filename} ...')
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = resp.headers.get('Content-Length')
                total = int(total) if total else 0
                downloaded = 0
                chunks = []
                block_size = 8192

                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        _progress(pct, filename)
                    else:
                        _progress(-1, filename)

                data = b''.join(chunks)

            tmp_path = local_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(data)
            os.replace(tmp_path, local_path)
            remote_ts = _get_remote_last_modified(url)
            if remote_ts:
                os.utime(local_path, (remote_ts, remote_ts))
            _status(f'[完成] {filename} ({len(data)} bytes)')
            _progress(100, filename)
        except Exception as e:
            _status(f'[跳过] {filename} 下载失败: {e}')


def load_map_from_json_gz() -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """从本地 base.json.gz + extra.json.gz 构建映射字典。"""
    base_path = _local_path('base.json.gz')
    extra_path = _local_path('extra.json.gz')

    try:
        with gzip.open(base_path, 'rt', encoding='utf-8') as f:
            base_data = json.load(f)
    except Exception as e:
        print(f'[错误] 读取 base.json.gz 失败: {e}')
        return None

    extra_data = None
    try:
        with gzip.open(extra_path, 'rt', encoding='utf-8') as f:
            extra_data = json.load(f)
    except Exception as e:
        print(f'[警告] 读取 extra.json.gz 失败 (注释将不可用): {e}')

    mapping: Dict[str, List[Dict[str, Any]]] = {}
    for i, entry in enumerate(base_data):
        ch = entry.get('z', '')
        phonetic = entry.get('y', '').strip()
        if not ch or not phonetic:
            continue

        note = None
        if extra_data and i < len(extra_data):
            ext = extra_data[i]
            parts = []
            d = ext.get('d')
            if d and isinstance(d, list):
                if len(d) > 0 and isinstance(d[0], str) and d[0].strip():
                    parts.append(d[0].strip())
                if len(d) > 1 and isinstance(d[1], list):
                    for j, defn in enumerate(d[1], 1):
                        if defn and isinstance(defn, str):
                            parts.append(f'{j}{defn}')
            e_val = ext.get('e')
            if e_val and isinstance(e_val, str) and e_val.strip():
                parts.append(e_val.strip())
            n_val = ext.get('n')
            if n_val and isinstance(n_val, str) and n_val.strip():
                parts.append(n_val.strip())
            if parts:
                note = '\n'.join(parts)

        mapping.setdefault(ch, []).append({'phonetic': phonetic, 'note': note})

    print(f'[加载] 从 JSON 加载了 {len(mapping)} 个字的音标数据')
    return mapping if mapping else None
