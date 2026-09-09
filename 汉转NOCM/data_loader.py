"""数据下载与加载模块：负责从远程或本地获取 json.gz 音标数据。"""

import os
import gzip
import hashlib
import json
import io
import urllib.request
from datetime import datetime
import re
from typing import Dict, List, Any, Optional

from app_version import get_app_dir
from atomic_io import save_json_atomic


def get_data_dir() -> str:
    """返回数据文件所在目录：打包为 exe 时取 exe 所在目录，否则取脚本目录。"""
    return get_app_dir()


BASE_JSON_GZ_URL = 'https://qwert-ly.github.io/xtext/base.json.gz'
EXTRA_JSON_GZ_URL = 'https://qwert-ly.github.io/xtext/extra.json.gz'
_DATA_UPDATE_LOG = 'data_update.log'
_READING_CHANGE_EVENTS_FILE = 'reading_change_events.json'
_DATA_CHANGE_HEADER = re.compile(
    r'^\[(?P<timestamp>[^]]+)] (?P<filename>.+?) 更新 — 共 (?P<count>\d+) 处差异$')
_DATA_CHANGE_ENTRY = re.compile(r'^  \[(?P<kind>新增|删除|修改)]\s*(?P<body>.*)$')
_DATA_CHANGE_INDEX_CACHE = {'signature': None, 'items': []}
_READING_CHANGE_CACHE = {'signature': None, 'events': {}}
_DATA_CHANGE_FIELD_LABELS = {
    'c': '音韵地位', 'm': '声首', 'd': '释义',
    'z': '汉字', 'y': '音标',
    '總出現次數': '总出现次数', '見西周': '见西周',
    '少見詞出處': '少见词出处',
    '推導中古音': '推导中古音', '推導普通話': '推导普通话',
}

_MIDDLE_CHINESE_INITIALS = '幫滂並明端透定泥來知徹澄孃精清從心邪莊初崇生俟章昌常書船日見溪羣疑影曉匣云以'
_MIDDLE_CHINESE_RIMES = '東冬鍾江支脂之微魚虞模齊祭泰佳皆夬灰咍廢真臻文殷元魂痕寒刪山先仙蕭宵肴豪歌麻陽唐庚耕清青蒸登尤侯幽侵覃談鹽添咸銜嚴凡'
_LABIAL_INITIALS = set('幫滂並明')
_BLUNT_INITIALS = set('幫滂並明見溪羣疑影曉匣云')
_ROUNDING_NEUTRAL_RIMES = set('東冬鍾江模尤侯')
_YIN_RIMES = set('支脂之微魚虞模齊祭泰佳皆夬灰咍廢蕭宵肴豪歌麻侯尤幽')
_INITIAL_PLACES = {
    **{initial: '唇音' for initial in '幫滂並明'},
    **{initial: '舌头音' for initial in '端透定泥'},
    **{initial: '舌上音' for initial in '知徹澄孃'},
    **{initial: '齿头音' for initial in '精清從心邪'},
    **{initial: '正齿音' for initial in '莊初崇生俟章昌常書船'},
    **{initial: '牙音' for initial in '見溪羣疑'},
    **{initial: '喉音' for initial in '影曉匣云以'},
    '來': '半舌音', '日': '半齿音',
}
_INITIAL_VOICING = {
    **{initial: '全清' for initial in '幫端知精心莊生章書見影曉'},
    **{initial: '次清' for initial in '滂透徹清初昌溪'},
    **{initial: '全浊' for initial in '並定澄從邪崇俟常船羣匣'},
    **{initial: '次浊' for initial in '明泥孃來日疑云以'},
}
_INITIAL_MANNERS = {
    **{initial: '塞音' for initial in '幫滂並端透定知徹澄見溪羣影'},
    **{initial: '鼻音' for initial in '明泥孃疑'},
    **{initial: '塞擦音' for initial in '精清從莊初崇章昌常'},
    **{initial: '擦音' for initial in '心邪生俟書船曉匣'},
    '來': '边音', '日': '响音', '云': '近音', '以': '近音',
}
_VOICING_NOTES = {
    '全清': '不送气清音',
    '次清': '送气清音',
    '全浊': '浊阻碍音',
    '次浊': '鼻音、边音等浊响音',
}
_RIME_GROUPS = {
    '通': '東冬鍾', '江': '江', '止': '支脂之微', '遇': '魚虞模',
    '蟹': '齊祭泰佳皆夬灰咍廢', '臻': '真臻文殷魂痕',
    '山': '元寒刪山先仙', '效': '蕭宵肴豪', '果': '歌', '假': '麻',
    '宕': '陽唐', '梗': '庚耕清青', '曾': '蒸登', '流': '尤侯幽',
    '深': '侵', '咸': '覃談鹽添咸銜嚴凡',
}
_RIME_TO_GROUP = {
    rime: group for group, rimes in _RIME_GROUPS.items() for rime in rimes
}
_POSITION_PATTERN = re.compile(
    rf'^([{_MIDDLE_CHINESE_INITIALS}])([開合]?)([一二三四])'
    rf'([ABC]?)([{_MIDDLE_CHINESE_RIMES}])([平上去入])$')


def parse_phonological_position(value: str) -> Optional[Dict[str, Any]]:
    """拆分《切韵》音韵地位描述，并生成适合界面展示的解释。"""
    raw = str(value or '').strip()
    match = _POSITION_PATTERN.fullmatch(raw)
    if not match:
        return None
    initial, rounding, division, category, rime, tone = match.groups()
    group = _RIME_TO_GROUP.get(rime)
    parts = [
        {'key': 'initial', 'label': '声母', 'value': f'{initial}母'},
        {'key': 'rounding', 'label': '开合',
         'value': f'{rounding}口' if rounding else '开合中立'},
        {'key': 'division', 'label': '等', 'value': f'{division}等'},
        {'key': 'category', 'label': '类别',
         'value': f'{category}类' if category else '不分类'},
        {'key': 'rime', 'label': '韵', 'value': f'{rime}韵'},
        {'key': 'tone', 'label': '声调', 'value': f'{tone}声'},
    ]
    initial_voicing = _INITIAL_VOICING.get(initial)
    initial_traits = '、'.join(filter(None, (
        _INITIAL_PLACES.get(initial), initial_voicing,
        _INITIAL_MANNERS.get(initial))))
    explanations = [{
        'text': f'{initial}母：{initial_traits}。',
    }]
    if initial_voicing:
        explanations.append({
            'text': f'{initial_voicing}：{_VOICING_NOTES[initial_voicing]}。',
            'indent': True,
        })
    if initial == '來':
        explanations.append({'text': '拟音：舌边近音 /l/。', 'indent': True})
    if rounding:
        if rounding == '開':
            explanations.append({'text': '開口：无合口圆唇成分。'})
        else:
            explanations.append({'text': '合口：有圆唇成分。'})
        explanations.append({
            'text': '开合：区分圆唇特征，不是口腔开度。',
            'indent': True,
        })
    elif initial in _LABIAL_INITIALS:
        explanations.append({'text':
            f'开合：未标。{initial}母属唇音，不独立区分圆唇特征。'})
    elif rime in _ROUNDING_NEUTRAL_RIMES:
        explanations.append({'text':
            f'开合：未标。{rime}韵不独立区分圆唇特征。'})
    else:
        explanations.append({'text': '开合：未标。'})
    explanations.append({'text':
        f'{division}等：韵图等类，关联介音、主元音等音质差异。'
        '不等同于固定的 /j/，不是声调。'})
    if category == 'C':
        explanations.append({'text': 'C类：三等内部分类，属非前元音类。'})
        explanations.append({'text': 'A、B类：前元音类。', 'indent': True})
        explanations.append({
            'text': '重纽：唇、牙、喉音三等的A／B对立。',
            'indent': True,
        })
    elif category:
        explanations.append({'text':
            f'{category}类：三等内部分类，属前元音类。'})
        explanations.append({'text': 'C类：非前元音类。', 'indent': True})
        explanations.append({
            'text': '重纽：唇、牙、喉音三等的A／B对立。',
            'indent': True,
        })
    elif division != '三':
        explanations.append({'text':
            '类别：A／B／C仅用于唇、牙、喉音的三等地位，此处不适用。'})
    elif initial not in _BLUNT_INITIALS:
        explanations.append({'text':
            f'类别：{initial}母不参与三等地位的A／B／C分类。'})
    else:
        explanations.append({'text': '类别：此三等地位未标A／B／C类别。'})
    rime_kind = '阴声韵' if rime in _YIN_RIMES else (
        '入声韵' if tone == '入' else '阳声韵')
    kind_note = {
        '阴声韵': '一般无鼻音或塞音韵尾',
        '阳声韵': '通常具有鼻音韵尾',
        '入声韵': '与塞音韵尾相配',
    }[rime_kind]
    if group:
        explanations.append({'text':
            f'{rime}韵：{group}摄、{rime_kind}。'})
    else:
        explanations.append({'text': f'{rime}韵：{rime_kind}。'})
    explanations.append({
        'text': f'{rime_kind}：{kind_note}。',
        'indent': True,
    })
    if group:
        explanations.append({
            'text': '摄：归并了韵腹、韵尾等的韵类。',
            'indent': True,
        })
    if tone == '入':
        explanations.append({'text': '入声：中古四声之一，属促声，与塞音韵尾相配。'})
    else:
        explanations.append({'text': f'{tone}声：中古四声之一，属舒声。'})
    return {
        'raw': raw,
        'parts': parts,
        'explanations': explanations,
    }


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
        # 网络不可用时优先使用已有的有效本地数据，避免每次启动继续
        # 等待一次注定失败的完整下载。
        return False
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
    log_path = os.path.join(get_data_dir(), _DATA_UPDATE_LOG)
    header = f'\n{"="*60}\n[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {filename} 更新 — 共 {len([d for d in diffs if d.startswith("  [")])} 处差异\n{"="*60}'
    entry = header + '\n' + '\n'.join(diffs) + '\n'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(entry)
    count = len([d for d in diffs if d.startswith('  [')])
    status_fn(f'[对比] {filename} 有 {count} 处差异，已记录到 data_update.log')


def _data_change_log_path():
    return os.path.join(get_data_dir(), _DATA_UPDATE_LOG)


def _data_change_index():
    """Build a compact byte-offset index without loading the log into RAM."""
    path = _data_change_log_path()
    try:
        stat = os.stat(path)
    except OSError:
        return path, 0, []
    signature = (path, stat.st_size, stat.st_mtime_ns)
    if _DATA_CHANGE_INDEX_CACHE['signature'] == signature:
        return path, stat.st_size, _DATA_CHANGE_INDEX_CACHE['items']

    items = []
    separator = b'=' * 60
    previous = None
    with open(path, 'rb') as file:
        while True:
            line_start = file.tell()
            line = file.readline()
            if not line:
                break
            if line.strip() != separator:
                continue
            header = file.readline().decode('utf-8', errors='replace').strip()
            match = _DATA_CHANGE_HEADER.match(header)
            if not match:
                continue
            closing = file.readline()
            if closing.strip() != separator:
                continue
            if previous is not None:
                previous['end'] = line_start
            previous = {
                'id': str(line_start),
                'timestamp': match.group('timestamp'),
                'filename': match.group('filename'),
                'count': int(match.group('count')),
                'start': file.tell(),
                'end': stat.st_size,
            }
            items.append(previous)
    _DATA_CHANGE_INDEX_CACHE['signature'] = signature
    _DATA_CHANGE_INDEX_CACHE['items'] = items
    return path, stat.st_size, items


def get_data_change_batches(offset=0, limit=40):
    """Return newest update batches while keeping the large log server-side."""
    path, size, items = _data_change_index()
    offset = max(0, int(offset or 0))
    limit = max(1, min(100, int(limit or 40)))
    newest = list(reversed(items))
    page = newest[offset:offset + limit]
    return {
        'ok': True,
        'exists': os.path.exists(path),
        'file_size': size,
        'total': len(newest),
        'offset': offset,
        'has_more': offset + len(page) < len(newest),
        'items': [{key: item[key] for key in
                   ('id', 'timestamp', 'filename', 'count')} for item in page],
    }


def _iter_data_change_entries(file, start, end):
    file.seek(start)
    current = None
    while file.tell() < end:
        line = file.readline()
        if not line:
            break
        text = line.decode('utf-8', errors='replace').rstrip('\r\n')
        match = _DATA_CHANGE_ENTRY.match(text)
        if match:
            if current is not None:
                yield current
            body = match.group('body').strip()
            label, separator, summary = body.partition(':')
            current = {
                'kind': match.group('kind'),
                'label': label.strip(),
                'summary': summary.strip() if separator else '',
                'details': [],
            }
        elif current is not None and text.strip():
            current['details'].append(text.strip())
    if current is not None:
        yield current


def _parse_data_change_json(text):
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def _structure_data_change_entry(entry):
    """Turn raw old/new JSON into a concise field-level comparison."""
    old_value = new_value = None
    if entry['kind'] == '修改':
        for detail in entry['details']:
            if detail.startswith('旧:'):
                old_value = _parse_data_change_json(detail[2:].strip())
            elif detail.startswith('新:'):
                new_value = _parse_data_change_json(detail[2:].strip())
    elif entry['kind'] == '新增':
        new_value = _parse_data_change_json(entry['summary'])
    elif entry['kind'] == '删除':
        old_value = _parse_data_change_json(entry['summary'])

    if old_value is None and new_value is None:
        return entry
    old_record = old_value if isinstance(old_value, dict) else {}
    new_record = new_value if isinstance(new_value, dict) else {}
    if old_record or new_record:
        keys = list(old_record)
        keys.extend(key for key in new_record if key not in old_record)
        changes = []
        unchanged = 0
        missing = object()
        for key in keys:
            old = old_record.get(key, missing)
            new = new_record.get(key, missing)
            if old is not missing and new is not missing and old == new:
                unchanged += 1
                continue
            status = ('新增' if old is missing else
                      '删除' if new is missing else '修改')
            changes.append({
                'field': _DATA_CHANGE_FIELD_LABELS.get(key, key),
                'field_key': key,
                'status': status,
                'old': None if old is missing else old,
                'new': None if new is missing else new,
            })
        identity = new_record or old_record
        headword = identity.get('m') or identity.get('z')
    else:
        changes = [{
            'field': '值', 'status': entry['kind'],
            'old': old_value, 'new': new_value,
        }]
        unchanged = 0
        series_head = None
    return {
        **entry,
        'display_label': (f'{headword} · {entry["label"]}'
                          if headword else entry['label']),
        'changes': changes,
        'unchanged_count': unchanged,
        'details': [],
    }


def _stable_change_event_id(batch, entry):
    payload = json.dumps({
        'timestamp': batch['timestamp'],
        'filename': batch['filename'],
        'kind': entry['kind'],
        'label': entry['label'],
        'summary': entry['summary'],
        'details': entry['details'],
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def _split_logged_phonetics(value):
    return [item.strip() for item in str(value or '').split(',') if item.strip()]


def _reading_change_event(batch, entry):
    """Return a stable per-character reading event for a base-data entry."""
    if batch.get('filename') != 'base.json.gz' or len(entry.get('label', '')) != 1:
        return None
    removed = []
    added = []
    summary = entry.get('summary', '')
    if entry.get('kind') == '删除':
        removed = _split_logged_phonetics(summary)
    elif entry.get('kind') == '新增':
        added = _split_logged_phonetics(summary)
    elif entry.get('kind') == '修改':
        for part in summary.split(';'):
            part = part.strip()
            if part.startswith('移除 '):
                removed.extend(_split_logged_phonetics(part[3:]))
            elif part.startswith('新增 '):
                added.extend(_split_logged_phonetics(part[3:]))
    if not removed and not added:
        return None
    return {
        'id': _stable_change_event_id(batch, entry),
        'batch_id': batch['id'],
        'timestamp': batch['timestamp'],
        'filename': batch['filename'],
        'batch_count': batch['count'],
        'kind': entry['kind'],
        'char': entry['label'],
        'summary': summary,
        'removed': removed,
        'added': added,
    }


def get_reading_change_events():
    """Return base-reading changes indexed by character, oldest first."""
    path, _size, batches = _data_change_index()
    try:
        stat = os.stat(path)
        signature = (path, stat.st_size, stat.st_mtime_ns)
    except OSError:
        signature = (path, 0, 0)
    if _READING_CHANGE_CACHE['signature'] == signature:
        return _READING_CHANGE_CACHE['events']
    cache_path = os.path.join(get_data_dir(), _READING_CHANGE_EVENTS_FILE)
    try:
        with open(cache_path, 'r', encoding='utf-8') as file:
            persisted = json.load(file)
        persisted_signature = persisted.get('signature') or {}
        if (persisted_signature.get('size') == signature[1]
                and persisted_signature.get('mtime_ns') == signature[2]
                and isinstance(persisted.get('events'), dict)):
            _READING_CHANGE_CACHE['signature'] = signature
            _READING_CHANGE_CACHE['events'] = persisted['events']
            return persisted['events']
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    events = {}
    if os.path.exists(path):
        with open(path, 'rb') as file:
            for batch in batches:
                if batch.get('filename') != 'base.json.gz':
                    continue
                for entry in _iter_data_change_entries(
                        file, batch['start'], batch['end']):
                    event = _reading_change_event(batch, entry)
                    if event:
                        events.setdefault(event['char'], []).append(event)
    _READING_CHANGE_CACHE['signature'] = signature
    _READING_CHANGE_CACHE['events'] = events
    try:
        save_json_atomic(cache_path, {
            'signature': {'size': signature[1], 'mtime_ns': signature[2]},
            'events': events,
        }, indent=1)
    except OSError:
        pass
    return events


def get_current_data_revision():
    """Return the newest base-data change timestamp used by new cells."""
    timestamps = [
        event['timestamp']
        for values in get_reading_change_events().values()
        for event in values
    ]
    return max(timestamps, default='0000-00-00 00:00:00')


def get_data_change_entries(batch_id, offset=0, limit=80, query=''):
    """Read one page from a selected batch, optionally filtering its text."""
    path, _size, items = _data_change_index()
    batch = next((item for item in items if item['id'] == str(batch_id)), None)
    if batch is None:
        raise ValueError('数据变更批次不存在或日志已经更新')
    offset = max(0, int(offset or 0))
    limit = max(1, min(200, int(limit or 80)))
    query = str(query or '').strip().casefold()
    matched = []
    total = 0
    with open(path, 'rb') as file:
        for entry in _iter_data_change_entries(
                file, batch['start'], batch['end']):
            haystack = ' '.join([
                entry['kind'], entry['label'], entry['summary'],
                *entry['details']]).casefold()
            if query and query not in haystack:
                continue
            if offset <= total < offset + limit:
                structured = _structure_data_change_entry(entry)
                structured['event_id'] = _stable_change_event_id(batch, entry)
                matched.append(structured)
            total += 1
    return {
        'ok': True,
        'batch': {key: batch[key] for key in
                  ('id', 'timestamp', 'filename', 'count')},
        'query': query,
        'offset': offset,
        'total': total,
        'has_more': offset + len(matched) < total,
        'items': matched,
    }


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
    """下载数据文件并返回包含逐文件状态与错误的报告。

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

    report = {'files': [], 'errors': []}
    for url, filename in [
        (BASE_JSON_GZ_URL, 'base.json.gz'),
        (EXTRA_JSON_GZ_URL, 'extra.json.gz'),
    ]:
        local_path = _local_path(filename)
        try:
            _status(f'正在检查 {filename} ...')
            if not _needs_update(url, local_path):
                _status(f'[跳过] {filename} 已是最新')
                report['files'].append({
                    'filename': filename, 'url': url,
                    'path': local_path, 'status': 'current',
                })
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

            if _load_gz_json(data) is None:
                raise ValueError('下载内容不是有效的 gzip JSON 数据')

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
            report['files'].append({
                'filename': filename, 'url': url, 'path': local_path,
                'status': 'downloaded', 'size': len(data),
            })
        except Exception as e:
            _status(f'[跳过] {filename} 下载失败: {e}')
            error = {
                'filename': filename,
                'url': url,
                'path': local_path,
                'type': type(e).__name__,
                'message': str(e) or repr(e),
            }
            report['errors'].append(error)
            report['files'].append({
                'filename': filename, 'url': url,
                'path': local_path, 'status': 'failed',
            })
    report['ok'] = not report['errors']
    return report


def load_map_from_json_gz(on_status=None, on_progress=None) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """从本地 base.json.gz + extra.json.gz 构建映射字典。"""
    base_path = _local_path('base.json.gz')
    extra_path = _local_path('extra.json.gz')

    def _status(stage, message):
        if on_status:
            on_status(stage, message)

    _status('read_base', '正在解压并解析基础音标数据...')

    try:
        with gzip.open(base_path, 'rt', encoding='utf-8') as f:
            base_data = json.load(f)
    except Exception as e:
        print(f'[错误] 读取 base.json.gz 失败: {e}')
        return None

    extra_data = None
    _status('read_extra', '正在解压并解析扩展注释数据...')
    try:
        with gzip.open(extra_path, 'rt', encoding='utf-8') as f:
            extra_data = json.load(f)
    except Exception as e:
        print(f'[警告] 读取 extra.json.gz 失败 (注释将不可用): {e}')

    _status('build_index', '正在建立字音索引...')
    mapping: Dict[str, List[Dict[str, Any]]] = {}
    total = max(1, len(base_data))
    for i, entry in enumerate(base_data):
        ch = entry.get('z', '')
        phonetic = entry.get('y', '').strip()
        if not ch or not phonetic:
            continue

        note = None
        position = None
        headword = None
        if extra_data and i < len(extra_data):
            ext = extra_data[i]
            position_val = ext.get('c')
            if isinstance(position_val, str) and position_val.strip():
                position = position_val.strip()
            series_head_val = ext.get('m')
            if isinstance(series_head_val, str) and series_head_val.strip():
                series_head = series_head_val.strip()
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

        option = {'phonetic': phonetic, 'note': note}
        if position:
            option['position'] = position
        if series_head:
            option['series_head'] = series_head
        mapping.setdefault(ch, []).append(option)
        if on_progress and (i % 500 == 0 or i + 1 == total):
            on_progress((i + 1) * 100 // total)

    print(f'[加载] 从 JSON 加载了 {len(mapping)} 个字的音标数据')
    return mapping if mapping else None
