"""文稿管理：文稿的读写、列出、删除、排序等文件 I/O 操作。"""

import json
import os
import re
from datetime import datetime

_DRAFTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'drafts')
_DRAFTS_ORDER_FILE = os.path.join(_DRAFTS_DIR, '_order.json')
_GROUPS_FILE = os.path.join(_DRAFTS_DIR, '_groups.json')


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


# ── 文件夹（分组）管理 ──────────────────────────────


def _ensure_children(group):
    """确保文件夹包含 children 字段（兼容旧数据）。"""
    if 'children' not in group:
        group['children'] = []
    for ch in group['children']:
        _ensure_children(ch)


def get_groups():
    """获取文件夹树，返回 [{id, name, expanded, files, children}, ...]。"""
    ensure_drafts_dir()
    if os.path.exists(_GROUPS_FILE):
        try:
            with open(_GROUPS_FILE, 'r', encoding='utf-8') as f:
                groups = json.load(f)
            seen = set()
            deduped = []
            for g in groups:
                if g['id'] not in seen:
                    seen.add(g['id'])
                    _ensure_children(g)
                    deduped.append(g)
            return deduped
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_groups(groups):
    """保存文件夹列表。"""
    ensure_drafts_dir()
    with open(_GROUPS_FILE, 'w', encoding='utf-8') as f:
        json.dump(groups, f, ensure_ascii=False, indent=1)


def _find_group(groups, group_id):
    """递归查找文件夹，返回 (group, parent_list) 或 (None, None)。"""
    for g in groups:
        if g['id'] == group_id:
            return g, groups
        found, parent = _find_group(g.get('children', []), group_id)
        if found:
            return found, parent
    return None, None


def _collect_all_ids(groups):
    """递归收集所有文件夹 ID。"""
    ids = set()
    for g in groups:
        ids.add(g['id'])
        ids.update(_collect_all_ids(g.get('children', [])))
    return ids


def _remove_file_recursive(groups, filename):
    """从所有文件夹（含子文件夹）中递归移除文件。"""
    for g in groups:
        if filename in g['files']:
            g['files'].remove(filename)
        _remove_file_recursive(g.get('children', []), filename)


def create_group(name='新建文件夹', parent_id=None):
    """创建新文件夹。parent_id=None 时在顶层创建。"""
    groups = get_groups()
    gid = 'g_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    existing_ids = _collect_all_ids(groups)
    suffix = 0
    while gid in existing_ids:
        suffix += 1
        gid = 'g_' + datetime.now().strftime('%Y%m%d_%H%M%S') + f'_{suffix}'
    group = {'id': gid, 'name': name, 'expanded': True,
             'files': [], 'children': []}
    if parent_id:
        parent, _ = _find_group(groups, parent_id)
        if parent:
            parent['children'].insert(0, group)
        else:
            groups.insert(0, group)
    else:
        groups.insert(0, group)
    save_groups(groups)
    return group


def rename_group(group_id, new_name):
    """重命名文件夹。"""
    groups = get_groups()
    found, _ = _find_group(groups, group_id)
    if found:
        found['name'] = new_name
    save_groups(groups)


def delete_group(group_id):
    """删除文件夹（文稿和子文件夹变为未分组/顶层，不删除文稿文件）。"""
    groups = get_groups()
    found, parent_list = _find_group(groups, group_id)
    if found and parent_list is not None:
        parent_list.remove(found)
    save_groups(groups)


def toggle_group(group_id):
    """切换文件夹展开/折叠。"""
    groups = get_groups()
    found, _ = _find_group(groups, group_id)
    if found:
        found['expanded'] = not found['expanded']
    save_groups(groups)


def move_to_group(filename, group_id):
    """将文稿移入指定文件夹。group_id=None 时移到未分组。"""
    groups = get_groups()
    _remove_file_recursive(groups, filename)
    if group_id is not None:
        found, _ = _find_group(groups, group_id)
        if found:
            found['files'].append(filename)
    save_groups(groups)


def remove_from_group(filename):
    """将文稿从所有文件夹中递归移除（变为未分组）。"""
    groups = get_groups()
    _remove_file_recursive(groups, filename)
    save_groups(groups)


def move_group_into(group_id, target_parent_id):
    """将文件夹移入另一个文件夹。target_parent_id=None 移到顶层。
    不允许移入自身或其后代。"""
    groups = get_groups()
    if target_parent_id and _is_descendant_of(groups, group_id,
                                               target_parent_id):
        return
    found, parent_list = _find_group(groups, group_id)
    if not found:
        return
    parent_list.remove(found)
    if target_parent_id is None:
        groups.insert(0, found)
    else:
        target, _ = _find_group(groups, target_parent_id)
        if target:
            target['children'].insert(0, found)
        else:
            groups.insert(0, found)
    save_groups(groups)


def _is_descendant_of(groups, ancestor_id, check_id):
    """检查 check_id 是否是 ancestor_id 本身或其后代。"""
    if ancestor_id == check_id:
        return True
    found, _ = _find_group(groups, ancestor_id)
    if not found:
        return False
    return _find_group(found.get('children', []), check_id)[0] is not None


def get_grouped_filenames(groups=None):
    """递归返回所有已分组的文件名集合。"""
    if groups is None:
        groups = get_groups()
    result = set()
    for g in groups:
        result.update(g['files'])
        result.update(get_grouped_filenames(g.get('children', [])))
    return result


def reorder_group(group_id, parent_id, before_group_id):
    """在同一父级内重排文件夹顺序：将 group_id 移到 before_group_id 之前。
    before_group_id=None 则放到末尾。parent_id=None 操作顶层列表。"""
    groups = get_groups()
    if parent_id is None:
        siblings = groups
    else:
        parent, _ = _find_group(groups, parent_id)
        if not parent:
            return
        siblings = parent['children']
    found = None
    for g in siblings:
        if g['id'] == group_id:
            found = g
            break
    if not found:
        return
    siblings.remove(found)
    if before_group_id:
        for i, g in enumerate(siblings):
            if g['id'] == before_group_id:
                siblings.insert(i, found)
                break
        else:
            siblings.append(found)
    else:
        siblings.append(found)
    save_groups(groups)


def reorder_file_in_group(filename, group_id, before_filename):
    """在文件夹内重排文稿顺序：将 filename 移到 before_filename 之前。
    before_filename=None 则放到末尾。group_id=None 操作未分组全局排序。"""
    if group_id is None:
        # 未分组：操作 _order.json
        order = get_drafts_order()
        all_drafts = [d['filename'] for d in list_drafts()]
        # 确保 order 包含所有未分组文件
        grouped = get_grouped_filenames()
        ungrouped = [fn for fn in all_drafts if fn not in grouped]
        # 建立有序列表
        existing = [fn for fn in order if fn in ungrouped]
        new_fns = [fn for fn in ungrouped if fn not in existing]
        full = new_fns + existing
        if filename not in full:
            return
        full.remove(filename)
        if before_filename and before_filename in full:
            idx = full.index(before_filename)
            full.insert(idx, filename)
        else:
            full.append(filename)
        save_drafts_order(full)
    else:
        groups = get_groups()
        found, _ = _find_group(groups, group_id)
        if not found or filename not in found['files']:
            return
        found['files'].remove(filename)
        if before_filename and before_filename in found['files']:
            idx = found['files'].index(before_filename)
            found['files'].insert(idx, filename)
        else:
            found['files'].append(filename)
        save_groups(groups)
