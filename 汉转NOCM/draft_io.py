"""文稿管理：文稿的读写、列出、删除、排序等文件 I/O 操作。"""

import json
import os
import re
from datetime import datetime

_DRAFTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'drafts')
_DRAFTS_ORDER_FILE = os.path.join(_DRAFTS_DIR, '_order.json')


def ensure_drafts_dir():
    os.makedirs(_DRAFTS_DIR, exist_ok=True)


def get_drafts_order():
    """获取文稿排序列表。"""
    ensure_drafts_dir()
    if os.path.exists(_DRAFTS_ORDER_FILE):
        try:
            with open(_DRAFTS_ORDER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_drafts_order(order):
    """保存文稿排序列表。"""
    ensure_drafts_dir()
    with open(_DRAFTS_ORDER_FILE, 'w', encoding='utf-8') as f:
        json.dump(order, f, ensure_ascii=False)


def list_drafts():
    """列出所有已保存的文稿，按自定义顺序排列（新文稿在前）。"""
    ensure_drafts_dir()
    drafts = []
    for fn in os.listdir(_DRAFTS_DIR):
        if not fn.endswith('.json') or fn.startswith('_'):
            continue
        fp = os.path.join(_DRAFTS_DIR, fn)
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            drafts.append({
                'filename': fn,
                'name': data.get('name', fn[:-5]),
                'modified': data.get('modified', ''),
                'preview': data.get('preview', ''),
            })
        except (json.JSONDecodeError, OSError):
            continue
    # 按自定义顺序排列，新文稿放最前
    order = get_drafts_order()
    new_drafts = [d for d in drafts if d['filename'] not in order]
    ordered_drafts = [d for d in drafts if d['filename'] in order]
    new_drafts.sort(key=lambda d: d['modified'], reverse=True)
    ordered_drafts.sort(key=lambda d: order.index(d['filename']))
    return new_drafts + ordered_drafts


def save_draft(filename, name, buffer, cell_info):
    """保存文稿到文件，返回实际使用的文件名。"""
    ensure_drafts_dir()
    if filename is None:
        filename = datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
    if name is None:
        raw = ''.join(buffer[0]) if buffer[0] else ''
        m = re.match(
            r"[^\s，。！？；：、「」『』【】（）\u201c\u201d\u2018\u2019',\.!\?;:\(\)\[\]\"'…—―．]+", raw)
        name = m.group()[:20] if m else '未命名文稿'

    serialized_info = []
    for row in cell_info:
        row_info = []
        for info in row:
            row_info.append({
                'phonetic': info['phonetic'],
                'is_poly': info['is_poly'],
                'selected': info.get('selected', 'none'),
            })
        serialized_info.append(row_info)

    preview_chars = []
    for line in buffer:
        preview_chars.extend(line)
        if len(preview_chars) >= 30:
            break
    preview = ''.join(preview_chars[:30])

    data = {
        'name': name,
        'created': datetime.now().isoformat(),
        'modified': datetime.now().isoformat(),
        'preview': preview,
        'buffer': buffer,
        'cell_info': serialized_info,
    }
    fp = os.path.join(_DRAFTS_DIR, filename)
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    return filename


def load_draft(filename, mapping):
    """从文件加载文稿，返回 (buffer, cell_info) 元组。"""
    fp = os.path.join(_DRAFTS_DIR, filename)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)

    buffer = data['buffer']
    loaded_info = data['cell_info']
    cell_info = []
    for li, (row_chars, row_info) in enumerate(zip(buffer, loaded_info)):
        rebuilt = []
        for ci, (ch, info) in enumerate(zip(row_chars, row_info)):
            opts = mapping.get(ch)
            is_poly = info.get('is_poly', False)
            rebuilt.append({
                'phonetic': info['phonetic'],
                'options': opts if is_poly and opts and len(opts) > 1 else None,
                'is_poly': is_poly,
                'selected': info.get('selected', 'none'),
            })
        cell_info.append(rebuilt)

    return buffer, cell_info


def delete_draft(filename):
    """删除文稿文件。"""
    fp = os.path.join(_DRAFTS_DIR, filename)
    try:
        os.remove(fp)
    except OSError:
        pass


def rename_draft(filename, new_name):
    """重命名文稿。"""
    fp = os.path.join(_DRAFTS_DIR, filename)
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['name'] = new_name
        data['modified'] = datetime.now().isoformat()
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except (json.JSONDecodeError, OSError):
        pass


def get_draft_name(filename):
    """读取文稿显示名称。"""
    fp = os.path.join(_DRAFTS_DIR, filename)
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('name', filename)
    except (json.JSONDecodeError, OSError):
        return filename
