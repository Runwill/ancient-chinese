"""Configurable NOCM transcription engine."""

import json
import os
import sys
from typing import Dict, Iterable, List, Tuple

from nocm_phonology import apply_replacements, parse_syllable


DEFAULT_SCHEME_ID = 'current_suno'


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


def _pairs(items: Iterable) -> List[Tuple[str, str]]:
    return [(str(old), str(new)) for old, new in items]


class NocmTranscriber:
    """Render NOCM tokens through a configurable transcription scheme."""

    def __init__(self, scheme: Dict):
        self.scheme = scheme
        self.maps = scheme.get('maps', {})
        self.rules = scheme.get('rules', {})
        self.options = scheme.get('options', {})

    def _map_residual(self, text: str) -> str:
        text = apply_replacements(text, _pairs(self.rules.get('residual_replace', [])))
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
            text = apply_replacements(text, _pairs(self.rules.get('pharyngeal_relax', [])))
        if self.options.get('improve_syllable', False):
            text = apply_replacements(text, _pairs(self.rules.get('syllable_relax', [])))
        return apply_replacements(text, _pairs(self.rules.get('post_replace', [])))

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
