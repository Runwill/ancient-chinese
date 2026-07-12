"""数据下载与加载模块：负责从远程或本地获取 json.gz 音标数据。"""

import os
import gzip
import json
import io
import urllib.request
from datetime import datetime
from typing import Dict, List, Any, Optional

from atomic_io import save_json_atomic


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


def _load_gz_json(path_or_bytes):
    """从文件路径或 bytes 加载 gzip JSON 数据。"""
    try:
        if isinstance(path_or_bytes, bytes):
            with gzip.open(io.BytesIO(path_or_bytes), 'rt', encoding='utf-8') as f:
                return json.load(f)
        else:
            with gzip.open(path_or_bytes, 'rt', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        return None


def _diff_data(old_data, new_data, filename):
    """比较新旧数据，返回差异描述列表。
    base.json.gz 按字分组比较读音列表，不受插入/删除位移影响；
    其它文件回退到逐索引对比。"""
    if old_data is None or new_data is None:
        return []
    diffs = []
    if filename == 'base.json.gz':
        # 按字分组: {字 -> sorted([读音列表])}
        old_map = {}
        for e in old_data:
            ch = e.get('z', '')
            ph = e.get('y', '').strip()
            if ch and ph:
                old_map.setdefault(ch, []).append(ph)
        new_map = {}
        for e in new_data:
            ch = e.get('z', '')
            ph = e.get('y', '').strip()
            if ch and ph:
                new_map.setdefault(ch, []).append(ph)
        all_chars = sorted(set(old_map) | set(new_map))
        for ch in all_chars:
            old_phs = sorted(old_map.get(ch, []))
            new_phs = sorted(new_map.get(ch, []))
            if old_phs == new_phs:
                continue
            if not old_phs:
                diffs.append(f'  [新增] {ch}: {", ".join(new_phs)}')
            elif not new_phs:
                diffs.append(f'  [删除] {ch}: {", ".join(old_phs)}')
            else:
                removed = sorted(set(old_phs) - set(new_phs))
                added = sorted(set(new_phs) - set(old_phs))
                parts = []
                if removed:
                    parts.append(f'移除 {", ".join(removed)}')
                if added:
                    parts.append(f'新增 {", ".join(added)}')
                if not parts:
                    # 读音相同但出现次数变化
                    parts.append(f'{", ".join(old_phs)} → {", ".join(new_phs)}')
                diffs.append(f'  [修改] {ch}: {"; ".join(parts)}')
    else:
        max_len = max(len(old_data), len(new_data))
        for i in range(max_len):
            old_entry = old_data[i] if i < len(old_data) else None
            new_entry = new_data[i] if i < len(new_data) else None
            if old_entry == new_entry:
                continue
            if old_entry is None:
                diffs.append(f'  [新增] #{i}: {json.dumps(new_entry, ensure_ascii=False)}')
            elif new_entry is None:
                diffs.append(f'  [删除] #{i}: {json.dumps(old_entry, ensure_ascii=False)}')
            else:
                diffs.append(f'  [修改] #{i}:')
                diffs.append(f'    旧: {json.dumps(old_entry, ensure_ascii=False)}')
                diffs.append(f'    新: {json.dumps(new_entry, ensure_ascii=False)}')
    return diffs


def _log_diff(filename, diffs, status_fn):
    """将差异写入 data_update.log。"""
    if not diffs:
        status_fn(f'[对比] {filename} 内容无实质变化')
        return
    log_path = os.path.join(get_data_dir(), 'data_update.log')
    header = f'\n{"="*60}\n[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {filename} 更新 — 共 {len([d for d in diffs if d.startswith("  [")])} 处差异\n{"="*60}'
    entry = header + '\n' + '\n'.join(diffs) + '\n'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(entry)
    count = len([d for d in diffs if d.startswith('  [')])
    status_fn(f'[对比] {filename} 有 {count} 处差异，已记录到 data_update.log')


def _extract_changed_chars(old_data, new_data):
    """从 base.json.gz 的新旧数据中提取读音有变化的汉字集合。"""
    if old_data is None or new_data is None:
        return set()
    changed = set()
    # 构建 旧: {字 -> [读音列表]}
    old_map = {}
    for entry in old_data:
        ch = entry.get('z', '')
        ph = entry.get('y', '').strip()
        if ch and ph:
            old_map.setdefault(ch, []).append(ph)
    # 构建 新: {字 -> [读音列表]}
    new_map = {}
    for entry in new_data:
        ch = entry.get('z', '')
        ph = entry.get('y', '').strip()
        if ch and ph:
            new_map.setdefault(ch, []).append(ph)
    # 对比
    all_chars = set(old_map) | set(new_map)
    for ch in all_chars:
        if sorted(old_map.get(ch, [])) != sorted(new_map.get(ch, [])):
            changed.add(ch)
    return changed


_CHANGED_CHARS_FILE = 'changed_chars.json'


def get_changed_chars() -> set:
    """读取因数据更新而读音发生变化的汉字集合。"""
    path = os.path.join(get_data_dir(), _CHANGED_CHARS_FILE)
    data = None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    if isinstance(data, list):
        return set(data)
    return set()


def save_changed_chars(chars: set):
    """保存变化汉字集合。"""
    path = os.path.join(get_data_dir(), _CHANGED_CHARS_FILE)
    save_json_atomic(path, sorted(chars))


def clear_changed_char(ch: str):
    """从变化集合中移除单个汉字（用户已重新选择读音后）。"""
    chars = get_changed_chars()
    if ch in chars:
        chars.discard(ch)
        save_changed_chars(chars)
    return chars


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

            # 对比新旧数据
            if os.path.exists(local_path):
                old_data = _load_gz_json(local_path)
                new_data = _load_gz_json(data)
                diffs = _diff_data(old_data, new_data, filename)
                _log_diff(filename, diffs, _status)
                # base.json.gz 变化时记录受影响的汉字
                if filename == 'base.json.gz' and old_data and new_data:
                    changed = _extract_changed_chars(old_data, new_data)
                    if changed:
                        existing = get_changed_chars()
                        merged = existing | changed
                        save_changed_chars(merged)
                        _status(f'[标记] {len(changed)} 个汉字的读音发生变化')

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
