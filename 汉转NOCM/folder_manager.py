"""文件夹（分组）管理：文件夹树的增删改查与嵌套操作。"""

import json
import os
from datetime import datetime

from draft_io import (ensure_drafts_dir, get_drafts_order, save_drafts_order,
                      list_drafts)

_DRAFTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'drafts')
_GROUPS_FILE = os.path.join(_DRAFTS_DIR, '_groups.json')


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
