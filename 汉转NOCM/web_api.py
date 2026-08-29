"""Python bridge used by the HTML/WebView user interface."""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import sys
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from app_version import CHANGELOG, __version__, get_app_dir
from atomic_io import save_json_atomic, write_bytes_atomic
from backup_manager import (create_backup, default_backup_dir, inspect_backup,
                            restore_backup)
from constants import find_bracket_ranges, get_theme, in_bracket, set_theme
from data_loader import (download_and_update, get_current_data_revision,
                         get_data_change_batches, get_data_change_entries,
                         get_data_dir, get_reading_change_events,
                         load_map_from_json_gz)
from draft_io import (delete_draft, draft_has_pending_updates, get_draft_name,
                      list_draft_history, list_drafts, list_recent_drafts,
                      load_draft, rename_draft, restore_draft_history,
                      save_draft, set_draft_completed,
                      update_draft_editor_state)
from editor_buffer import EditorBuffer
from folder_manager import (create_group, delete_group, get_groups,
                            move_group_into, move_to_group, rename_group,
                            reorder_file_in_group, reorder_group, toggle_group)
from library_import import import_legacy_library
from nocm_phonology import DEFAULT_TONE_ORDER, consume_suffix
from nocm_transcriber import (DEFAULT_SCHEME_ID, NocmTranscriber, diff_schemes,
                              get_scheme_dir, list_schemes,
                              load_preferred_scheme_id, load_scheme,
                              migrate_scheme_data, normalize_scheme_id,
                              save_preferred_scheme_id, save_scheme,
                              save_scheme_order,
                              validate_scheme)
from update_manager import (check_for_updates, diagnostic_info, download_update,
                            launch_windows_update, validate_downloaded_update)
from runtime_log import clear_runtime_logs, get_runtime_logs


_PUNCT_TO_NEWLINE = '，。！？；：、,!?;:…—○'
_PUNCT_DOUBLE_NEWLINE = '。'
_BRACKET_CONTROL_LINE = re.compile(r'^\[[^\r\n]*\]$')
_NORMAL_NON_HAN = re.compile(
    r'''[\sa-zA-Z0-9，。！？；：、「」『』【】（）《》〈〉〔〕“”‘’'''
    r''',\.!\?;:\(\)\[\]\{\}"'`~@#\$%\^&\*\-_\=\+\\|/<>'''
    r'''…—―─·•◆◇○●◎■□▲△▼▽★☆※→←↑↓↔§¶†‡°℃\u3000-\u303F]''')
_APP_WINDOW = None
_UI_STATE_PATH = os.path.join(get_app_dir(), '.ui_state.json')
_UI_STATE_LOCK = threading.RLock()
_EXPORT_OPTION_KEYS = {
    'punct_split',
    'clean_line_breaks',
    'ignore_bracket_control_lines',
    'remove_pharyngeal',
    'remove_tones',
    'remove_glottal_tone',
    'extra_h_voiceless_sonorant',
    'entry_before_glottal',
    'departing_before_glottal',
}


def _load_ui_preferences():
    with _UI_STATE_LOCK:
        try:
            with open(_UI_STATE_PATH, 'r', encoding='utf-8') as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}


def _save_ui_preferences(preferences):
    with _UI_STATE_LOCK:
        save_json_atomic(
            _UI_STATE_PATH, preferences, indent=2, newline=True)


def _set_ui_state_value(key, value):
    with _UI_STATE_LOCK:
        preferences = _load_ui_preferences()
        if value is None:
            preferences.pop(key, None)
        else:
            preferences[key] = value
        _save_ui_preferences(preferences)


def _draft_library_snapshot():
    """Return draft lists annotated with phonology-update warnings."""
    drafts = list_drafts()
    recent = list_recent_drafts()
    reading_events = get_reading_change_events()
    stale_by_filename = {}
    for draft in drafts:
        filename = draft.get('filename')
        try:
            stale = bool(filename and draft_has_pending_updates(
                filename, reading_events))
        except (OSError, ValueError):
            stale = False
        draft['stale'] = stale
        if filename:
            stale_by_filename[filename] = stale
    for draft in recent:
        draft['stale'] = stale_by_filename.get(
            draft.get('filename'), False)
    return drafts, recent


class WebApi:
    """Thread-safe application facade exposed to JavaScript by pywebview."""

    def __init__(self, mapping=None):
        self.mapping = mapping
        self.data_revision = (
            get_current_data_revision() if mapping
            else '0000-00-00 00:00:00')
        self.reading_events = get_reading_change_events() if mapping else {}
        self.buf: Optional[EditorBuffer] = (
            EditorBuffer(mapping, self.data_revision) if mapping else None)
        self.current_draft: Optional[str] = None
        self.export_scheme_id = load_preferred_scheme_id()
        self.scroll_top = 0
        self._window_maximized = False
        self._lock = threading.RLock()
        self._startup = {
            'phase': 'ready' if mapping else 'waiting',
            'message': '准备就绪' if mapping else '正在准备数据...',
            'progress': 100 if mapping else 0,
            'step': 6 if mapping else 0,
            'step_count': 6,
            'detail': '启动完成' if mapping else '等待后端开始初始化',
            'indeterminate': False,
            'error': None,
            'details': None,
        }
        self._startup_thread = None
        self._startup_result = None
        self._update_download = {
            'phase': 'idle', 'message': '', 'progress': 0,
            'downloaded': 0, 'total': 0, 'result': None, 'error': None,
        }
        self._update_check = {
            'phase': 'idle', 'message': '', 'result': None, 'error': None,
        }

    def set_window(self, window):
        global _APP_WINDOW
        _APP_WINDOW = window
        window.events.maximized += lambda: self._set_window_maximized(True)
        window.events.restored += lambda: self._set_window_maximized(False)

    def _set_window_maximized(self, maximized):
        self._window_maximized = bool(maximized)
        if _APP_WINDOW and _APP_WINDOW.events.loaded.is_set():
            try:
                _APP_WINDOW.run_js(
                    f'window.setDesktopWindowMaximized?.({str(bool(maximized)).lower()})')
            except Exception:
                pass

    # Startup -------------------------------------------------------------

    def start_initialize(self):
        """Start initialization without blocking WebView progress polling."""
        with self._lock:
            if self.buf is not None:
                return dict(self._startup)
            if self._startup_thread and self._startup_thread.is_alive():
                return dict(self._startup)
            self._startup_result = None
            self._startup.update(
                phase='loading', message='正在检查基础音标数据...',
                progress=4, step=1, step_count=6,
                detail='base.json.gz · 正在连接数据源',
                indeterminate=True, error=None, details=None)
            self._startup_thread = threading.Thread(
                target=self.initialize, name='pboc-startup', daemon=True)
            thread = self._startup_thread
        thread.start()
        return self.get_startup_status()

    def initialize(self):
        """Load/update phonology data and return the first complete snapshot."""
        with self._lock:
            if self.buf is not None:
                return self._startup_result or self.get_state()
            self._startup.update(
                phase='loading', message='正在检查基础音标数据...',
                progress=5, step=1, step_count=6,
                detail='base.json.gz · 正在确认是否需要更新',
                indeterminate=True)
        try:
            download_report = download_and_update(
                on_status=self._set_startup_message,
                on_progress=self._set_startup_progress,
            )
            mapping = load_map_from_json_gz(
                on_status=self._set_mapping_stage,
                on_progress=self._set_mapping_progress)
            if mapping is None:
                error = RuntimeError(
                    '无法加载音节数据，请检查数据文件或网络连接。')
                error.details = self._startup_error_report(download_report)
                raise error
            with self._lock:
                self.mapping = mapping
                self.data_revision = get_current_data_revision()
                self._startup.update(
                    phase='loading', message='正在读取数据变更记录...',
                    progress=91, step=4,
                    detail='识别需要重新确认读音的位置',
                    indeterminate=True)
                self.reading_events = get_reading_change_events()
                self.buf = EditorBuffer(mapping, self.data_revision)
                self._startup.update(
                    phase='loading', message='正在恢复上次文稿...',
                    progress=95, step=5,
                    detail='恢复光标、选择和滚动位置',
                    indeterminate=False)
                self._restore_startup_draft()
                self._startup.update(
                    phase='loading', message='正在准备应用界面...',
                    progress=98, step=6,
                    detail='整理文稿库、方案和界面设置')
                result = self.get_state()
                self._startup_result = result
                self._startup.update(
                    phase='ready', message='准备就绪', progress=100,
                    step=6, detail='启动完成', indeterminate=False,
                    error=None, details=None)
            return result
        except Exception as exc:
            with self._lock:
                self._startup.update(
                    phase='error', message='启动失败', error=str(exc),
                    indeterminate=False,
                    details=getattr(
                        exc, 'details', self._startup_error_report(None, exc)))
            return {'ok': False, 'startup': dict(self._startup)}

    @staticmethod
    def _startup_error_report(download_report=None, exception=None):
        data_dir = get_data_dir()
        lines = [
            f'程序版本: {__version__}',
            f'数据目录: {data_dir}',
        ]
        for filename in ('base.json.gz', 'extra.json.gz'):
            path = os.path.join(data_dir, filename)
            try:
                size = os.path.getsize(path)
                state = f'存在，{size} bytes'
            except OSError:
                state = '不存在或无法读取'
            lines.append(f'{filename}: {state}')
        errors = (download_report or {}).get('errors', [])
        if errors:
            lines.append('')
            lines.append('自动下载错误:')
            for item in errors:
                lines.extend([
                    f"- 文件: {item.get('filename', '未知')}",
                    f"  地址: {item.get('url', '')}",
                    f"  异常: {item.get('type', 'Error')}: "
                    f"{item.get('message', '未知错误')}",
                ])
        elif exception is not None:
            lines.extend([
                '', '启动异常:',
                f'- {type(exception).__name__}: {exception}',
            ])
        else:
            lines.extend([
                '', '自动下载未报告网络错误；本地数据可能损坏或内容为空。',
            ])
        return '\n'.join(lines)

    def get_startup_status(self):
        with self._lock:
            return dict(self._startup)

    def get_backend_readiness(self):
        """Desktop bridge is ready when this method can be called."""
        return {'ready': True, 'error': None}

    def _set_startup_message(self, message):
        with self._lock:
            raw = str(message)
            filename = ('base.json.gz' if 'base.json.gz' in raw else
                        'extra.json.gz' if 'extra.json.gz' in raw else '')
            if filename:
                base = filename == 'base.json.gz'
                label = '基础音标数据' if base else '扩展注释数据'
                step = 1 if base else 2
                floor = 5 if base else 31
                if '正在检查' in raw:
                    message = f'正在检查{label}...'
                    detail = f'{filename} · 正在确认是否需要更新'
                    indeterminate = True
                elif '正在下载' in raw:
                    message = f'正在下载{label}...'
                    detail = f'{filename} · 正在连接数据源'
                    indeterminate = True
                elif '已是最新' in raw:
                    message = f'{label}已是最新'
                    detail = f'{filename} · 使用本地文件'
                    indeterminate = False
                elif '下载失败' in raw:
                    message = f'{label}联网更新失败'
                    detail = f'{filename} · 将尝试使用已有本地文件'
                    indeterminate = False
                else:
                    message = f'正在处理{label}...'
                    detail = raw
                    indeterminate = False
                self._startup.update(
                    message=message, detail=detail, step=step,
                    progress=max(self._startup['progress'], floor),
                    indeterminate=indeterminate)
            else:
                self._startup.update(message=raw, detail=raw)

    def _set_startup_progress(self, progress, _name=None):
        with self._lock:
            if progress >= 0:
                base = _name == 'base.json.gz'
                start, span = (5, 25) if base else (31, 24)
                pct = max(0, min(100, int(progress)))
                label = '基础音标数据' if base else '扩展注释数据'
                self._startup.update(
                    message=f'正在下载{label}...',
                    progress=start + pct * span // 100,
                    step=1 if base else 2,
                    detail=f'{_name} · 已下载 {pct}%',
                    indeterminate=False)
            else:
                self._startup['indeterminate'] = True

    def _set_mapping_stage(self, stage, message):
        stages = {
            'read_base': (3, 58, 'base.json.gz'),
            'read_extra': (3, 66, 'extra.json.gz'),
            'build_index': (4, 74, '整理汉字、音标与注释的对应关系'),
        }
        step, progress, detail = stages.get(stage, (3, 58, ''))
        with self._lock:
            self._startup.update(
                phase='loading', message=str(message), progress=progress,
                step=step, detail=detail, indeterminate=True)

    def _set_mapping_progress(self, progress):
        pct = max(0, min(100, int(progress)))
        with self._lock:
            self._startup.update(
                message='正在建立字音索引...',
                progress=74 + pct * 16 // 100, step=4,
                detail=f'字音索引 · 已完成 {pct}%', indeterminate=False)

    def _require_buffer(self):
        if self.buf is None:
            raise RuntimeError('编辑器尚未初始化')
        return self.buf

    def _pending_cell_updates(self, char, info):
        revision = info.get('data_revision')
        reviews = info.get('update_reviews') or {}
        phonetic = info.get('phonetic', char)
        pending = []
        for event in self.reading_events.get(char, []):
            if revision and event['timestamp'] <= revision:
                continue
            review = reviews.get(event['id']) or {}
            if review.get('status') in (
                    'accepted_new', 'kept_current', 'reviewed'):
                continue
            if (review.get('status') == 'reopened'
                    or phonetic in event.get('removed', [])):
                pending.append(copy.deepcopy(event))
        return pending

    def _confirmed_cell_updates(self, info):
        reviews = info.get('update_reviews') or {}
        confirmed = []
        for event_id, review in reviews.items():
            if review.get('status') not in (
                    'accepted_new', 'kept_current', 'reviewed'):
                continue
            event = copy.deepcopy(review.get('event') or {'id': event_id})
            event['review'] = copy.deepcopy(review)
            confirmed.append(event)
        confirmed.sort(key=lambda item: item.get('timestamp', ''), reverse=True)
        return confirmed

    def _refresh_cell_update_state(self, char, info):
        pending = self._pending_cell_updates(char, info)
        info['stale'] = bool(pending)
        return pending

    def _refresh_all_update_states(self, buf):
        for chars, infos in zip(buf.buffer, buf.cell_info):
            for char, info in zip(chars, infos):
                self._refresh_cell_update_state(char, info)

    # Snapshots -----------------------------------------------------------

    def get_state(self):
        with self._lock:
            buf = self._require_buffer()
            drafts, recent_drafts = _draft_library_snapshot()
            return {
                'ok': True,
                'editor': self._editor_snapshot(buf),
                'drafts': drafts,
                'recent_drafts': recent_drafts,
                'groups': get_groups(),
                'schemes': list_schemes(),
                'selected_scheme': self.export_scheme_id,
                'theme': get_theme(),
                'version': __version__,
                'changelog': CHANGELOG,
                'ui_preferences': _load_ui_preferences(),
            }

    def get_editor(self):
        with self._lock:
            return self._editor_snapshot(self._require_buffer())

    def _editor_snapshot(self, buf):
        lines = []
        for chars, infos in zip(buf.buffer, buf.cell_info):
            cells = []
            brackets = find_bracket_ranges(chars)
            for ci, (char, info) in enumerate(zip(chars, infos)):
                phonetic = info.get('phonetic', char)
                is_poly = bool(info.get('is_poly'))
                stale = bool(info.get('stale'))
                bracket = in_bracket(ci, brackets)
                cell = {
                    'char': char,
                    'phonetic': phonetic,
                    'is_poly': is_poly,
                    'selected': info.get('selected', 'none'),
                    'manual_hl': bool(info.get('manual_hl')),
                    'stale': stale,
                    'in_bracket': bracket,
                    'missing_phonetic': (
                        not bracket and not stale and not is_poly
                        and phonetic == char
                        and _NORMAL_NON_HAN.fullmatch(char) is None),
                }
                cells.append(cell)
            lines.append(cells)
        return {
            'lines': lines,
            'cursor': [buf.cur_line, buf.cur_col],
            'selection': buf.selection_range(),
            'dirty': buf.dirty,
            'current_draft': self.current_draft,
            'current_name': (get_draft_name(self.current_draft)
                             if self.current_draft else '未命名文稿'),
            'can_undo': bool(buf.undo_stack),
            'can_redo': bool(buf.redo_stack),
            'raw': buf.copy_raw(),
            'scroll_top': self.scroll_top,
        }

    def _view_state(self):
        buf = self._require_buffer()
        return {
            'cursor': [buf.cur_line, buf.cur_col],
            'selection': (list(buf.sel_anchor) if buf.sel_anchor else None),
            'scroll_top': self.scroll_top,
        }

    def _changed(self):
        """Persist every edit so a process crash cannot discard the document."""
        buf = self._require_buffer()
        if self.current_draft is None and buf.copy_raw():
            self.current_draft = save_draft(
                None, '未命名文稿', buf.buffer, buf.cell_info,
                self._view_state())
            _set_ui_state_value('current_draft', self.current_draft)
        elif self.current_draft is not None:
            save_draft(self.current_draft, None, buf.buffer, buf.cell_info,
                       self._view_state())
        buf.dirty = False
        return self._editor_snapshot(buf)

    # Editor operations ---------------------------------------------------

    def set_caret(self, line, column, extend=False):
        with self._lock:
            buf = self._require_buffer()
            line = max(0, min(int(line), len(buf.buffer) - 1))
            column = max(0, min(int(column), len(buf.buffer[line])))
            if extend and buf.sel_anchor is None:
                buf.sel_anchor = (buf.cur_line, buf.cur_col)
            elif not extend:
                buf.sel_anchor = None
            buf.cur_line, buf.cur_col = line, column
            if self.current_draft:
                update_draft_editor_state(
                    self.current_draft, self._view_state())
            return self._editor_snapshot(buf)

    def save_editor_view(self, scroll_top):
        with self._lock:
            self.scroll_top = max(0, int(scroll_top or 0))
            if self.current_draft:
                update_draft_editor_state(
                    self.current_draft, self._view_state())
            return {'ok': True}

    def editor_action(self, action, extend=False):
        with self._lock:
            buf = self._require_buffer()
            changed = False
            if action in ('Left', 'Right', 'Up', 'Down', 'Home', 'End'):
                if extend and buf.sel_anchor is None:
                    buf.sel_anchor = (buf.cur_line, buf.cur_col)
                elif not extend:
                    buf.sel_anchor = None
                buf.handle_nav(action)
            elif action == 'escape':
                buf.clear_selection()
            elif action == 'select_all':
                if buf.copy_raw():
                    buf.sel_anchor = (0, 0)
                    buf.cur_line = len(buf.buffer) - 1
                    buf.cur_col = len(buf.buffer[-1])
            elif action == 'undo':
                changed = buf.undo()
            elif action == 'redo':
                changed = buf.redo()
            elif action == 'backspace':
                changed = buf.delete_selection() or buf.backspace()
            elif action == 'delete':
                changed = buf.delete_selection() or buf.delete_char()
            elif action == 'newline':
                buf.delete_selection()
                buf.insert_newline()
                changed = True
            else:
                raise ValueError(f'未知编辑操作: {action}')
            return self._changed() if changed else self._editor_snapshot(buf)

    def insert_text(self, text, payload=None):
        with self._lock:
            buf = self._require_buffer()
            text = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
            if not text:
                return self._editor_snapshot(buf)
            if not buf.delete_selection():
                buf.save_undo()
            if (isinstance(payload, dict)
                    and payload.get('text') == text
                    and payload.get('buffer')):
                buf.insert_payload(payload)
            else:
                buf.insert_chars_raw(text)
            return self._changed()

    def delete_selection(self):
        with self._lock:
            buf = self._require_buffer()
            return self._changed() if buf.delete_selection() else self._editor_snapshot(buf)

    def get_copy_payload(self, selection_only=True):
        with self._lock:
            buf = self._require_buffer()
            payload = buf.selection_payload() if selection_only else buf.full_payload()
            if selection_only and payload is None:
                payload = buf.full_payload()
            return payload

    def get_phonetic_text(self, selection_only=False):
        with self._lock:
            buf = self._require_buffer()
            if selection_only and buf.selection_range():
                return self._selection_phonetic(buf)
            return self._phonetic_text(buf)

    def get_cell_details(self, line, column):
        with self._lock:
            buf = self._require_buffer()
            line, column = int(line), int(column)
            if line < 0 or line >= len(buf.buffer):
                return None
            if column < 0 or column >= len(buf.buffer[line]):
                return None
            char = buf.buffer[line][column]
            info = buf.cell_info[line][column]
            pending_updates = self._refresh_cell_update_state(char, info)
            options = copy.deepcopy(self.mapping.get(char) or [])
            same_char_count = sum(row.count(char) for row in buf.buffer)
            return {
                'line': line,
                'column': column,
                'char': char,
                'phonetic': info.get('phonetic', char),
                'is_poly': bool(info.get('is_poly')),
                'selected': info.get('selected', 'none'),
                'manual_hl': bool(info.get('manual_hl')),
                'stale': bool(pending_updates),
                'options': options,
                'pending_updates': pending_updates,
                'confirmed_updates': self._confirmed_cell_updates(info),
                'same_char_count': same_char_count,
            }

    def reading_conflicts(self, line, column, phonetic):
        with self._lock:
            buf = self._require_buffer()
            char = buf.buffer[int(line)][int(column)]
            conflicts = []
            for li, (chars, infos) in enumerate(zip(buf.buffer, buf.cell_info)):
                for ci, (ch, info) in enumerate(zip(chars, infos)):
                    if (ch == char and (li, ci) != (int(line), int(column))
                            and info.get('is_poly')
                            and info.get('selected') == 'manual'
                            and info.get('phonetic') != phonetic):
                        conflicts.append({
                            'line': li,
                            'column': ci,
                            'phonetic': info.get('phonetic'),
                            'context': ''.join(chars),
                        })
            return conflicts

    @staticmethod
    def _record_update_review(info, event, status, before, after,
                              previous_selected=None):
        reviews = info.setdefault('update_reviews', {})
        previous_review = reviews.get(event['id']) or {}
        before_revision = info.get('data_revision')
        if previous_review.get('status') == 'reopened':
            before = previous_review.get('before', before)
            before_revision = previous_review.get(
                'before_revision', before_revision)
            previous_selected = previous_review.get(
                'previous_selected', previous_selected)
        reviews[event['id']] = {
            'status': status,
            'before': before,
            'after': after,
            'before_revision': before_revision,
            'previous_selected': previous_selected,
            'confirmed_at': datetime.now().isoformat(timespec='seconds'),
            'event': copy.deepcopy(event),
        }
        if not before_revision or event['timestamp'] > before_revision:
            info['data_revision'] = event['timestamp']

    def _confirm_pending_with_reading(self, char, info, phonetic):
        pending = self._pending_cell_updates(char, info)
        before = info.get('phonetic', char)
        previous_selected = info.get('selected', 'none')
        for event in pending:
            self._record_update_review(
                info, event, 'accepted_new', before, phonetic,
                previous_selected)
        return bool(pending)

    def apply_reading(self, line, column, phonetic, global_apply=False,
                      overwrite_manual=False, skip_positions=None):
        with self._lock:
            buf = self._require_buffer()
            line, column = int(line), int(column)
            char = buf.buffer[line][column]
            skipped = {
                (int(position[0]), int(position[1]))
                for position in (skip_positions or [])
                if isinstance(position, (list, tuple)) and len(position) == 2
            }
            buf.save_undo()
            had_stale = False
            if global_apply:
                for infos in buf.cell_info:
                    for info in infos:
                        if info.get('selected') == 'global_recent':
                            info['selected'] = 'global'
                for li, (chars, infos) in enumerate(zip(buf.buffer, buf.cell_info)):
                    for ci, (ch, info) in enumerate(zip(chars, infos)):
                        if ch != char or not info.get('is_poly'):
                            continue
                        if (li, ci) in skipped:
                            continue
                        conflict = (info.get('selected') == 'manual'
                                    and info.get('phonetic') != phonetic
                                    and (li, ci) != (line, column))
                        if conflict and not overwrite_manual:
                            continue
                        same_manual = (
                            (li, ci) != (line, column)
                            and info.get('selected') == 'manual'
                            and info.get('phonetic') == phonetic)
                        if not same_manual:
                            pending_confirmed = self._confirm_pending_with_reading(
                                ch, info, phonetic)
                            info['phonetic'] = phonetic
                            info['selected'] = (
                                'manual' if (li, ci) == (line, column)
                                else 'global_recent')
                            had_stale = pending_confirmed or had_stale
                        self._refresh_cell_update_state(ch, info)
            else:
                info = buf.cell_info[line][column]
                had_stale = self._confirm_pending_with_reading(
                    char, info, phonetic)
                info['phonetic'] = phonetic
                info['selected'] = 'manual'
                self._refresh_cell_update_state(char, info)
            editor = self._changed()
            return self.get_state() if had_stale else editor

    def review_cell_update(self, line, column, event_id, action,
                           phonetic=None):
        with self._lock:
            buf = self._require_buffer()
            line, column = int(line), int(column)
            char = buf.buffer[line][column]
            info = buf.cell_info[line][column]
            pending = self._pending_cell_updates(char, info)
            event = next(
                (item for item in pending if item['id'] == str(event_id)),
                None)
            if event is None:
                raise ValueError('这条更新已经确认或不再适用于此处')
            action = str(action or '')
            before = info.get('phonetic', char)
            previous_selected = info.get('selected', 'none')
            after = before
            if action == 'accept':
                phonetic = str(phonetic or '').strip()
                allowed = [
                    (item.get('phonetic', '') if isinstance(item, dict)
                     else str(item))
                    for item in (self.mapping.get(char) or [])
                ]
                if not phonetic or phonetic not in allowed:
                    raise ValueError('请选择当前词库中的读音')
                after = phonetic
                status = 'accepted_new'
            elif action == 'keep':
                status = 'kept_current'
            else:
                raise ValueError('未知的更新确认方式')
            buf.save_undo()
            self._record_update_review(
                info, event, status, before, after, previous_selected)
            if action == 'accept':
                options = self.mapping.get(char) or []
                info['phonetic'] = after
                info['is_poly'] = len(options) > 1
                info['options'] = options if len(options) > 1 else None
                info['selected'] = 'manual'
            self._refresh_cell_update_state(char, info)
            self._changed()
            return self.get_state()

    def reopen_cell_update(self, line, column, event_id,
                           restore_reading=False):
        with self._lock:
            buf = self._require_buffer()
            line, column = int(line), int(column)
            char = buf.buffer[line][column]
            info = buf.cell_info[line][column]
            reviews = info.setdefault('update_reviews', {})
            review = reviews.get(str(event_id))
            if not review or review.get('status') not in (
                    'accepted_new', 'kept_current', 'reviewed'):
                raise ValueError('没有可重新审阅的确认记录')
            buf.save_undo()
            if (restore_reading
                    and info.get('phonetic', char) == review.get('after')):
                info['phonetic'] = review.get('before', char)
                info['selected'] = review.get('previous_selected', 'none')
            review['status'] = 'reopened'
            review['reopened_at'] = datetime.now().isoformat(timespec='seconds')
            info['data_revision'] = review.get('before_revision')
            self._refresh_cell_update_state(char, info)
            self._changed()
            return self.get_state()

    def toggle_highlight(self, line, column):
        with self._lock:
            buf = self._require_buffer()
            info = buf.cell_info[int(line)][int(column)]
            buf.save_undo()
            info['manual_hl'] = not bool(info.get('manual_hl'))
            return self._changed()

    # Drafts and folders --------------------------------------------------

    def new_draft(self):
        with self._lock:
            self.buf = EditorBuffer(self.mapping)
            self.scroll_top = 0
            self.current_draft = save_draft(
                None, '未命名文稿', self.buf.buffer, self.buf.cell_info,
                self._view_state())
            _set_ui_state_value('current_draft', self.current_draft)
            return self.get_state()

    def save_current(self):
        with self._lock:
            buf = self._require_buffer()
            if not buf.copy_raw().strip():
                return {'ok': False, 'message': '没有可保存的内容。'}
            self.current_draft = save_draft(
                self.current_draft, None, buf.buffer, buf.cell_info,
                self._view_state(), create_history=True)
            _set_ui_state_value('current_draft', self.current_draft)
            buf.dirty = False
            return {'ok': True, 'state': self.get_state()}

    def _load_draft_into_buffer(self, filename, persist_current=True):
        buf = self._require_buffer()
        buffer, cell_info, view_state = load_draft(
            filename, self.mapping, include_state=True)
        buf.buffer = buffer or [[]]
        buf.cell_info = cell_info or [[]]
        cursor = view_state.get('cursor', [0, 0])
        buf.cur_line = max(0, min(int(cursor[0]), len(buf.buffer) - 1))
        buf.cur_col = max(
            0, min(int(cursor[1]), len(buf.buffer[buf.cur_line])))
        anchor = view_state.get('selection')
        if isinstance(anchor, (list, tuple)) and len(anchor) == 2:
            ali = max(0, min(int(anchor[0]), len(buf.buffer) - 1))
            aci = max(0, min(int(anchor[1]), len(buf.buffer[ali])))
            buf.sel_anchor = (ali, aci)
        else:
            buf.sel_anchor = None
        self.scroll_top = max(0, int(view_state.get('scroll_top', 0)))
        buf.undo_stack.clear()
        buf.redo_stack.clear()
        buf.dirty = False
        self.current_draft = filename
        if persist_current:
            _set_ui_state_value('current_draft', filename)
        self.reading_events = get_reading_change_events()
        self.data_revision = get_current_data_revision()
        buf.data_revision = self.data_revision
        self._refresh_all_update_states(buf)

    def _restore_startup_draft(self):
        preferred = _load_ui_preferences().get('current_draft')
        candidates = [preferred] if preferred else []
        candidates.extend(
            item.get('filename') for item in list_recent_drafts()
            if item.get('filename') not in candidates)
        for filename in candidates:
            try:
                self._load_draft_into_buffer(filename)
                return True
            except (OSError, ValueError, TypeError):
                continue
        _set_ui_state_value('current_draft', None)
        return False

    def load_draft(self, filename):
        with self._lock:
            self._load_draft_into_buffer(filename)
            return self.get_state()

    def get_draft_history(self, filename=None):
        with self._lock:
            filename = filename or self.current_draft
            return list_draft_history(filename) if filename else []

    def restore_draft_version(self, filename, snapshot_id):
        with self._lock:
            restore_draft_history(filename, snapshot_id)
            return self.load_draft(filename)

    def delete_draft(self, filename):
        with self._lock:
            delete_draft(filename)
            if self.current_draft == filename:
                self.buf = EditorBuffer(self.mapping)
                self.current_draft = None
                self.scroll_top = 0
                _set_ui_state_value('current_draft', None)
            return self.get_state()

    def rename_draft(self, filename, name):
        with self._lock:
            name = str(name or '').strip()
            if not name:
                raise ValueError('文稿名称不能为空')
            rename_draft(filename, name)
            return self.get_state()

    def set_draft_completed(self, filename, completed):
        with self._lock:
            set_draft_completed(filename, bool(completed))
            return self.get_state()

    def create_group(self, name='新建文件夹', parent_id=None):
        with self._lock:
            create_group(str(name or '新建文件夹'), parent_id)
            return self.get_state()

    def rename_group(self, group_id, name):
        with self._lock:
            rename_group(group_id, str(name or '').strip() or '未命名文件夹')
            return self.get_state()

    def delete_group(self, group_id):
        with self._lock:
            delete_group(group_id)
            return self.get_state()

    def toggle_group(self, group_id):
        with self._lock:
            toggle_group(group_id)
            return self.get_state()

    def move_draft(self, filename, group_id=None, before_filename=None):
        with self._lock:
            move_to_group(filename, group_id)
            reorder_file_in_group(filename, group_id, before_filename)
            return self.get_state()

    def move_group(self, group_id, parent_id=None, before_group_id=None):
        with self._lock:
            move_group_into(group_id, parent_id)
            reorder_group(group_id, parent_id, before_group_id)
            return self.get_state()

    # Search, replace, and batch editing ---------------------------------

    def replace_text(self, query, replacement, replace_all=False,
                     scope='char', line=None, column=None):
        with self._lock:
            buf = self._require_buffer()
            query = str(query or '')
            replacement = str(replacement or '')
            if not query:
                return {'count': 0, 'editor': self._editor_snapshot(buf)}
            if scope not in ('char', 'phon'):
                scope = 'char'
            if scope == 'char' and '\n' in replacement:
                raise ValueError('查找替换暂不支持在替换内容中插入换行')
            targets = []
            if scope == 'phon':
                for li, infos in enumerate(buf.cell_info):
                    for ci, info in enumerate(infos):
                        if query in str(info.get('phonetic', '')):
                            if replace_all or (li == int(line) and ci == int(column)):
                                targets.append((li, ci))
                                if not replace_all:
                                    break
                    if targets and not replace_all:
                        break
            else:
                for li, chars in enumerate(buf.buffer):
                    text = ''.join(chars)
                    start = 0
                    while True:
                        index = text.find(query, start)
                        if index < 0:
                            break
                        if replace_all or (li == int(line) and index == int(column)):
                            targets.append((li, index))
                            if not replace_all:
                                break
                        start = index + max(1, len(query))
                    if targets and not replace_all:
                        break
            if not targets:
                return {'count': 0, 'editor': self._editor_snapshot(buf)}
            buf.save_undo()
            if scope == 'phon':
                for li, ci in targets:
                    info = buf.cell_info[li][ci]
                    info['phonetic'] = str(info.get('phonetic', '')).replace(
                        query, replacement)
                    info['selected'] = 'manual'
                buf.cur_line, buf.cur_col = targets[-1]
                buf.cur_col += 1
            else:
                for li, index in sorted(targets, reverse=True):
                    new_chars = list(replacement)
                    new_infos = [buf.make_cell_info(char) for char in new_chars]
                    buf.buffer[li][index:index + len(query)] = new_chars
                    buf.cell_info[li][index:index + len(query)] = new_infos
                first_li, first_ci = targets[0]
                buf.cur_line = first_li
                buf.cur_col = first_ci + len(replacement)
            buf.sel_anchor = None
            snapshot = self._changed()
            return {'count': len(targets), 'editor': snapshot}

    def get_polyphonic_summary(self):
        with self._lock:
            buf = self._require_buffer()
            summary = {}
            for chars, infos in zip(buf.buffer, buf.cell_info):
                for char, info in zip(chars, infos):
                    if not info.get('is_poly'):
                        continue
                    item = summary.setdefault(char, {
                        'char': char, 'count': 0, 'readings': {},
                        'options': copy.deepcopy(self.mapping.get(char) or [])})
                    item['count'] += 1
                    phon = info.get('phonetic', '')
                    item['readings'][phon] = item['readings'].get(phon, 0) + 1
            return sorted(summary.values(), key=lambda item: (-item['count'], item['char']))

    def batch_apply_reading(self, char, phonetic, overwrite_manual=False):
        with self._lock:
            buf = self._require_buffer()
            target = None
            for li, chars in enumerate(buf.buffer):
                for ci, value in enumerate(chars):
                    if value == char and buf.cell_info[li][ci].get('is_poly'):
                        target = (li, ci)
                        break
                if target:
                    break
            if not target:
                raise ValueError(f'正文中没有多音字「{char}」')
            return self.apply_reading(
                target[0], target[1], phonetic, True, overwrite_manual)

    # Schemes and export --------------------------------------------------

    def select_scheme(self, scheme_id):
        with self._lock:
            scheme_id = normalize_scheme_id(scheme_id)
            load_scheme(scheme_id)
            self.export_scheme_id = scheme_id
            save_preferred_scheme_id(scheme_id)
            return {'ok': True, 'selected_scheme': scheme_id}

    def reorder_schemes(self, scheme_ids):
        with self._lock:
            save_scheme_order(scheme_ids)
            return {'ok': True, 'schemes': list_schemes()}

    def update_scheme_description(self, scheme_id, description):
        with self._lock:
            scheme_id = normalize_scheme_id(scheme_id)
            scheme = load_scheme(scheme_id)
            scheme['description'] = str(description or '').strip()
            save_scheme(scheme, scheme_id)
            return {
                'ok': True,
                'scheme': {
                    'id': scheme_id,
                    'name': scheme.get('name', scheme_id),
                    'description': scheme['description'],
                },
                'schemes': list_schemes(),
            }

    def set_scheme_archived(self, scheme_id, archived):
        with self._lock:
            scheme_id = normalize_scheme_id(scheme_id)
            scheme = load_scheme(scheme_id)
            scheme['archived'] = bool(archived)
            save_scheme(scheme, scheme_id)
            schemes = list_schemes()
            if scheme['archived'] and self.export_scheme_id == scheme_id:
                available = [item for item in schemes if not item['archived']]
                self.export_scheme_id = available[0]['id'] if available else None
                save_preferred_scheme_id(self.export_scheme_id or '')
            return {
                'ok': True,
                'schemes': schemes,
                'selected_scheme': self.export_scheme_id,
            }

    def get_scheme(self, scheme_id=None):
        with self._lock:
            scheme_id = scheme_id or self.export_scheme_id
            if not scheme_id:
                raise ValueError('没有可用方案，请先导入方案')
            return load_scheme(scheme_id)

    def validate_scheme(self, scheme):
        with self._lock:
            return validate_scheme(scheme)

    def preview_scheme(self, scheme, text):
        with self._lock:
            issues = validate_scheme(scheme)
            if any(item['severity'] == 'error' for item in issues):
                return {'ok': False, 'issues': issues, 'output': ''}
            try:
                output = NocmTranscriber(scheme).convert_text(str(text or ''))
                return {'ok': True, 'issues': issues, 'output': output}
            except Exception as exc:
                return {'ok': False, 'issues': issues, 'output': '',
                        'message': str(exc)}

    def compare_scheme(self, scheme, other_scheme_id):
        with self._lock:
            other = load_scheme(other_scheme_id)
            return {
                'other': {'id': other.get('id'), 'name': other.get('name')},
                'differences': diff_schemes(scheme, other),
            }

    def save_scheme(self, scheme):
        with self._lock:
            scheme_id = save_scheme(scheme, scheme.get('id'))
            self.export_scheme_id = scheme_id
            save_preferred_scheme_id(scheme_id)
            return {
                'ok': True,
                'scheme': load_scheme(scheme_id),
                'schemes': list_schemes(),
                'selected_scheme': scheme_id,
            }

    def clone_scheme(self, scheme):
        with self._lock:
            clone = copy.deepcopy(scheme)
            source_id = normalize_scheme_id(clone.get('id') or DEFAULT_SCHEME_ID)
            base_id = normalize_scheme_id(f'{source_id}_copy')
            existing = {item['id'] for item in list_schemes()}
            target_id = base_id
            suffix = 2
            while target_id in existing:
                target_id = f'{base_id}_{suffix}'
                suffix += 1
            clone['id'] = target_id
            clone['name'] = f"{clone.get('name') or source_id} 副本"
            clone.pop('created_at', None)
            clone.pop('archived', None)
            return clone

    def import_scheme_json(self, path=None):
        if not path and _APP_WINDOW:
            import webview
            chosen = _APP_WINDOW.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=('JSON 方案 (*.json)',))
            path = chosen[0] if chosen else None
        if not path:
            return {'ok': False, 'cancelled': True}
        with self._lock:
            with open(path, 'r', encoding='utf-8') as file:
                scheme = json.load(file)
            return self._import_scheme_data(scheme, path)

    def import_scheme_content(self, content, filename='scheme.json'):
        """Import scheme JSON supplied by a browser file picker."""
        try:
            scheme = json.loads(str(content or ''))
        except json.JSONDecodeError as exc:
            raise ValueError('方案文件不是有效的 JSON') from exc
        with self._lock:
            return self._import_scheme_data(scheme, filename)

    def _import_scheme_data(self, scheme, source):
        scheme, _changed = migrate_scheme_data(scheme)
        issues = validate_scheme(scheme)
        errors = [item for item in issues if item['severity'] == 'error']
        if errors:
            raise ValueError('；'.join(item['message'] for item in errors[:3]))
        source_id = normalize_scheme_id(
            scheme.get('id') or os.path.splitext(os.path.basename(source))[0])
        existing = {item['id'] for item in list_schemes()}
        target_id = source_id
        if target_id in existing:
            target_id = normalize_scheme_id(f'{source_id}_imported')
            suffix = 2
            while target_id in existing:
                target_id = f'{source_id}_imported_{suffix}'
                suffix += 1
        scheme['id'] = target_id
        if target_id != source_id:
            scheme['name'] = f"{scheme.get('name') or source_id}（导入）"
        saved_id = save_scheme(scheme, target_id)
        self.export_scheme_id = saved_id
        save_preferred_scheme_id(saved_id)
        return {
            'ok': True, 'scheme': load_scheme(saved_id),
            'schemes': list_schemes(), 'selected_scheme': saved_id,
            'source': os.path.abspath(source),
        }

    def export_scheme_json(self, scheme, path=None):
        with self._lock:
            editable = copy.deepcopy(scheme)
            editable, _changed = migrate_scheme_data(editable)
            issues = validate_scheme(editable)
            errors = [item for item in issues if item['severity'] == 'error']
            if errors:
                raise ValueError('；'.join(item['message'] for item in errors[:3]))
            scheme_id = normalize_scheme_id(editable.get('id'))
            if not path and _APP_WINDOW:
                import webview
                chosen = _APP_WINDOW.create_file_dialog(
                    webview.SAVE_DIALOG,
                    directory=get_scheme_dir(),
                    save_filename=f'{scheme_id}.json',
                    file_types=('JSON 方案 (*.json)',))
                path = chosen[0] if chosen else None
            if not path:
                return {'ok': False, 'cancelled': True}
            if not str(path).lower().endswith('.json'):
                path = f'{path}.json'
            editable['id'] = scheme_id
            editable['app_version'] = __version__
            save_json_atomic(path, editable, indent=2, newline=True)
            return {'ok': True, 'path': os.path.abspath(path)}

    def export_text(self, mode='phon', scheme_id=None, punct_split=False,
                    entry_before_glottal=False,
                    departing_before_glottal=False,
                    remove_pharyngeal=False,
                    remove_tones=False,
                    clean_line_breaks=False,
                    remove_glottal_tone=False,
                    extra_h_before_voiceless_sonorant=False,
                    ignore_bracket_control_lines=False):
        with self._lock:
            buf = self._require_buffer()
            raw = buf.copy_raw().strip()
            phon = self._phonetic_text(buf)
            scheme_id = scheme_id or self.export_scheme_id
            if mode == 'raw':
                result = raw
            elif mode == 'both':
                result = self._both_text(buf, bool(punct_split))
            elif mode == 'suno':
                if not scheme_id:
                    raise ValueError('没有可用方案，请先导入方案')
                scheme = load_scheme(scheme_id)
                phon = self._phonetic_text(
                    buf, bool(entry_before_glottal),
                    bool(departing_before_glottal),
                    bool(remove_pharyngeal), bool(remove_tones),
                    scheme.get('maps', {}).get('tone'),
                    scheme.get('parse_order', {}).get('tone'),
                    bool(remove_glottal_tone))
                transcriber = NocmTranscriber(scheme)
                if extra_h_before_voiceless_sonorant:
                    result = transcriber.convert_text(phon, True)
                else:
                    result = transcriber.convert_text(phon)
            else:
                result = phon
            if punct_split and mode != 'both':
                result = self._split_punctuation(result)
            if ignore_bracket_control_lines:
                result = self._ignore_bracket_control_lines(result)
            if clean_line_breaks:
                result = self._clean_line_breaks(result)
            if scheme_id != self.export_scheme_id:
                self.export_scheme_id = scheme_id
                save_preferred_scheme_id(scheme_id)
            return result

    def get_image_export_data(self):
        """Return bracket-free cells, preserving control lines as blanks."""
        with self._lock:
            buf = self._require_buffer()
            lines = []
            for line_index, (chars, infos) in enumerate(
                    zip(buf.buffer, buf.cell_info)):
                brackets = find_bracket_ranges(chars)
                cells = [
                    {
                        'char': char,
                        'phonetic': info.get('phonetic', char),
                        'is_poly': bool(info.get('is_poly')),
                        'selected': info.get('selected', 'none'),
                        'manual_hl': bool(info.get('manual_hl')),
                        'stale': bool(info.get('stale')),
                        'missing_phonetic': (
                            not info.get('stale') and not info.get('is_poly')
                            and info.get('phonetic', char) == char
                            and _NORMAL_NON_HAN.fullmatch(char) is None),
                    }
                    for column, (char, info) in enumerate(zip(chars, infos))
                    if not in_bracket(column, brackets)
                ]
                visible_blank = not ''.join(
                    cell['char'] for cell in cells).strip()
                if visible_blank:
                    cells = []
                lines.append({
                    'source_line': line_index,
                    'cells': cells,
                    'blank': visible_blank,
                })
            return {
                'ok': True,
                'title': (get_draft_name(self.current_draft)
                          if self.current_draft else '未命名文稿'),
                'lines': lines,
            }

    def export_image(self, data_url, filename=None, path=None):
        """Save a browser-rendered PNG through the native save dialog."""
        value = str(data_url or '')
        prefix = 'data:image/png;base64,'
        if not value.startswith(prefix):
            raise ValueError('图片数据格式无效')
        try:
            content = base64.b64decode(value[len(prefix):], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('图片数据无法解码') from exc
        if not content.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('导出内容不是有效的 PNG 图片')
        if len(content) > 64 * 1024 * 1024:
            raise ValueError('图片超过 64 MB，请减少导出的行数')

        safe_name = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+', '_', str(filename or '正文')).strip()
        safe_name = safe_name.rstrip('. ') or '正文'
        if not safe_name.lower().endswith('.png'):
            safe_name = f'{safe_name}.png'
        if not path and _APP_WINDOW:
            import webview
            pictures = os.path.join(os.path.expanduser('~'), 'Pictures')
            chosen = _APP_WINDOW.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=pictures if os.path.isdir(pictures) else None,
                save_filename=safe_name,
                file_types=('PNG 图片 (*.png)',))
            path = chosen[0] if chosen else None
        if not path:
            return {'ok': False, 'cancelled': True}
        if not str(path).lower().endswith('.png'):
            path = f'{path}.png'
        write_bytes_atomic(path, content)
        return {'ok': True, 'path': os.path.abspath(path)}

    # Preferences ---------------------------------------------------------

    def get_theme_preference(self):
        return {'theme': get_theme()}

    def set_theme(self, theme):
        if theme not in ('light', 'dark'):
            raise ValueError('主题必须是 light 或 dark')
        set_theme(theme)
        return {'theme': get_theme()}

    def restart_app(self):
        executable = sys.executable
        args = ([executable] + sys.argv[1:] if getattr(sys, 'frozen', False)
                else [executable] + sys.argv)
        os.execv(executable, args)

    def set_ui_preference(self, key, value):
        if key not in ('inspector_width', 'editor_zoom', 'debug_mode',
                       'export_options'):
            raise ValueError('不支持的界面偏好')
        if key == 'inspector_width':
            normalized = max(230, min(520, int(value)))
        elif key == 'editor_zoom':
            normalized = max(0.7, min(2.0, round(float(value), 1)))
        elif key == 'export_options':
            source = value if isinstance(value, dict) else {}
            normalized = {
                name: bool(source.get(name, False))
                for name in _EXPORT_OPTION_KEYS
            }
        else:
            normalized = bool(value)
        with _UI_STATE_LOCK:
            preferences = _load_ui_preferences()
            preferences[key] = normalized
            _save_ui_preferences(preferences)
        return {'ok': True, 'key': key, 'value': normalized}

    # Maintenance --------------------------------------------------------

    def get_window_state(self):
        return {'maximized': self._window_maximized}

    def minimize_window(self):
        if _APP_WINDOW:
            _APP_WINDOW.minimize()
        return {'ok': True}

    def toggle_maximize_window(self):
        if not _APP_WINDOW:
            return {'ok': False, 'maximized': False}
        maximized = not self._window_maximized
        if maximized:
            _APP_WINDOW.maximize()
        else:
            _APP_WINDOW.restore()
        self._set_window_maximized(maximized)
        return {'ok': True, 'maximized': maximized}

    def close_window(self):
        if _APP_WINDOW:
            threading.Timer(0.05, _APP_WINDOW.destroy).start()
        return {'ok': True}

    def start_window_resize(self, edge):
        hit_tests = {
            'left': 10, 'right': 11, 'top': 12,
            'top-left': 13, 'top-right': 14, 'bottom': 15,
            'bottom-left': 16, 'bottom-right': 17,
        }
        hit_test = hit_tests.get(str(edge))
        native = getattr(_APP_WINDOW, 'native', None) if _APP_WINDOW else None
        if os.name != 'nt' or not hit_test or native is None or self._window_maximized:
            return {'ok': False}
        try:
            import ctypes
            handle = int(native.Handle.ToInt64())
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(handle, 0x00A1, hit_test, 0)
            return {'ok': True}
        except Exception:
            return {'ok': False}

    def get_diagnostics(self):
        return diagnostic_info()

    def get_backend_logs(self):
        return get_runtime_logs()

    def clear_backend_logs(self):
        clear_runtime_logs()
        return get_runtime_logs()

    def check_for_updates(self):
        return check_for_updates()

    def start_update_check(self):
        """Check releases in the background and expose a pollable status."""
        with self._lock:
            if self._update_check['phase'] == 'checking':
                return copy.deepcopy(self._update_check)
            self._update_check = {
                'phase': 'checking', 'message': '正在连接 GitHub…',
                'result': None, 'error': None,
            }

        def worker():
            try:
                result = check_for_updates()
                with self._lock:
                    self._update_check.update(
                        phase='ready', message='更新检查完成',
                        result=result, error=None)
            except Exception as exc:
                with self._lock:
                    self._update_check.update(
                        phase='error', message='检查更新失败',
                        error=str(exc) or type(exc).__name__)

        threading.Thread(
            target=worker, name='pboc-update-check', daemon=True).start()
        return self.get_update_check_status()

    def get_update_check_status(self):
        with self._lock:
            return copy.deepcopy(self._update_check)

    def download_update(self):
        return download_update()

    def start_update_download(self, expected_version=None):
        """Start a non-blocking update download for WebView clients."""
        with self._lock:
            current = self._update_download
            if current['phase'] in ('checking', 'downloading', 'verifying'):
                return dict(current)
            result = current.get('result') or {}
            if (current['phase'] == 'ready' and result.get('version') ==
                    str(expected_version or '')):
                return dict(current)
            self._update_download = {
                'phase': 'checking', 'message': '正在获取更新信息…',
                'progress': 0, 'downloaded': 0, 'total': 0,
                'result': None, 'error': None,
            }

        def worker():
            try:
                result = download_update(on_progress=self._set_update_download)
                with self._lock:
                    self._update_download.update(
                        phase='ready', message='安装包已下载并通过校验',
                        progress=100, result=result, error=None)
            except Exception as exc:
                with self._lock:
                    self._update_download.update(
                        phase='error', message='更新下载失败',
                        error=str(exc) or type(exc).__name__)

        threading.Thread(target=worker, daemon=True).start()
        return self.get_update_download_status()

    def _set_update_download(self, status):
        with self._lock:
            self._update_download.update(status)

    def get_update_download_status(self):
        with self._lock:
            return copy.deepcopy(self._update_download)

    def install_downloaded_update(self, path):
        verified = validate_downloaded_update(path)
        if os.environ.get('HAN_NOCM_RUNTIME') == 'android':
            return {**verified, 'ready': True}
        result = launch_windows_update(path)
        if _APP_WINDOW:
            threading.Timer(0.35, _APP_WINDOW.destroy).start()
        return result

    def export_backup(self, path=None):
        if not path and _APP_WINDOW:
            import webview
            chosen = _APP_WINDOW.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=default_backup_dir(),
                save_filename='汉转PBOC备份.zip',
                file_types=('ZIP 备份 (*.zip)',))
            path = chosen[0] if chosen else None
        if not path:
            return {'ok': False, 'cancelled': True}
        result = create_backup(path)
        return {'ok': True, **result}

    def import_backup(self, path=None, replace=True):
        if not path and _APP_WINDOW:
            import webview
            chosen = _APP_WINDOW.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=default_backup_dir(),
                allow_multiple=False,
                file_types=('ZIP 备份 (*.zip)',))
            path = chosen[0] if chosen else None
        if not path:
            return {'ok': False, 'cancelled': True}
        inspected = inspect_backup(path)
        result = restore_backup(inspected['path'], bool(replace))
        self.export_scheme_id = load_preferred_scheme_id()
        self.buf = EditorBuffer(self.mapping)
        self.current_draft = None
        self.scroll_top = 0
        _set_ui_state_value('current_draft', None)
        return {**result, 'state': self.get_state()}

    def import_old_library(self, path=None):
        if not path and _APP_WINDOW:
            import webview
            chosen = _APP_WINDOW.create_file_dialog(
                webview.FOLDER_DIALOG, allow_multiple=False)
            path = chosen[0] if chosen else None
        if not path:
            return {'ok': False, 'cancelled': True}
        with self._lock:
            report = import_legacy_library(path)
            return {'ok': True, **report, 'state': self.get_state()}

    def open_location(self, location):
        info = diagnostic_info()
        allowed = {
            'app': info['app_dir'], 'drafts': info['draft_dir'],
            'schemes': info['scheme_dir'], 'log': info['log_path'],
            'backups': default_backup_dir(),
        }
        path = allowed.get(location)
        if not path:
            raise ValueError('未知位置')
        if location == 'log' and not os.path.exists(path):
            raise FileNotFoundError('日志文件尚未生成')
        os.startfile(path)
        return {'ok': True}

    def get_data_change_batches(self, offset=0, limit=40):
        return get_data_change_batches(offset, limit)

    def get_data_change_entries(self, batch_id, offset=0, limit=80, query=''):
        return get_data_change_entries(batch_id, offset, limit, query)

    def open_releases_page(self):
        import webbrowser
        from app_version import RELEASES_PAGE_URL
        webbrowser.open(RELEASES_PAGE_URL)
        return {'ok': True}

    def open_source_url(self, url):
        import webbrowser
        allowed = {
            'https://zhuanlan.zhihu.com/p/12987993957',
            'https://github.com/qwert-ly/xtext',
            'https://space.bilibili.com/129368153',
            'https://space.bilibili.com/87432837',
        }
        if url not in allowed:
            raise ValueError('未知的数据源地址')
        webbrowser.open(url)
        return {'ok': True}

    # Text rendering helpers ---------------------------------------------

    @staticmethod
    def _phonetic_text(buf, entry_before_glottal=False,
                       departing_before_glottal=False,
                       remove_pharyngeal=False, remove_tones=False,
                       tone_map=None, tone_order=None,
                       remove_glottal_tone=False):
        lines = []
        for chars, infos in zip(buf.buffer, buf.cell_info):
            brackets = find_bracket_ranges(chars)
            phonetics = WebApi._line_phonetics(
                chars, infos, brackets, entry_before_glottal,
                departing_before_glottal, remove_pharyngeal,
                remove_tones, tone_map, tone_order,
                remove_glottal_tone)
            parts, bracket_buf = [], []
            for ci, (char, info) in enumerate(zip(chars, infos)):
                if in_bracket(ci, brackets):
                    bracket_buf.append(char)
                else:
                    if bracket_buf:
                        parts.append(''.join(bracket_buf))
                        bracket_buf = []
                    parts.append(phonetics[ci])
            if bracket_buf:
                parts.append(''.join(bracket_buf))
            lines.append(' '.join(parts))
        return '\n'.join(lines).strip()

    @staticmethod
    def _line_phonetics(chars, infos, brackets, entry_before_glottal,
                        departing_before_glottal=False,
                        remove_pharyngeal=False, remove_tones=False,
                        tone_map=None, tone_order=None,
                        remove_glottal_tone=False):
        phonetics = [
            str(info.get('phonetic', char))
            for char, info in zip(chars, infos)
        ]
        if remove_pharyngeal:
            phonetics = [
                phonetic if in_bracket(ci, brackets)
                else phonetic.replace('ˤ', '')
                for ci, phonetic in enumerate(phonetics)
            ]
        if entry_before_glottal or departing_before_glottal:
            for ci in range(1, len(phonetics)):
                if (in_bracket(ci, brackets)
                        or in_bracket(ci - 1, brackets)
                        or not phonetics[ci].startswith('ʔ')):
                    continue
                previous = phonetics[ci - 1]
                if (entry_before_glottal
                        and previous.endswith(('p', 't', 'k'))):
                    phonetics[ci - 1] = f'{previous[:-1]}ʔ'
                    continue
                if departing_before_glottal:
                    for suffix in ('ps', 'ts', 'ks', 'ʔs', 's'):
                        if previous.endswith(suffix):
                            phonetics[ci - 1] = (
                                f'{previous[:-len(suffix)]}ʔ')
                            break
        if remove_tones:
            source = tone_map or {key: key for key in DEFAULT_TONE_ORDER}
            order = tone_order or DEFAULT_TONE_ORDER
            phonetics = [
                phonetic if in_bracket(ci, brackets)
                else consume_suffix(phonetic, source, order)[0]
                for ci, phonetic in enumerate(phonetics)
            ]
        elif remove_glottal_tone:
            source = tone_map or {key: key for key in DEFAULT_TONE_ORDER}
            order = tone_order or DEFAULT_TONE_ORDER
            cleaned = []
            for ci, phonetic in enumerate(phonetics):
                if in_bracket(ci, brackets):
                    cleaned.append(phonetic)
                    continue
                body, tone = consume_suffix(phonetic, source, order)
                cleaned.append(f"{body}{tone.replace('ʔ', '')}")
            phonetics = cleaned
        return phonetics

    @staticmethod
    def _selection_phonetic(buf):
        (sli, sci), (eli, eci) = buf.selection_range()
        output = []
        for li in range(sli, eli + 1):
            chars, infos = buf.buffer[li], buf.cell_info[li]
            lo = sci if li == sli else 0
            hi = eci if li == eli else len(chars)
            brackets = find_bracket_ranges(chars)
            parts, bracket_buf = [], []
            for ci in range(lo, hi):
                if in_bracket(ci, brackets):
                    bracket_buf.append(chars[ci])
                else:
                    if bracket_buf:
                        parts.append(''.join(bracket_buf))
                        bracket_buf = []
                    parts.append(infos[ci].get('phonetic', chars[ci]))
            if bracket_buf:
                parts.append(''.join(bracket_buf))
            output.append(' '.join(parts))
        return '\n'.join(output).strip()

    @staticmethod
    def _split_punctuation(text):
        output = []
        normalized = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
        for raw_line in normalized.split('\n'):
            brackets = find_bracket_ranges(raw_line)
            transformed = []
            for index, char in enumerate(raw_line):
                if in_bracket(index, brackets):
                    transformed.append(char)
                elif char in _PUNCT_DOUBLE_NEWLINE:
                    transformed.append('\n\n')
                elif char in _PUNCT_TO_NEWLINE:
                    transformed.append('\n')
                else:
                    transformed.append(char)
            output.extend(
                line.strip() for line in ''.join(transformed).split('\n'))
        return '\n'.join(output)

    @staticmethod
    def _ignore_bracket_control_lines(text):
        normalized = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
        return '\n'.join(
            line for line in normalized.split('\n')
            if _BRACKET_CONTROL_LINE.fullmatch(line.strip()) is None)

    @staticmethod
    def _clean_line_breaks(text):
        output = []
        pending_blank = False
        normalized = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
        for raw_line in normalized.split('\n'):
            line = raw_line.strip()
            if line:
                if (pending_blank and output
                        and _BRACKET_CONTROL_LINE.fullmatch(output[-1]) is None):
                    output.append('')
                output.append(line)
                pending_blank = False
            elif output:
                pending_blank = True
        return '\n'.join(output)

    @staticmethod
    def _both_text(buf, punct_split, entry_before_glottal=False,
                   departing_before_glottal=False):
        output = []
        pending_blank = False

        def emit(raw, phon, double=False):
            nonlocal pending_blank
            raw, phon = raw.strip(), phon.strip()
            if not raw and not phon:
                return False
            if pending_blank and output:
                output.append('')
                pending_blank = False
            if raw:
                output.append(raw)
            if phon:
                output.append(phon)
            if double:
                pending_blank = True
            return bool(phon)

        for chars, infos in zip(buf.buffer, buf.cell_info):
            line_has_phon = False
            brackets = find_bracket_ranges(chars)
            phonetics = WebApi._line_phonetics(
                chars, infos, brackets, entry_before_glottal,
                departing_before_glottal)
            raw_buf, phon_parts = [], []
            for ci, (char, info) in enumerate(zip(chars, infos)):
                if in_bracket(ci, brackets):
                    raw_buf.append(char)
                    continue
                if punct_split and char in _PUNCT_TO_NEWLINE:
                    line_has_phon = emit(
                        ''.join(raw_buf), ' '.join(phon_parts),
                        char in _PUNCT_DOUBLE_NEWLINE) or line_has_phon
                    raw_buf, phon_parts = [], []
                else:
                    raw_buf.append(char)
                    phon_parts.append(phonetics[ci])
            line_has_phon = emit(
                ''.join(raw_buf), ' '.join(phon_parts)) or line_has_phon
            if line_has_phon and output and not pending_blank:
                pending_blank = True
        return '\n'.join(output).rstrip()


def web_asset_path(filename='index.html'):
    """Resolve packaged and source-tree web assets."""
    import sys

    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'web', filename)
