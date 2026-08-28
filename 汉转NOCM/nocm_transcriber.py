"""Configurable PBOC transcription engine."""

import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app_version import SCHEME_SCHEMA_VERSION, __version__, get_app_dir
from atomic_io import save_json_atomic, write_text_atomic
from nocm_phonology import (apply_replacements, mapping_pairs, parse_syllable,
                            replacement_pairs)


DEFAULT_SCHEME_ID = 'current_suno'
_SCHEME_ID_PATTERN = re.compile(r'[^A-Za-z0-9_-]+')
_SCHEME_ORDER_FILENAME = '_order.json'
_VOICELESS_SONORANT_ONSETS = {'m̥', 'n̥', 'r̥', 'l̥', 'ŋ̊'}


def _scheme_pref_path() -> str:
    return os.path.join(get_app_dir(), '.scheme_pref')


def get_scheme_dir() -> str:
    """Return the directory that stores transcription scheme JSON files."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        external_dir = os.path.join(exe_dir, 'schemes')
        bundled_dir = os.path.join(getattr(sys, '_MEIPASS', exe_dir), 'schemes')
        try:
            os.makedirs(external_dir, exist_ok=True)
            if os.path.isdir(bundled_dir):
                for filename in os.listdir(bundled_dir):
                    if not filename.endswith('.json'):
                        continue
                    source = os.path.join(bundled_dir, filename)
                    target = os.path.join(external_dir, filename)
                    if os.path.exists(target):
                        continue
                    with open(source, 'r', encoding='utf-8') as f:
                        content = f.read()
                    write_text_atomic(
                        target, lambda f, value=content: f.write(value))
            return external_dir
        except OSError:
            # A read-only installation can still use bundled schemes; saving
            # will surface the permission error to the editor.
            return bundled_dir
    return os.path.join(get_app_dir(), 'schemes')


def list_schemes() -> List[Dict[str, str]]:
    """List scheme metadata from oldest to newest."""
    schemes = []
    scheme_dir = get_scheme_dir()
    if not os.path.isdir(scheme_dir):
        return schemes
    for filename in sorted(os.listdir(scheme_dir)):
        if not filename.endswith('.json') or filename.startswith('_'):
            continue
        path = os.path.join(scheme_dir, filename)
        try:
            file_created_at = datetime.fromtimestamp(
                os.path.getctime(path), timezone.utc).isoformat()
        except OSError:
            file_created_at = ''
        try:
            scheme = load_scheme(filename[:-5])
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        created_at = scheme.get('created_at')
        if not created_at:
            created_at = file_created_at
        schemes.append({
            'id': scheme.get('id', filename[:-5]),
            'name': scheme.get('name', filename[:-5]),
            'description': scheme.get('description', ''),
            'created_at': created_at,
            'archived': bool(scheme.get('archived', False)),
        })
    schemes.sort(key=lambda item: (
        item['created_at'] or '9999',
        item['name'].casefold(), item['id'].casefold()))
    return schemes


def save_scheme_order(scheme_ids) -> List[str]:
    """Persist a complete, de-duplicated order for available schemes."""
    available = [item['id'] for item in list_schemes()]
    requested = []
    for scheme_id in scheme_ids or []:
        normalized = normalize_scheme_id(str(scheme_id))
        if normalized in available and normalized not in requested:
            requested.append(normalized)
    requested.extend(item for item in available if item not in requested)
    scheme_dir = get_scheme_dir()
    os.makedirs(scheme_dir, exist_ok=True)
    save_json_atomic(
        os.path.join(scheme_dir, _SCHEME_ORDER_FILENAME),
        requested, indent=2, newline=True)
    return requested


def load_scheme(scheme_id: str = DEFAULT_SCHEME_ID) -> Dict:
    """Load one scheme JSON by id."""
    filename = scheme_id if scheme_id.endswith('.json') else f'{scheme_id}.json'
    path = os.path.join(get_scheme_dir(), filename)
    with open(path, 'r', encoding='utf-8') as f:
        scheme = json.load(f)
    scheme, changed = migrate_scheme_data(scheme)
    if changed:
        save_json_atomic(path, scheme, indent=2, newline=True)
    return scheme


def migrate_scheme_data(scheme):
    """Upgrade an in-memory scheme and return ``(scheme, changed)``."""
    if not isinstance(scheme, dict):
        raise ValueError('方案数据不是对象')
    version = int(scheme.get('schema_version', 1) or 1)
    if version > SCHEME_SCHEMA_VERSION:
        raise ValueError(f'方案格式版本 {version} 高于当前支持版本')
    changed = version < SCHEME_SCHEMA_VERSION
    if 'maps' not in scheme or not isinstance(scheme['maps'], dict):
        raise ValueError('方案缺少 maps')
    scheme.setdefault('options', {})
    scheme.setdefault('labels', {})
    scheme.setdefault('parse_order', {})
    scheme.setdefault('rules', {})
    options = scheme['options']
    definitions = scheme.setdefault('option_definitions', {})
    if ('english_voiced_stops' in options or
            'english_voiced_stops' in definitions):
        style = ('english' if bool(options.get('english_voiced_stops', False))
                 else 'nasal')
        presets = {
            'nasal': {'b': 'mб', 'd': 'nд', 'g': 'ŋг'},
            'english': {'b': 'б', 'd': 'ντ', 'g': 'γκ'},
        }
        scheme['maps'].setdefault('onset', {}).update(presets[style])
        options.pop('english_voiced_stops', None)
        definitions.pop('english_voiced_stops', None)
        options['voiced_stop_style'] = style
        definitions['voiced_stop_style'] = {
            'type': 'choice',
            'label': '浊塞音拼写',
            'description': ('鼻音诱导：mб / nд / ŋг；英美：б / ντ / γκ；'
                            '手动修改映射后使用自定义。'),
            'choices': [
                {'value': 'nasal', 'label': '鼻音诱导'},
                {'value': 'english', 'label': '英美'},
                {'value': 'custom', 'label': '自定义'},
            ],
            'presets': presets,
        }
        changed = True
    scheme['schema_version'] = SCHEME_SCHEMA_VERSION
    if changed:
        scheme['migrated_by'] = __version__
    return scheme, changed


def normalize_scheme_id(value: str) -> str:
    """Return a filesystem-safe scheme id."""
    value = _SCHEME_ID_PATTERN.sub('_', (value or '').strip()).strip('_')
    return value or 'custom_suno'


def load_preferred_scheme_id(
        default: str = DEFAULT_SCHEME_ID) -> Optional[str]:
    """Load the last selected scheme, falling back if it is unavailable."""
    try:
        with open(_scheme_pref_path(), 'r', encoding='utf-8') as f:
            preferred = normalize_scheme_id(f.read())
        scheme = load_scheme(preferred)
        if not scheme.get('archived', False):
            return preferred
    except (OSError, json.JSONDecodeError, ValueError):
        pass

    try:
        scheme = load_scheme(default)
        if not scheme.get('archived', False):
            return default
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    schemes = [item for item in list_schemes() if not item['archived']]
    return schemes[0]['id'] if schemes else None


def save_preferred_scheme_id(scheme_id: str) -> bool:
    """Persist the selected scheme id without interrupting the UI on failure."""
    scheme_id = normalize_scheme_id(scheme_id)
    try:
        write_text_atomic(_scheme_pref_path(), lambda f: f.write(scheme_id))
        return True
    except OSError:
        return False


def save_scheme(scheme: Dict, scheme_id: str = None) -> str:
    """Save a scheme JSON and return its normalized id."""
    scheme_id = normalize_scheme_id(scheme_id or scheme.get('id'))
    scheme = dict(scheme)
    scheme_dir = get_scheme_dir()
    path = os.path.join(scheme_dir, f'{scheme_id}.json')
    if not scheme.get('created_at'):
        existing_created_at = ''
        try:
            with open(path, 'r', encoding='utf-8') as file:
                existing_created_at = json.load(file).get('created_at', '')
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        if not existing_created_at and os.path.exists(path):
            existing_created_at = datetime.fromtimestamp(
                os.path.getctime(path), timezone.utc).isoformat()
        scheme['created_at'] = existing_created_at or datetime.now(
            timezone.utc).isoformat()
    scheme['id'] = scheme_id
    scheme['schema_version'] = SCHEME_SCHEMA_VERSION
    scheme['app_version'] = __version__
    scheme, _changed = migrate_scheme_data(scheme)
    errors = [item for item in validate_scheme(scheme)
              if item['severity'] == 'error']
    if errors:
        raise ValueError('；'.join(item['message'] for item in errors[:3]))
    os.makedirs(scheme_dir, exist_ok=True)
    save_json_atomic(path, scheme, indent=2, newline=True)
    return scheme_id


def validate_scheme(scheme):
    """Return structured errors and warnings for an editable scheme."""
    issues = []

    def add(severity, path, message):
        issues.append({'severity': severity, 'path': path, 'message': message})

    if not isinstance(scheme, dict):
        return [{'severity': 'error', 'path': '', 'message': '方案数据不是对象'}]
    if not str(scheme.get('id', '')).strip():
        add('error', 'id', '方案 ID 不能为空')
    maps = scheme.get('maps')
    if not isinstance(maps, dict):
        add('error', 'maps', '映射表格式无效')
        maps = {}
    labels = scheme.get('labels', {})
    parse_order = scheme.get('parse_order', {})
    for section, section_map in maps.items():
        if not isinstance(section_map, dict):
            add('error', f'maps.{section}', f'{section} 映射必须是对象')
            continue
        for source, target in section_map.items():
            if not str(source):
                add('error', f'maps.{section}', f'{section} 中存在空 PBOC 项')
            if target is None:
                add('warning', f'maps.{section}.{source}', f'{source} 的输出为空值')
        order = parse_order.get(section, [])
        if len(order) != len(set(order)):
            add('warning', f'parse_order.{section}', f'{section} 的解析顺序包含重复项')
        missing = [key for key in order if key not in section_map]
        if missing:
            add('warning', f'parse_order.{section}',
                f'{section} 的解析顺序引用了不存在的项：{", ".join(missing[:4])}')
        stale_labels = [key for key in labels.get(section, {})
                        if key not in section_map]
        if stale_labels:
            add('warning', f'labels.{section}',
                f'{section} 有未使用的说明：{", ".join(stale_labels[:4])}')

    seen_rules = set()
    rules = scheme.get('rules', {})
    if not isinstance(rules, dict):
        add('error', 'rules', '替换规则格式无效')
        return issues
    for section, pairs in rules.items():
        if not isinstance(pairs, list):
            add('error', f'rules.{section}', f'{section} 规则必须是列表')
            continue
        for index, pair in enumerate(pairs):
            path = f'rules.{section}[{index}]'
            if not isinstance(pair, list) or len(pair) != 2:
                add('error', path, '替换规则必须包含查找和替换两项')
                continue
            old = pair[0]
            if isinstance(old, dict) and old.get('type') == 'map_concat':
                parts = old.get('parts', [])
                if not parts:
                    add('error', path, '映射项拼接不能为空')
                for part in parts:
                    if not isinstance(part, (list, tuple)) or len(part) != 2:
                        add('error', path, '映射项拼接格式无效')
                        continue
                    map_section, key = part
                    if key not in maps.get(map_section, {}):
                        add('error', path,
                            f'拼接引用不存在：{map_section}.{key}')
                signature = json.dumps(old, ensure_ascii=False, sort_keys=True)
            else:
                if str(old) == '':
                    add('error', path, '查找内容不能为空')
                signature = str(old)
            duplicate_key = (section, signature)
            if duplicate_key in seen_rules:
                add('warning', path, '同一分组中存在重复查找规则')
            seen_rules.add(duplicate_key)
    return issues


def diff_schemes(left, right):
    """Return a compact, structured difference between two schemes."""
    differences = []

    def add(category, key, before, after):
        differences.append({
            'category': category, 'key': key,
            'before': before, 'after': after})

    for key in sorted(set(left.get('options', {})) | set(right.get('options', {}))):
        before = left.get('options', {}).get(key)
        after = right.get('options', {}).get(key)
        if before != after:
            add('选项', key, before, after)
    left_maps, right_maps = left.get('maps', {}), right.get('maps', {})
    for section in sorted(set(left_maps) | set(right_maps)):
        lm, rm = left_maps.get(section, {}), right_maps.get(section, {})
        for key in sorted(set(lm) | set(rm)):
            if lm.get(key) != rm.get(key):
                add('映射', f'{section}.{key}', lm.get(key), rm.get(key))
    left_rules, right_rules = left.get('rules', {}), right.get('rules', {})
    for section in sorted(set(left_rules) | set(right_rules)):
        before, after = left_rules.get(section, []), right_rules.get(section, [])
        if before != after:
            add('规则', section, before, after)
    return differences


def clone_scheme(source_id: str = DEFAULT_SCHEME_ID, target_id: str = None,
                 name: str = None) -> Dict:
    """Create an editable copy of an existing scheme in memory."""
    source = load_scheme(source_id)
    target_id = normalize_scheme_id(target_id or f'{source_id}_copy')
    source['id'] = target_id
    source['name'] = name or f"{source.get('name', source_id)} 副本"
    source.pop('created_at', None)
    source.pop('archived', None)
    return source


def resolve_scheme_options(scheme: Dict) -> Dict:
    """Return an isolated scheme whose visible maps are the source of truth."""
    return copy.deepcopy(scheme)


class NocmTranscriber:
    """Render PBOC tokens through a configurable transcription scheme."""

    def __init__(self, scheme: Dict):
        self.scheme = resolve_scheme_options(scheme)
        self.maps = self.scheme.get('maps', {})
        self.rules = self.scheme.get('rules', {})
        self.options = self.scheme.get('options', {})

    def _map_residual(self, text: str) -> str:
        text = apply_replacements(text, replacement_pairs(
            self.rules.get('residual_replace', []), self.scheme))
        residual_map = self.maps.get('residual', {})
        if residual_map:
            residual_order = self.scheme.get('parse_order', {}).get('residual')
            text = apply_replacements(
                text, mapping_pairs(residual_map, residual_order))
        return text

    def convert_token(
            self, token: str,
            extra_h_before_voiceless_sonorant: bool = False) -> str:
        if not token:
            return token
        parsed = parse_syllable(token, self.scheme)
        text = ''.join([
            self.maps.get('onset', {}).get(parsed.onset, parsed.onset),
            self.maps.get('glide', {}).get(parsed.glide, parsed.glide),
            self._map_residual(parsed.residual),
            self.maps.get('nucleus', {}).get(parsed.nucleus, parsed.nucleus),
            self.maps.get('coda', {}).get(parsed.coda, parsed.coda),
            self.maps.get('tone', {}).get(parsed.tone, parsed.tone),
        ])
        if self.options.get('improve_pharyngeal', False):
            text = apply_replacements(text, replacement_pairs(
                self.rules.get('pharyngeal_relax', []), self.scheme))
        if self.options.get('improve_syllable', False):
            text = apply_replacements(text, replacement_pairs(
                self.rules.get('syllable_relax', []), self.scheme))
        text = apply_replacements(text, replacement_pairs(
            self.rules.get('post_replace', []), self.scheme))
        if (extra_h_before_voiceless_sonorant
                and parsed.onset in _VOICELESS_SONORANT_ONSETS):
            text = f'h{text}'
        return text

    def convert_line(
            self, line: str,
            extra_h_before_voiceless_sonorant: bool = False) -> str:
        def convert_outside_brackets(text: str) -> str:
            return re.sub(
                r'\S+', lambda match: self.convert_token(
                    match.group(), extra_h_before_voiceless_sonorant), text)

        parts = []
        outside_start = 0
        bracket_start = None
        bracket_depth = 0
        for index, char in enumerate(line):
            if char == '[':
                if bracket_depth == 0:
                    parts.append(convert_outside_brackets(
                        line[outside_start:index]))
                    bracket_start = index
                bracket_depth += 1
            elif char == ']' and bracket_depth:
                bracket_depth -= 1
                if bracket_depth == 0:
                    parts.append(line[bracket_start:index + 1])
                    outside_start = index + 1

        if bracket_depth:
            # An unfinished control tag is safer left untouched than partially
            # transcribed while the user is still editing it.
            parts.append(line[bracket_start:])
        else:
            parts.append(convert_outside_brackets(line[outside_start:]))
        return ''.join(parts).strip()

    def convert_text(
            self, text: str,
            extra_h_before_voiceless_sonorant: bool = False) -> str:
        return '\n'.join(
            self.convert_line(line, extra_h_before_voiceless_sonorant)
            for line in text.splitlines()).strip()


def convert_text(text: str, scheme_id: str = DEFAULT_SCHEME_ID) -> str:
    """Convenience function for one-off conversion."""
    return NocmTranscriber(load_scheme(scheme_id)).convert_text(text)
