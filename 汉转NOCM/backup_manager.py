"""Portable backup and guarded restore for user-owned application data."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import datetime

from app_version import BACKUP_SCHEMA_VERSION, __version__, get_app_dir
from atomic_io import write_bytes_atomic
from draft_io import DRAFTS_DIR, ensure_drafts_dir
from nocm_transcriber import get_scheme_dir


_PREFERENCE_FILES = ('.theme_pref', '.scheme_pref', '.ui_state.json',
                     'changed_chars.json')


def default_backup_dir():
    path = os.path.join(get_app_dir(), 'backups')
    os.makedirs(path, exist_ok=True)
    return path


def create_backup(path=None, reason='manual'):
    """Create a complete ZIP backup and return metadata about it."""
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if not path:
        path = os.path.join(default_backup_dir(), f'汉转PBOC备份_{stamp}.zip')
    path = os.path.abspath(path)
    if not path.lower().endswith('.zip'):
        path += '.zip'
    os.makedirs(os.path.dirname(path), exist_ok=True)

    entries = []
    ensure_drafts_dir()
    for root, _dirs, files in os.walk(DRAFTS_DIR):
        for filename in files:
            if not filename.endswith('.json'):
                continue
            source = os.path.join(root, filename)
            relative = os.path.relpath(source, DRAFTS_DIR).replace('\\', '/')
            entries.append((source, f'drafts/{relative}'))
    scheme_dir = get_scheme_dir()
    if os.path.isdir(scheme_dir):
        for filename in os.listdir(scheme_dir):
            if filename.endswith('.json'):
                entries.append((os.path.join(scheme_dir, filename),
                                f'schemes/{filename}'))
    for filename in _PREFERENCE_FILES:
        source = os.path.join(get_app_dir(), filename)
        if os.path.isfile(source):
            entries.append((source, f'preferences/{filename}'))

    manifest = {
        'backup_schema_version': BACKUP_SCHEMA_VERSION,
        'app_version': __version__,
        'created_at': datetime.now().isoformat(),
        'reason': reason,
        'files': len(entries),
    }
    fd, temp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + '.', suffix='.tmp',
        dir=os.path.dirname(path))
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            for source, archive_name in entries:
                archive.write(source, archive_name)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return {'path': path, 'files': len(entries), 'manifest': manifest}


def inspect_backup(path):
    """Validate a backup without modifying application data."""
    path = os.path.abspath(path)
    with zipfile.ZipFile(path, 'r') as archive:
        try:
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('备份包缺少有效的 manifest.json') from exc
        version = int(manifest.get('backup_schema_version', 0) or 0)
        if version <= 0 or version > BACKUP_SCHEMA_VERSION:
            raise ValueError(f'不支持的备份格式版本：{version}')
        allowed = []
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            if info.is_dir() or name == 'manifest.json':
                continue
            parts = [part for part in name.split('/') if part]
            if '..' in parts or name.startswith('/'):
                raise ValueError('备份包包含不安全路径')
            if not (name.startswith('drafts/')
                    or name.startswith('schemes/')
                    or name.startswith('preferences/')):
                raise ValueError(f'备份包包含未知文件：{name}')
            if (name.startswith('preferences/')
                    and os.path.basename(name) not in _PREFERENCE_FILES):
                raise ValueError(f'备份包包含不允许的偏好文件：{name}')
            if (not name.startswith('preferences/')
                    and not name.endswith('.json')):
                raise ValueError(f'备份包包含不允许的文件：{name}')
            allowed.append(name)
    return {'path': path, 'manifest': manifest, 'files': allowed}


def restore_backup(path, replace=True):
    """Restore a validated backup after creating a safety snapshot."""
    inspected = inspect_backup(path)
    safety = create_backup(reason='pre_restore')
    if replace:
        _clear_json_files(DRAFTS_DIR)
        _clear_json_files(get_scheme_dir())
    restored = 0
    with zipfile.ZipFile(inspected['path'], 'r') as archive:
        for name in inspected['files']:
            content = archive.read(name)
            if name.startswith('drafts/'):
                relative = name[len('drafts/'):]
                target = _safe_restore_target(DRAFTS_DIR, relative)
            elif name.startswith('schemes/'):
                target = os.path.join(get_scheme_dir(),
                                      os.path.basename(name))
            else:
                filename = os.path.basename(name)
                if filename not in _PREFERENCE_FILES:
                    continue
                target = os.path.join(get_app_dir(), filename)
            write_bytes_atomic(target, content)
            restored += 1
    return {
        'ok': True,
        'restored': restored,
        'safety_backup': safety['path'],
        'manifest': inspected['manifest'],
    }


def _safe_restore_target(root, relative):
    root = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root, *relative.split('/')))
    if os.path.commonpath([root, target]) != root:
        raise ValueError('备份包包含越界路径')
    return target


def _clear_json_files(root):
    if not os.path.isdir(root):
        return
    for directory, _dirs, files in os.walk(root):
        for filename in files:
            if filename.endswith('.json'):
                try:
                    os.remove(os.path.join(directory, filename))
                except OSError:
                    pass
