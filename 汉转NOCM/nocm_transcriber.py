"""Configurable PBOC transcription engine."""

import copy
import json
import os
import re
import sys
from dataclasses import replace
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
    if isinstance(scheme['parse_order'], dict):
        for section, order in list(scheme['parse_order'].items()):
            if not isinstance(order, list):
                continue
            unique_order = list(dict.fromkeys(order))
            if unique_order != order:
                scheme['parse_order'][section] = unique_order
                changed = True
    options = scheme['options']
    definitions = scheme.setdefault('option_definitions', {})
    obsolete_dialect_keys = {
        'dialect_dongtu', 'dialect_dongtu_jizhi',
        'dialect_xitu_qinzheng', 'dialect_xitu_qinzheng_target',
        'dialect_xitu_qinzheng_coda', 'dialect_han_xitu_qinzheng',
        'dialect_han_xitu_qinzheng_target',
        'dialect_han_xitu_qinzheng_coda',
    }
    for key in obsolete_dialect_keys:
        if key in options:
            options.pop(key)
            changed = True
        if key in definitions:
            definitions.pop(key)
            changed = True
    # Split the former combined 之幽 option once into independent 之 / 幽
    # controls while preserving its prior enabled state and target vowel.
    split_zhiyou = {
        ('dialect_xitu_zhiyou_e', 'dialect_xitu_zhiyou_e_target',
         'dialect_xitu_zhiyou'),
        ('dialect_xitu_zhiyou_u', 'dialect_xitu_zhiyou_u_target',
         'dialect_xitu_zhiyou'),
        ('dialect_han_zhiyou_e', 'dialect_han_zhiyou_e_target',
         'dialect_han_zhiyou'),
        ('dialect_han_zhiyou_u', 'dialect_han_zhiyou_u_target',
         'dialect_han_zhiyou'),
    }
    for enabled_key, target_key, old_key in split_zhiyou:
        if enabled_key not in options and old_key in options:
            options[enabled_key] = bool(options[old_key])
            changed = True
        if target_key not in options and old_key in options:
            old_target = old_key + '_target'
            options[target_key] = copy.deepcopy(
                options.get(old_target, 'ɯ'))
            changed = True
    for old_key in ('dialect_xitu_zhiyou', 'dialect_xitu_zhiyou_target',
                    'dialect_han_zhiyou', 'dialect_han_zhiyou_target'):
        if old_key in options:
            options.pop(old_key)
            changed = True
        if old_key in definitions:
            definitions.pop(old_key)
            changed = True
    presets = {
        'nasal': {'b': 'mб', 'd': 'nд', 'g': 'ŋг'},
        'english': {'b': 'б', 'd': 'ντ', 'g': 'γκ'},
    }
    voiced_stop_definition = {
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
    extra_h_definition = {
        'type': 'boolean',
        'label': '清响音前额外加 h',
        'description': '转写清响音声母时，在方案输出前再添加一个 h。',
        'group': 'transcription',
    }
    dialect_definitions = {
        'dialect_xitu': {
            'type': 'boolean',
            'label': '西土方言',
            'description': '启用西土方言的合韵修改。',
            'group': 'dialect',
        },
        'dialect_han': {
            'type': 'boolean',
            'label': '汉代',
            'description': '启用汉代音变。',
            'group': 'dialect_group',
        },
        'dialect_han_xitu': {
            'type': 'boolean',
            'label': '汉代西土',
            'description': '启用汉代西土音变。',
            'group': 'dialect_group',
        },
        'dialect_han_dongtu': {
            'type': 'boolean',
            'label': '汉代东土',
            'description': '启用汉代东土音变。',
            'group': 'dialect_group',
        },
        'dialect_donghan_late_xitu': {
            'type': 'boolean',
            'label': '东汉晚期西土',
            'description': '启用东汉晚期西土音变。',
            'group': 'dialect_group',
        },
        'dialect_xitu_dongqin': {
            'type': 'boolean', 'label': '冬侵合韵·侵',
            'description': 'u 元音、m 韵尾。修改韵尾。', 'group': 'dialect',
        },
        'dialect_xitu_dongqin_coda': {
            'type': 'text', 'label': '冬侵合韵·侵目标韵尾', 'default': 'ŋ',
            'group': 'dialect', 'parent': 'dialect_xitu_dongqin',
        },
        'dialect_xitu_dongqin_dong': {
            'type': 'boolean', 'label': '冬侵合韵·冬',
            'description': 'u 元音、ŋ 韵尾。修改韵尾。', 'group': 'dialect',
        },
        'dialect_xitu_dongqin_dong_coda': {
            'type': 'text', 'label': '冬侵合韵·冬目标韵尾', 'default': 'm',
            'group': 'dialect', 'parent': 'dialect_xitu_dongqin_dong',
        },
        'dialect_xitu_qinzheng_only': {
            'type': 'boolean', 'label': '侵蒸合韵·侵',
            'description': 'ə 元音、m 韵尾。修改韵尾。', 'group': 'dialect',
        },
        'dialect_xitu_qinzheng_only_coda': {
            'type': 'text', 'label': '侵蒸合韵·侵目标韵尾', 'default': 'ŋ',
            'group': 'dialect', 'parent': 'dialect_xitu_qinzheng_only',
        },
        'dialect_xitu_qinzheng_only_zheng': {
            'type': 'boolean', 'label': '侵蒸合韵·蒸',
            'description': 'ə 元音、ŋ 韵尾。修改韵尾。', 'group': 'dialect',
        },
        'dialect_xitu_qinzheng_only_zheng_coda': {
            'type': 'text', 'label': '侵蒸合韵·蒸目标韵尾', 'default': 'm',
            'group': 'dialect', 'parent': 'dialect_xitu_qinzheng_only_zheng',
        },
        'dialect_xitu_zhiyou_e': {
            'type': 'boolean',
            'label': '之幽合韵·之',
            'description': 'ə 元音、无韵尾、无声调或 ʔ 声调。修改元音。',
            'group': 'dialect',
        },
        'dialect_xitu_zhiyou_e_target': {
            'type': 'text',
            'label': '之幽合韵·之目标元音',
            'description': '之幽合韵使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect',
            'parent': 'dialect_xitu_zhiyou_e',
        },
        'dialect_xitu_zhiyou_u': {'type': 'boolean', 'label': '之幽合韵·幽', 'description': 'u 元音、无韵尾、无声调或 ʔ 声调。修改元音。', 'group': 'dialect'},
        'dialect_xitu_zhiyou_u_target': {'type': 'text', 'label': '之幽合韵·幽目标元音', 'description': 'u 元音的目标元音。', 'default': 'ɯ', 'group': 'dialect', 'parent': 'dialect_xitu_zhiyou_u'},
        'dialect_xitu_zhijue': {
            'type': 'boolean',
            'label': '職覺合韵·職',
            'description': 'ə 元音、无韵尾、k 声调。修改元音。',
            'group': 'dialect',
        },
        'dialect_xitu_zhijue_target': {
            'type': 'text',
            'label': '職覺合韵·職目标元音',
            'description': '西土方言職覺合韵使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect',
            'parent': 'dialect_xitu_zhijue',
        },
        'dialect_han_zhiyou_e': {
            'type': 'boolean',
            'label': '之幽合韵·之',
            'description': 'ə 元音、无韵尾、无声调或 ʔ 声调。修改元音。',
            'group': 'dialect_han_xitu',
        },
        'dialect_han_zhiyou_e_target': {
            'type': 'text',
            'label': '之幽合韵·之目标元音',
            'description': '汉代之幽合韵使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect_han_xitu',
            'parent': 'dialect_han_zhiyou_e',
        },
        'dialect_han_zhiyou_u': {'type': 'boolean', 'label': '之幽合韵·幽', 'description': 'u 元音、无韵尾、无声调或 ʔ 声调。修改元音。', 'group': 'dialect_han_xitu'},
        'dialect_han_zhiyou_u_target': {'type': 'text', 'label': '之幽合韵·幽目标元音', 'description': 'u 元音的目标元音。', 'default': 'ɯ', 'group': 'dialect_han_xitu', 'parent': 'dialect_han_zhiyou_u'},
        'dialect_han_xitu_dongqin': {
            'type': 'boolean', 'label': '冬侵合韵·侵',
            'description': 'u 元音、m 韵尾。修改韵尾。', 'group': 'dialect_han_xitu',
        },
        'dialect_han_xitu_dongqin_coda': {
            'type': 'text', 'label': '冬侵合韵·侵目标韵尾', 'default': 'ŋ',
            'group': 'dialect_han_xitu', 'parent': 'dialect_han_xitu_dongqin',
        },
        'dialect_han_xitu_dongqin_dong': {
            'type': 'boolean', 'label': '冬侵合韵·冬',
            'description': 'u 元音、ŋ 韵尾。修改韵尾。', 'group': 'dialect_han_xitu',
        },
        'dialect_han_xitu_dongqin_dong_coda': {
            'type': 'text', 'label': '冬侵合韵·冬目标韵尾', 'default': 'm',
            'group': 'dialect_han_xitu', 'parent': 'dialect_han_xitu_dongqin_dong',
        },
        'dialect_han_xitu_qinzheng_only': {
            'type': 'boolean', 'label': '侵蒸合韵·侵',
            'description': 'ə 元音、m 韵尾。修改韵尾。', 'group': 'dialect_han_xitu',
        },
        'dialect_han_xitu_qinzheng_only_coda': {
            'type': 'text', 'label': '侵蒸合韵·侵目标韵尾', 'default': 'ŋ',
            'group': 'dialect_han_xitu', 'parent': 'dialect_han_xitu_qinzheng_only',
        },
        'dialect_han_xitu_qinzheng_only_zheng': {
            'type': 'boolean', 'label': '侵蒸合韵·蒸',
            'description': 'ə 元音、ŋ 韵尾。修改韵尾。', 'group': 'dialect_han_xitu',
        },
        'dialect_han_xitu_qinzheng_only_zheng_coda': {
            'type': 'text', 'label': '侵蒸合韵·蒸目标韵尾', 'default': 'm',
            'group': 'dialect_han_xitu', 'parent': 'dialect_han_xitu_qinzheng_only_zheng',
        },
        'dialect_xitu_zhijue_u': {'type': 'boolean', 'label': '職覺合韵·覺', 'description': 'u 元音、无韵尾、k 声调。修改元音。', 'group': 'dialect'},
        'dialect_xitu_zhijue_u_target': {'type': 'text', 'label': '職覺合韵·覺目标元音', 'default': 'ɯ', 'group': 'dialect', 'parent': 'dialect_xitu_zhijue_u'},
        'dialect_han_xitu_zhijue': {
            'type': 'boolean',
            'label': '職覺合韵·職',
            'description': 'ə 元音、无韵尾、k 声调。修改元音。',
            'group': 'dialect_han_xitu',
        },
        'dialect_han_xitu_zhijue_target': {
            'type': 'text',
            'label': '職覺合韵·職目标元音',
            'description': '汉代西土職覺合韵使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect_han_xitu',
            'parent': 'dialect_han_xitu_zhijue',
        },
        'dialect_han_xitu_zhijue_u': {'type': 'boolean', 'label': '職覺合韵·覺', 'description': 'u 元音、无韵尾、k 声调。修改元音。', 'group': 'dialect_han_xitu'},
        'dialect_han_xitu_zhijue_u_target': {'type': 'text', 'label': '職覺合韵·覺目标元音', 'default': 'ɯ', 'group': 'dialect_han_xitu', 'parent': 'dialect_han_xitu_zhijue_u'},
        'dialect_han_dongtu_zhiyou': {
            'type': 'boolean',
            'label': '之部合口字之幽合韵',
            'description': 'u 元音、无韵尾；w 介音 + ə 元音、无韵尾。修改为无介音、ɯ 元音。',
            'group': 'dialect_han_dongtu',
        },
        'dialect_han_dongtu_zhiyou_target': {
            'type': 'text',
            'label': '之部合口字之幽合韵目标元音',
            'description': '之部合口字之幽合韵使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect_han_dongtu',
            'parent': 'dialect_han_dongtu_zhiyou',
        },
        'dialect_xitu_you_xiao_first': {
            'type': 'boolean',
            'label': '第一类幽宵合韵·幽',
            'description': 'i 元音、w 韵尾。修改元音。',
            'group': 'dialect',
        },
        'dialect_xitu_you_xiao_first_target': {
            'type': 'text',
            'label': '第一类幽宵合韵·幽目标元音',
            'description': '第一类幽宵合韵使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect',
            'parent': 'dialect_xitu_you_xiao_first',
        },
        'dialect_xitu_you_xiao_first_e': {'type': 'boolean', 'label': '第一类幽宵合韵·宵', 'description': 'e 元音、w 韵尾。修改元音。', 'group': 'dialect'},
        'dialect_xitu_you_xiao_first_e_target': {'type': 'text', 'label': '第一类幽宵合韵·宵目标元音', 'default': 'ɯ', 'group': 'dialect', 'parent': 'dialect_xitu_you_xiao_first_e'},
        'dialect_xitu_you_xiao_second': {
            'type': 'boolean',
            'label': '第二类幽宵合韵·幽',
            'description': 'u 元音、无韵尾、无声调或 ʔ 声调。修改元音和韵尾。',
            'group': 'dialect',
        },
        'dialect_xitu_you_xiao_second_target': {
            'type': 'text',
            'label': '第二类幽宵合韵·幽目标元音',
            'description': 'u 元音的目标元音。',
            'default': 'ɯ',
            'group': 'dialect',
            'parent': 'dialect_xitu_you_xiao_second',
        },
        'dialect_xitu_you_xiao_second_coda': {
            'type': 'text',
            'label': '第二类幽宵合韵·幽目标韵尾',
            'description': '第二类幽宵合韵使用的目标韵尾。',
            'default': 'w',
            'group': 'dialect',
            'parent': 'dialect_xitu_you_xiao_second',
        },
        'dialect_xitu_you_xiao_second_a': {'type': 'boolean', 'label': '第二类幽宵合韵·宵', 'description': 'a 元音、w 韵尾。修改元音。', 'group': 'dialect'},
        'dialect_xitu_you_xiao_second_a_target': {'type': 'text', 'label': '第二类幽宵合韵·宵目标元音', 'default': 'ɯ', 'group': 'dialect', 'parent': 'dialect_xitu_you_xiao_second_a'},
        'dialect_xitu_xiaoyu_houyao': {
            'type': 'boolean',
            'label': '宵魚侯/藥屋合韵',
            'description': 'a 元音、无韵尾或 w 韵尾；o 元音、无韵尾。修改元音和韵尾。',
            'group': 'dialect_han_xitu',
        },
        'dialect_xitu_xiaoyu_houyao_target': {
            'type': 'text',
            'label': '宵魚侯/藥屋合韵目标元音',
            'description': '宵魚侯/藥屋合韵使用的目标元音。',
            'default': 'o',
            'group': 'dialect_han_xitu',
            'parent': 'dialect_xitu_xiaoyu_houyao',
        },
        'dialect_xitu_xiaoyu_houyao_coda': {
            'type': 'text',
            'label': '宵魚侯/藥屋合韵目标韵尾',
            'description': '宵魚侯/藥屋合韵使用的目标韵尾。',
            'default': 'w',
            'group': 'dialect_han_xitu',
            'parent': 'dialect_xitu_xiaoyu_houyao',
        },
        'dialect_xitu_donghan_zhibu_qianhua': {
            'type': 'boolean',
            'label': '之部前化',
            'description': 'ə 元音、无韵尾。修改元音。',
            'group': 'dialect_donghan_late_xitu',
        },
        'dialect_xitu_donghan_zhibu_qianhua_target': {
            'type': 'text',
            'label': '之部前化目标元音',
            'description': '之部前化使用的目标元音。',
            'default': 'ɨ',
            'group': 'dialect_donghan_late_xitu',
            'parent': 'dialect_xitu_donghan_zhibu_qianhua',
        },
        'dialect_xitu_donghan_youyuhou': {
            'type': 'boolean',
            'label': '幽魚侯合韵',
            'description': 'u、a、o 元音、无韵尾。修改元音和韵尾。',
            'group': 'dialect_donghan_late_xitu',
        },
        'dialect_xitu_donghan_youyuhou_target': {
            'type': 'text',
            'label': '幽魚侯合韵目标元音',
            'description': '幽魚侯合韵使用的目标元音。',
            'default': 'o',
            'group': 'dialect_donghan_late_xitu',
            'parent': 'dialect_xitu_donghan_youyuhou',
        },
        'dialect_xitu_donghan_youyuhou_coda': {
            'type': 'text',
            'label': '幽魚侯合韵目标韵尾',
            'description': '幽魚侯合韵使用的目标韵尾。',
            'default': 'w',
            'group': 'dialect_donghan_late_xitu',
            'parent': 'dialect_xitu_donghan_youyuhou',
        },
        'dialect_xitu_jizhi': {
            'type': 'boolean',
            'label': '緝職合韵·緝',
            'description': 'ə 元音、无韵尾、p 声调。修改元音和声调。',
            'group': 'dialect',
        },
        'dialect_xitu_jizhi_target': {
            'type': 'text',
            'label': '緝職合韵·緝目标元音',
            'description': '緝職合韵·緝使用的目标元音。',
            'default': 'ɯ',
            'group': 'dialect',
            'parent': 'dialect_xitu_jizhi',
        },
        'dialect_xitu_jizhi_tone': {
            'type': 'text',
            'label': '緝職合韵·緝目标声调',
            'description': '緝職合韵·緝使用的目标声调。',
            'default': 'k',
            'group': 'dialect',
            'parent': 'dialect_xitu_jizhi',
        },
    }
    legacy_glottal_key = 'checked_before_glottal_onset'
    if ('english_voiced_stops' in options or
            'english_voiced_stops' in definitions):
        style = ('english' if bool(options.get('english_voiced_stops', False))
                 else 'nasal')
        scheme['maps'].setdefault('onset', {}).update(presets[style])
        options.pop('english_voiced_stops', None)
        definitions.pop('english_voiced_stops', None)
        options['voiced_stop_style'] = style
        definitions['voiced_stop_style'] = voiced_stop_definition
        changed = True
    elif 'voiced_stop_style' not in definitions:
        if options.get('voiced_stop_style') not in presets:
            options['voiced_stop_style'] = 'custom'
        definitions['voiced_stop_style'] = voiced_stop_definition
        changed = True
    elif options.get('voiced_stop_style') not in {*presets, 'custom'}:
        options['voiced_stop_style'] = 'custom'
        changed = True
    if 'extra_h_voiceless_sonorant' not in options:
        options['extra_h_voiceless_sonorant'] = False
        changed = True
    if 'extra_h_voiceless_sonorant' not in definitions:
        definitions['extra_h_voiceless_sonorant'] = extra_h_definition
        changed = True
    # Older schemes used one key for rules that appeared under multiple
    # historical classes.  Keep that key as the 西土 value and seed the new
    # class-specific keys from it once, so later switches are independent.
    dialect_aliases = {
        'dialect_han_zhiyou': 'dialect_xitu_zhiyou',
        'dialect_han_zhiyou_target': 'dialect_xitu_zhiyou_target',
        'dialect_han_xitu_zhijue': 'dialect_xitu_zhijue',
        'dialect_han_xitu_zhijue_target': 'dialect_xitu_zhijue_target',
    }
    for new_key, old_key in dialect_aliases.items():
        if new_key not in options and old_key in options:
            options[new_key] = copy.deepcopy(options[old_key])
            changed = True
    # Split formerly shared 職覺 and 幽宵 controls into independent branches.
    split_aliases = {
        'dialect_xitu_zhijue_u': 'dialect_xitu_zhijue',
        'dialect_xitu_zhijue_u_target': 'dialect_xitu_zhijue_target',
        'dialect_han_xitu_zhijue_u': 'dialect_han_xitu_zhijue',
        'dialect_han_xitu_zhijue_u_target': 'dialect_han_xitu_zhijue_target',
        'dialect_xitu_you_xiao_first_e': 'dialect_xitu_you_xiao_first',
        'dialect_xitu_you_xiao_first_e_target': 'dialect_xitu_you_xiao_first_target',
        'dialect_xitu_you_xiao_second_a': 'dialect_xitu_you_xiao_second',
        'dialect_xitu_you_xiao_second_a_target': 'dialect_xitu_you_xiao_second_target',
    }
    for new_key, old_key in split_aliases.items():
        if new_key not in options and old_key in options:
            options[new_key] = copy.deepcopy(options[old_key])
            changed = True
    for key, definition in dialect_definitions.items():
        if key not in options:
            if key in ('dialect_han', 'dialect_han_xitu',
                       'dialect_donghan_late_xitu', 'dialect_han_dongtu'):
                options[key] = bool(options.get('dialect_xitu'))
            else:
                options[key] = (definition.get('default', False)
                                if definition.get('type') == 'text' else False)
            changed = True
        if key not in definitions:
            definitions[key] = copy.deepcopy(definition)
            changed = True
        else:
            if 'exclusive_with' in definitions[key]:
                definitions[key].pop('exclusive_with', None)
                changed = True
            metadata_keys = ('label', 'description', 'parent', 'group')
            for metadata_key in metadata_keys:
                if metadata_key in definition and definitions[key].get(metadata_key) != definition[metadata_key]:
                    definitions[key][metadata_key] = copy.deepcopy(definition[metadata_key])
                    changed = True
    if legacy_glottal_key in options:
        options.pop(legacy_glottal_key, None)
        changed = True
    if legacy_glottal_key in definitions:
        definitions.pop(legacy_glottal_key, None)
        changed = True
    for pairs in (scheme['rules'].values()
                  if isinstance(scheme['rules'], dict) else []):
        if not isinstance(pairs, list):
            continue
        for pair in pairs:
            if isinstance(pair, list) and len(pair) == 2:
                pair.append('')
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
        add('error', 'maps', '基础映射格式无效')
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
        add('error', 'rules', '附加替换格式无效')
        return issues
    for section, pairs in rules.items():
        if not isinstance(pairs, list):
            add('error', f'rules.{section}', f'{section} 规则必须是列表')
            continue
        for index, pair in enumerate(pairs):
            path = f'rules.{section}[{index}]'
            if not isinstance(pair, list) or len(pair) not in (2, 3):
                add('error', path, '附加替换必须包含查找、替换和可选说明')
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
                add('基础映射', f'{section}.{key}', lm.get(key), rm.get(key))
    left_rules, right_rules = left.get('rules', {}), right.get('rules', {})
    for section in sorted(set(left_rules) | set(right_rules)):
        before, after = left_rules.get(section, []), right_rules.get(section, [])
        if before != after:
            add('附加替换', section, before, after)
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
        self._remove_pure_entry_before_glottal = False

    def _map_residual(self, text: str) -> str:
        text = apply_replacements(text, replacement_pairs(
            self.rules.get('residual_replace', []), self.scheme))
        residual_map = self.maps.get('residual', {})
        if residual_map:
            residual_order = self.scheme.get('parse_order', {}).get('residual')
            text = apply_replacements(
                text, mapping_pairs(residual_map, residual_order))
        return text

    def _apply_cross_syllable_changes(self, syllables):
        """Apply enabled structural changes before per-syllable mapping."""
        if not self._remove_pure_entry_before_glottal:
            return syllables
        adjusted = list(syllables)
        for index in range(len(adjusted) - 1):
            previous = adjusted[index]
            following = adjusted[index + 1]
            if (previous.tone in {'p', 't', 'k'}
                    and following.onset == 'ʔ'):
                adjusted[index] = replace(previous, tone='')
        return adjusted

    def convert_token(
            self, token: str,
            extra_h_before_voiceless_sonorant: bool = False,
            parsed_syllable=None) -> str:
        if not token:
            return token
        parsed = parsed_syllable or parse_syllable(token, self.scheme)
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
        extra_h = self.options.get(
            'extra_h_voiceless_sonorant',
            extra_h_before_voiceless_sonorant)
        if (extra_h
                and parsed.onset in _VOICELESS_SONORANT_ONSETS):
            text = f'h{text}'
        return text

    def convert_line(
            self, line: str,
            extra_h_before_voiceless_sonorant: bool = False,
            remove_pure_entry_before_glottal: bool = False) -> str:
        self._remove_pure_entry_before_glottal = bool(
            remove_pure_entry_before_glottal)
        def convert_outside_brackets(text: str) -> str:
            matches = list(re.finditer(r'\S+', text))
            if not matches:
                return text
            syllables = self._apply_cross_syllable_changes([
                parse_syllable(match.group(), self.scheme)
                for match in matches
            ])
            pieces = []
            cursor = 0
            for match, syllable in zip(matches, syllables):
                pieces.append(text[cursor:match.start()])
                pieces.append(self.convert_token(
                    match.group(), extra_h_before_voiceless_sonorant,
                    parsed_syllable=syllable))
                cursor = match.end()
            pieces.append(text[cursor:])
            return ''.join(pieces)

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
            extra_h_before_voiceless_sonorant: bool = False,
            remove_pure_entry_before_glottal: bool = False) -> str:
        return '\n'.join(
            self.convert_line(line, extra_h_before_voiceless_sonorant,
                              remove_pure_entry_before_glottal)
            for line in text.splitlines()).strip()


def convert_text(text: str, scheme_id: str = DEFAULT_SCHEME_ID) -> str:
    """Convenience function for one-off conversion."""
    return NocmTranscriber(load_scheme(scheme_id)).convert_text(text)
