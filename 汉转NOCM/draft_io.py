"""文稿管理：文稿的读写、列出、删除、排序等文件 I/O 操作。"""

import json
import os
import sys
import re
import copy
from datetime import datetime

from app_version import DRAFT_SCHEMA_VERSION, __version__, get_app_dir
from atomic_io import save_json_atomic

# PyInstaller exe 时用 exe 所在目录，源码运行时用脚本所在目录
_BASE_DIR = get_app_dir()

DRAFTS_DIR = os.path.join(_BASE_DIR, 'drafts')
_DRAFTS_ORDER_FILE = os.path.join(DRAFTS_DIR, '_order.json')
_DRAFTS_RECENT_FILE = os.path.join(DRAFTS_DIR, '_recent.json')
_DRAFT_HISTORY_DIR = os.path.join(DRAFTS_DIR, '_history')
_HISTORY_LIMIT = 30
_AUTO_HISTORY_INTERVAL_SECONDS = 300


def ensure_drafts_dir():
    os.makedirs(DRAFTS_DIR, exist_ok=True)


def load_json(path, default=None):
    """安全读取 JSON 文件，失败时返回 default。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return default


def save_json(path, data):
    """原子写入 JSON 文件，避免异常退出留下半截文件。"""
    save_json_atomic(path, data, indent=1)


def _safe_filename(filename):
    filename = os.path.basename(str(filename or ''))
    if not filename.endswith('.json'):
        raise ValueError('无效的文稿文件名')
    return filename


def migrate_draft_data(data):
    """Upgrade an in-memory draft and return ``(data, changed)``."""
    if not isinstance(data, dict):
        raise ValueError('文稿数据不是对象')
    version = int(data.get('schema_version', 1) or 1)
    if version > DRAFT_SCHEMA_VERSION:
        raise ValueError(f'文稿格式版本 {version} 高于当前支持版本')
    changed = version < DRAFT_SCHEMA_VERSION
    data.setdefault('buffer', [[]])
    data.setdefault('cell_info', [[] for _ in data['buffer']])
    data.setdefault('editor_state', {
        'cursor': [0, 0], 'selection': None, 'scroll_top': 0})
    data['schema_version'] = DRAFT_SCHEMA_VERSION
    if changed:
        data['migrated_by'] = __version__
    return data, changed


def load_draft_data(filename, persist_migration=True):
    """Load and migrate a draft's complete serialized data."""
    filename = _safe_filename(filename)
    path = os.path.join(DRAFTS_DIR, filename)
    data = load_json(path)
    if data is None:
        raise FileNotFoundError(filename)
    data, changed = migrate_draft_data(data)
    if changed and persist_migration:
        save_json(path, data)
    return data


def get_drafts_order():
    """获取文稿排序列表。"""
    ensure_drafts_dir()
    return load_json(_DRAFTS_ORDER_FILE, [])


def save_drafts_order(order):
    """保存文稿排序列表。"""
    ensure_drafts_dir()
    save_json(_DRAFTS_ORDER_FILE, order)


def list_drafts():
    """列出所有已保存的文稿，按自定义顺序排列（新文稿在前）。"""
    ensure_drafts_dir()
    drafts = []
    for fn in os.listdir(DRAFTS_DIR):
        if not fn.endswith('.json') or fn.startswith('_'):
            continue
        try:
            data = load_draft_data(fn)
        except (OSError, ValueError):
            continue
        drafts.append({
            'filename': fn,
            'name': data.get('name', fn[:-5]),
            'modified': data.get('modified', ''),
            'preview': data.get('preview', ''),
            'unselected_polyphonic': count_unselected_polyphonic(data),
            'manually_completed': bool(data.get('manually_completed')),
        })
    order = get_drafts_order()
    new_drafts = [d for d in drafts if d['filename'] not in order]
    ordered_drafts = [d for d in drafts if d['filename'] in order]
    new_drafts.sort(key=lambda d: d['modified'], reverse=True)
    ordered_drafts.sort(key=lambda d: order.index(d['filename']))
    return new_drafts + ordered_drafts


def count_unselected_polyphonic(data):
    """Count polyphonic cells whose reading has never been selected."""
    total = 0
    for row in (data.get('cell_info') or []):
        for info in row:
            if (isinstance(info, dict) and info.get('is_poly')
                    and info.get('selected', 'none') == 'none'):
                total += 1
    return total


def save_draft(filename, name, buffer, cell_info, editor_state=None,
               create_history=False):
    """保存文稿到文件，返回实际使用的文件名。"""
    ensure_drafts_dir()
    now = datetime.now()
    existing = None
    if filename is None:
        base = now.strftime('%Y%m%d_%H%M%S')
        filename = base + '.json'
        suffix = 1
        while os.path.exists(os.path.join(DRAFTS_DIR, filename)):
            filename = f'{base}_{suffix}.json'
            suffix += 1
    else:
        filename = _safe_filename(filename)
        try:
            existing = load_draft_data(filename)
        except (OSError, ValueError):
            existing = None
    if existing:
        _save_history_snapshot(filename, existing, force=create_history)
    if name is None:
        if existing and existing.get('name'):
            name = existing['name']
        else:
            raw = ''.join(buffer[0]) if buffer[0] else ''
            m = re.match(
                r"[^\s，。！？；：、「」『』【】（）\u201c\u201d\u2018\u2019',\.!\?;:\(\)\[\]\"'…—―．]+", raw)
            name = m.group()[:20] if m else '未命名文稿'

    serialized_info = []
    for row in cell_info:
        serialized_row = []
        for info in row:
            serialized_row.append({
                'phonetic': info['phonetic'],
                'is_poly': bool(info.get('is_poly')),
                'selected': info.get('selected', 'none'),
                'manual_hl': bool(info.get('manual_hl')),
                'data_revision': info.get('data_revision'),
                'update_reviews': copy.deepcopy(
                    info.get('update_reviews') or {}),
            })
        serialized_info.append(serialized_row)

    preview = ''.join(ch for line in buffer for ch in line)[:30]

    data = {
        'schema_version': DRAFT_SCHEMA_VERSION,
        'app_version': __version__,
        'name': name,
        'created': (existing or {}).get('created', now.isoformat()),
        'modified': now.isoformat(),
        'preview': preview,
        'manually_completed': bool(
            (existing or {}).get('manually_completed', False)),
        'buffer': buffer,
        'cell_info': serialized_info,
        'editor_state': _normalize_editor_state(
            editor_state or (existing or {}).get('editor_state')),
    }
    save_json(os.path.join(DRAFTS_DIR, filename), data)
    mark_draft_recent(filename)
    return filename


def load_draft(filename, mapping, include_state=False):
    """从文件加载文稿，可选返回保存的编辑器视图状态。"""
    data = load_draft_data(filename)
    buffer = data['buffer']
    loaded_info = data['cell_info']
    cell_info = []
    for li, row_chars in enumerate(buffer):
        row_info = loaded_info[li] if li < len(loaded_info) else []
        rebuilt = []
        for ci, ch in enumerate(row_chars):
            info = row_info[ci] if ci < len(row_info) else {}
            opts = mapping.get(ch)
            is_poly = bool(info.get('is_poly', opts and len(opts) > 1))
            first = opts[0] if opts else ch
            fallback_phon = (first.get('phonetic', ch)
                             if isinstance(first, dict) else str(first))
            rebuilt.append({
                'phonetic': info.get('phonetic', fallback_phon),
                'options': opts if is_poly and opts and len(opts) > 1 else None,
                'is_poly': is_poly,
                'selected': info.get('selected', 'none'),
                'manual_hl': bool(info.get('manual_hl', False)),
                'data_revision': info.get('data_revision'),
                'update_reviews': copy.deepcopy(
                    info.get('update_reviews') or {}),
            })
        cell_info.append(rebuilt)
    mark_draft_recent(filename)
    if include_state:
        return buffer, cell_info, _normalize_editor_state(data.get('editor_state'))
    return buffer, cell_info


def _normalize_editor_state(state):
    state = state if isinstance(state, dict) else {}
    cursor = state.get('cursor')
    if not (isinstance(cursor, (list, tuple)) and len(cursor) == 2):
        cursor = [0, 0]
    selection = state.get('selection')
    if not (isinstance(selection, (list, tuple)) and len(selection) == 2):
        selection = None
    return {
        'cursor': [max(0, int(cursor[0])), max(0, int(cursor[1]))],
        'selection': selection,
        'scroll_top': max(0, int(state.get('scroll_top', 0) or 0)),
    }


def update_draft_editor_state(filename, editor_state):
    """Persist cursor/selection/scroll without changing modified time."""
    if not filename:
        return
    try:
        data = load_draft_data(filename)
    except (OSError, ValueError):
        return
    normalized = _normalize_editor_state(editor_state)
    if data.get('editor_state') != normalized:
        data['editor_state'] = normalized
        save_json(os.path.join(DRAFTS_DIR, _safe_filename(filename)), data)


def _history_folder(filename):
    return os.path.join(_DRAFT_HISTORY_DIR, _safe_filename(filename)[:-5])


def _save_history_snapshot(filename, data, force=False):
    """Save a bounded snapshot before overwriting a draft."""
    folder = _history_folder(filename)
    os.makedirs(folder, exist_ok=True)
    snapshots = sorted(
        (name for name in os.listdir(folder) if name.endswith('.json')),
        reverse=True)
    if not force and snapshots:
        newest = os.path.join(folder, snapshots[0])
        try:
            age = datetime.now().timestamp() - os.path.getmtime(newest)
            if age < _AUTO_HISTORY_INTERVAL_SECONDS:
                return
        except OSError:
            pass
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    save_json(os.path.join(folder, f'{stamp}.json'), data)
    snapshots = sorted(
        (name for name in os.listdir(folder) if name.endswith('.json')),
        reverse=True)
    for old_name in snapshots[_HISTORY_LIMIT:]:
        try:
            os.remove(os.path.join(folder, old_name))
        except OSError:
            pass


def list_draft_history(filename):
    folder = _history_folder(filename)
    if not os.path.isdir(folder):
        return []
    items = []
    for snapshot in sorted(os.listdir(folder), reverse=True):
        if not snapshot.endswith('.json'):
            continue
        data = load_json(os.path.join(folder, snapshot), {})
        items.append({
            'id': snapshot,
            'name': data.get('name', '未命名文稿'),
            'modified': data.get('modified', ''),
            'preview': data.get('preview', ''),
        })
    return items


def restore_draft_history(filename, snapshot_id):
    filename = _safe_filename(filename)
    snapshot_id = os.path.basename(str(snapshot_id or ''))
    if not snapshot_id.endswith('.json'):
        raise ValueError('无效的历史版本')
    current = load_draft_data(filename)
    _save_history_snapshot(filename, current, force=True)
    path = os.path.join(_history_folder(filename), snapshot_id)
    restored = load_json(path)
    if restored is None:
        raise FileNotFoundError(snapshot_id)
    restored, _changed = migrate_draft_data(restored)
    restored['modified'] = datetime.now().isoformat()
    restored['restored_from'] = snapshot_id
    save_json(os.path.join(DRAFTS_DIR, filename), restored)
    mark_draft_recent(filename)
    return filename


def mark_draft_recent(filename):
    filename = _safe_filename(filename)
    recent = load_json(_DRAFTS_RECENT_FILE, [])
    if recent and recent[0] == filename:
        return
    recent = [item for item in recent if item != filename]
    recent.insert(0, filename)
    save_json(_DRAFTS_RECENT_FILE, recent[:12])


def list_recent_drafts(limit=5):
    names = load_json(_DRAFTS_RECENT_FILE, [])
    by_name = {item['filename']: item for item in list_drafts()}
    return [by_name[name] for name in names if name in by_name][:limit]


def delete_draft(filename):
    """删除文稿文件。"""
    try:
        os.remove(os.path.join(DRAFTS_DIR, _safe_filename(filename)))
    except OSError:
        pass


def rename_draft(filename, new_name):
    """重命名文稿。"""
    fp = os.path.join(DRAFTS_DIR, _safe_filename(filename))
    try:
        data = load_draft_data(filename)
    except (OSError, ValueError):
        return
    data['name'] = new_name
    data['modified'] = datetime.now().isoformat()
    save_json(fp, data)


def set_draft_completed(filename, completed):
    """Set or clear the user's explicit completion marker."""
    filename = _safe_filename(filename)
    data = load_draft_data(filename)
    data['manually_completed'] = bool(completed)
    save_json(os.path.join(DRAFTS_DIR, filename), data)


def get_draft_name(filename):
    """读取文稿显示名称。"""
    try:
        data = load_draft_data(filename)
    except (OSError, ValueError):
        data = None
    return data.get('name', filename) if data else filename


def draft_has_stale_chars(filename, changed_chars):
    """检查文稿是否包含读音变化的汉字（快速扫描，不完整加载）。"""
    if not changed_chars:
        return False
    data = load_json(os.path.join(DRAFTS_DIR, filename))
    if not data or 'buffer' not in data:
        return False
    for row in data['buffer']:
        for ch in row:
            if ch in changed_chars:
                return True
    return False


def draft_has_pending_updates(filename, events_by_char):
    """Check persisted per-cell revisions without rebuilding the whole editor."""
    if not events_by_char:
        return False
    data = load_json(os.path.join(DRAFTS_DIR, filename))
    if not data or 'buffer' not in data:
        return False
    info_lines = data.get('cell_info') or []
    for li, row in enumerate(data['buffer']):
        infos = info_lines[li] if li < len(info_lines) else []
        for ci, char in enumerate(row):
            info = infos[ci] if ci < len(infos) else {}
            phonetic = info.get('phonetic', char)
            revision = info.get('data_revision')
            reviews = info.get('update_reviews') or {}
            for event in events_by_char.get(char, []):
                if revision and event['timestamp'] <= revision:
                    continue
                review = reviews.get(event['id']) or {}
                if review.get('status') in (
                        'accepted_new', 'kept_current', 'reviewed'):
                    continue
                if (review.get('status') == 'reopened'
                        or phonetic in event.get('removed', [])):
                    return True
    return False
