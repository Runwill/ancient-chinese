"""Configurable NOCM transcription engine."""

import json
import os
import re
import sys
from typing import Dict, List

from atomic_io import save_json_atomic, write_text_atomic
from nocm_phonology import apply_replacements, parse_syllable, replacement_pairs


DEFAULT_SCHEME_ID = 'current_suno'
_SCHEME_ID_PATTERN = re.compile(r'[^A-Za-z0-9_-]+')


def _scheme_pref_path() -> str:
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, '.scheme_pref')


def get_scheme_dir() -> str:
    """Return the directory that stores transcription scheme JSON files."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        external_dir = os.path.join(exe_dir, 'schemes')
        if os.path.isdir(external_dir):
            return external_dir
        base_dir = getattr(sys, '_MEIPASS', exe_dir)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'schemes')


def list_schemes() -> List[Dict[str, str]]:
    """List available scheme metadata."""
    schemes = []
    scheme_dir = get_scheme_dir()
    if not os.path.isdir(scheme_dir):
        return schemes
    for filename in sorted(os.listdir(scheme_dir)):
        if not filename.endswith('.json'):
            continue
        try:
            scheme = load_scheme(filename[:-5])
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        schemes.append({
            'id': scheme.get('id', filename[:-5]),
            'name': scheme.get('name', filename[:-5]),
            'description': scheme.get('description', ''),
        })
    return schemes


def load_scheme(scheme_id: str = DEFAULT_SCHEME_ID) -> Dict:
    """Load one scheme JSON by id."""
    filename = scheme_id if scheme_id.endswith('.json') else f'{scheme_id}.json'
    path = os.path.join(get_scheme_dir(), filename)
    with open(path, 'r', encoding='utf-8') as f:
        scheme = json.load(f)
    if 'maps' not in scheme:
        raise ValueError(f'Invalid scheme: {filename}')
    return scheme


def normalize_scheme_id(value: str) -> str:
    """Return a filesystem-safe scheme id."""
    value = _SCHEME_ID_PATTERN.sub('_', (value or '').strip()).strip('_')
    return value or 'custom_suno'


def load_preferred_scheme_id(default: str = DEFAULT_SCHEME_ID) -> str:
    """Load the last selected scheme, falling back if it is unavailable."""
    try:
        with open(_scheme_pref_path(), 'r', encoding='utf-8') as f:
            preferred = normalize_scheme_id(f.read())
        load_scheme(preferred)
        return preferred
    except (OSError, json.JSONDecodeError, ValueError):
        pass

    try:
        load_scheme(default)
        return default
    except (OSError, json.JSONDecodeError, ValueError):
        schemes = list_schemes()
        return schemes[0]['id'] if schemes else default


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
    scheme['id'] = scheme_id
    if 'maps' not in scheme:
        raise ValueError('Invalid scheme: missing maps')
    scheme_dir = get_scheme_dir()
    os.makedirs(scheme_dir, exist_ok=True)
    path = os.path.join(scheme_dir, f'{scheme_id}.json')
    save_json_atomic(path, scheme, indent=2, newline=True)
    return scheme_id


def clone_scheme(source_id: str = DEFAULT_SCHEME_ID, target_id: str = None,
                 name: str = None) -> Dict:
    """Create an editable copy of an existing scheme in memory."""
    source = load_scheme(source_id)
    target_id = normalize_scheme_id(target_id or f'{source_id}_copy')
    source['id'] = target_id
    source['name'] = name or f"{source.get('name', source_id)} 副本"
    return source


class NocmTranscriber:
    """Render NOCM tokens through a configurable transcription scheme."""

    def __init__(self, scheme: Dict):
        self.scheme = scheme
        self.maps = scheme.get('maps', {})
        self.rules = scheme.get('rules', {})
        self.options = scheme.get('options', {})

    def _map_residual(self, text: str) -> str:
        text = apply_replacements(text, replacement_pairs(
            self.rules.get('residual_replace', []), self.scheme))
        residual_map = self.maps.get('residual', {})
        if residual_map:
            text = apply_replacements(text, residual_map.items())
        return text

    def convert_token(self, token: str) -> str:
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
        return apply_replacements(text, replacement_pairs(
            self.rules.get('post_replace', []), self.scheme))

    def convert_line(self, line: str) -> str:
        parts = []
        for token in line.split():
            if token.startswith('[') and token.endswith(']'):
                parts.append(token)
            else:
                parts.append(self.convert_token(token))
        return ' '.join(parts)

    def convert_text(self, text: str) -> str:
        return '\n'.join(self.convert_line(line) for line in text.splitlines()).strip()


def convert_text(text: str, scheme_id: str = DEFAULT_SCHEME_ID) -> str:
    """Convenience function for one-off conversion."""
    return NocmTranscriber(load_scheme(scheme_id)).convert_text(text)
