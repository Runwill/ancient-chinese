"""Merge drafts and folder metadata from an older application library."""

from __future__ import annotations

import json
import os
from datetime import datetime

from backup_manager import create_backup
from draft_io import (DRAFTS_DIR, _DRAFT_HISTORY_DIR, _DRAFTS_ORDER_FILE,
                      _DRAFTS_RECENT_FILE, ensure_drafts_dir, get_drafts_order,
                      load_json, migrate_draft_data, save_drafts_order,
                      save_json)
from folder_manager import get_groups, save_groups


def find_legacy_drafts_dir(selected_path):
    """Resolve either an old app directory or its drafts directory."""
    selected_path = os.path.abspath(str(selected_path or ''))
    candidates = [selected_path, os.path.join(selected_path, 'drafts')]
    for candidate in candidates:
        if not os.path.isdir(candidate):
            continue
        if any(_is_draft_file(candidate, name)
               for name in os.listdir(candidate)):
            return candidate
        if os.path.isfile(os.path.join(candidate, '_groups.json')):
            return candidate
    raise ValueError('所选目录中没有找到旧版草稿资料库')


def import_legacy_library(selected_path):
    """Merge an old draft library and return a detailed import report."""
    source_dir = find_legacy_drafts_dir(selected_path)
    if os.path.normcase(source_dir) == os.path.normcase(os.path.abspath(DRAFTS_DIR)):
        raise ValueError('不能从当前资料库导入自身')
    ensure_drafts_dir()
    safety = create_backup(reason='pre_library_import')
    report = {
        'source': source_dir, 'imported': 0, 'skipped': 0,
        'renamed': 0, 'history': 0, 'errors': [],
        'safety_backup': safety['path'],
    }
    file_map = {}
    for filename in sorted(os.listdir(source_dir)):
        if not _is_draft_file(source_dir, filename):
            continue
        source = os.path.join(source_dir, filename)
        try:
            data = _load_json_strict(source)
            data, _changed = migrate_draft_data(data)
            target_name, status = _target_filename(filename, data)
            file_map[filename] = target_name
            if status == 'skip':
                report['skipped'] += 1
                continue
            if target_name != filename:
                report['renamed'] += 1
            data['imported_at'] = datetime.now().isoformat()
            data['imported_from'] = source_dir
            save_json(os.path.join(DRAFTS_DIR, target_name), data)
            report['imported'] += 1
            report['history'] += _import_history(
                source_dir, filename, target_name)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report['errors'].append(f'{filename}: {exc}')

    _merge_groups(source_dir, file_map)
    _merge_order(source_dir, file_map)
    _merge_recent(source_dir, file_map)
    return report


def _is_draft_file(directory, filename):
    if filename.startswith('_') or not filename.endswith('.json'):
        return False
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        return False
    data = load_json(path)
    return isinstance(data, dict) and 'buffer' in data


def _load_json_strict(path):
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)


def _target_filename(filename, incoming):
    target = os.path.join(DRAFTS_DIR, filename)
    if not os.path.exists(target):
        return filename, 'new'
    existing = load_json(target)
    if _draft_signature(existing) == _draft_signature(incoming):
        return filename, 'skip'
    stem = filename[:-5]
    candidate = f'{stem}_imported.json'
    suffix = 2
    while os.path.exists(os.path.join(DRAFTS_DIR, candidate)):
        candidate = f'{stem}_imported_{suffix}.json'
        suffix += 1
    return candidate, 'renamed'


def _draft_signature(data):
    if not isinstance(data, dict):
        return None
    return json.dumps({
        'buffer': data.get('buffer'),
        'cell_info': data.get('cell_info'),
        'name': data.get('name'),
    }, ensure_ascii=False, sort_keys=True)


def _import_history(source_dir, old_filename, new_filename):
    source = os.path.join(source_dir, '_history', old_filename[:-5])
    if not os.path.isdir(source):
        return 0
    target = os.path.join(_DRAFT_HISTORY_DIR, new_filename[:-5])
    os.makedirs(target, exist_ok=True)
    count = 0
    for filename in sorted(os.listdir(source)):
        if not filename.endswith('.json'):
            continue
        try:
            data = _load_json_strict(os.path.join(source, filename))
            data, _changed = migrate_draft_data(data)
            target_name = filename
            suffix = 2
            while os.path.exists(os.path.join(target, target_name)):
                target_name = f'{filename[:-5]}_{suffix}.json'
                suffix += 1
            save_json(os.path.join(target, target_name), data)
            count += 1
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return count


def _merge_groups(source_dir, file_map):
    imported = load_json(os.path.join(source_dir, '_groups.json'), [])
    if not isinstance(imported, list):
        return
    existing = get_groups()
    existing_ids = _group_ids(existing)

    def remap(group):
        group = dict(group)
        original_id = str(group.get('id') or 'imported_group')
        candidate = original_id
        suffix = 2
        while candidate in existing_ids:
            candidate = f'{original_id}_imported_{suffix}'
            suffix += 1
        existing_ids.add(candidate)
        group['id'] = candidate
        group['files'] = [file_map[name] for name in group.get('files', [])
                          if name in file_map]
        group['children'] = [remap(child)
                             for child in group.get('children', [])]
        group.setdefault('expanded', True)
        return group

    existing.extend(remap(group) for group in imported)
    save_groups(existing)


def _group_ids(groups):
    result = set()
    for group in groups:
        result.add(str(group.get('id')))
        result.update(_group_ids(group.get('children', [])))
    return result


def _merge_order(source_dir, file_map):
    imported = load_json(os.path.join(source_dir, '_order.json'), [])
    current = get_drafts_order()
    for filename in imported if isinstance(imported, list) else []:
        mapped = file_map.get(filename)
        if mapped and mapped not in current:
            current.append(mapped)
    for mapped in file_map.values():
        if mapped not in current:
            current.append(mapped)
    save_drafts_order(current)


def _merge_recent(source_dir, file_map):
    imported = load_json(os.path.join(source_dir, '_recent.json'), [])
    current = load_json(_DRAFTS_RECENT_FILE, [])
    additions = [file_map[name] for name in imported
                 if name in file_map and file_map[name] not in current]
    save_json(_DRAFTS_RECENT_FILE, (additions + current)[:12])
