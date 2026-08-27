"""PBOC syllable parsing utilities."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Tuple


DEFAULT_TONE_ORDER = ['ps', 'ts', 'ks', 'ʔs', 'ʔ', 's', 'p', 't', 'k', 'h']
DEFAULT_CODA_ORDER = ['w', 'm', 'j', 'r', 'n', 'ŋ']
DEFAULT_NUCLEUS_ORDER = ['a', 'A', 'e', 'o', 'ə', 'i', 'u']
DEFAULT_ONSET_ORDER = [
    'tsh', 'ts', 'dz', 'st', 's', 'th', 't', 'd', 'ph', 'p', 'b',
    'kh', 'k', 'g', 'm̥', 'm', 'n̥', 'n', 'r̥', 'r', 'C.r', 'l̥',
    'l', 'ŋ̊', 'ŋ', 'ʔ', 'h', 'ẘ', 'w',
]
DEFAULT_GLIDE_ORDER = ['r', 'ˤr', 'lˤ', 'l', 'wˤ', 'w', 'j̊', 'j', 'ˤ']


@dataclass(frozen=True)
class NocmSyllable:
    """Parsed PBOC syllable components."""

    original: str
    onset: str = ''
    glide: str = ''
    residual: str = ''
    nucleus: str = ''
    coda: str = ''
    tone: str = ''


def apply_replacements(text: str, replacements: Iterable[Tuple[str, str]]) -> str:
    """Apply ordered literal replacement pairs."""
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def resolve_rule_lookup(lookup, scheme: Dict = None) -> str:
    """Resolve a rule lookup string or map-concatenation expression."""
    if lookup is None:
        return ''
    if isinstance(lookup, dict) and lookup.get('type') == 'map_concat':
        maps = (scheme or {}).get('maps', {})
        field = lookup.get('field', 'target')
        parts = lookup.get('parts', [])
        resolved = []
        for part in parts:
            section = key = ''
            if isinstance(part, dict):
                section = str(part.get('section', ''))
                key = str(part.get('key', ''))
            elif isinstance(part, (list, tuple)) and len(part) >= 2:
                section = str(part[0])
                key = str(part[1])
            if not section or not key:
                continue
            if field == 'source':
                resolved.append(key)
            else:
                resolved.append(str(maps.get(section, {}).get(key, key)))
        return ''.join(resolved)
    return str(lookup)


def replacement_pairs(
        replacements: Iterable, scheme: Dict = None) -> List[Tuple[str, str]]:
    """Normalize legacy and structured replacement rules into literal pairs."""
    pairs = []
    for item in replacements or []:
        if isinstance(item, dict):
            old = item.get('find', item.get('old', ''))
            new = item.get('replace', item.get('new', ''))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            old, new = item[0], item[1]
        else:
            continue
        old = resolve_rule_lookup(old, scheme)
        if old == '':
            continue
        pairs.append((old, '' if new is None else str(new)))
    return pairs


def _ordered_keys(source: Mapping[str, str], order: Iterable[str] = None) -> List[str]:
    if order:
        keys = [key for key in order if key in source]
        keys.extend(key for key in source if key not in keys)
        return keys
    return list(source.keys())


def mapping_pairs(source: Mapping[str, str], order: Iterable[str] = None):
    """Return mapping pairs in the same explicit or table order shown by the editor."""
    return [(key, source[key]) for key in _ordered_keys(source, order)]


def consume_suffix(text: str, source: Mapping[str, str], order: Iterable[str] = None):
    """Consume a suffix according to the explicit or mapping-table order."""
    for key in _ordered_keys(source, order):
        if key and text.endswith(key):
            return text[:-len(key)], key
    return text, ''


def consume_prefix(text: str, source: Mapping[str, str], order: Iterable[str] = None):
    """Consume a prefix according to the explicit or mapping-table order."""
    for key in _ordered_keys(source, order):
        if key and text.startswith(key):
            return text[len(key):], key
    return text, ''


def parse_syllable(token: str, scheme: Dict = None) -> NocmSyllable:
    """Parse one PBOC token into phonological components."""
    scheme = scheme or {}
    maps = scheme.get('maps', {})
    parse_order = scheme.get('parse_order', {})
    rules = scheme.get('rules', {})

    text = apply_replacements(token, replacement_pairs(
        rules.get('pre_normalize', []), scheme))

    text, tone = consume_suffix(
        text, maps.get('tone', {}), parse_order.get('tone'))
    text, coda = consume_suffix(
        text, maps.get('coda', {}), parse_order.get('coda'))
    text, onset = consume_prefix(
        text, maps.get('onset', {}), parse_order.get('onset'))
    text, glide = consume_prefix(
        text, maps.get('glide', {}), parse_order.get('glide'))

    text = apply_replacements(text, replacement_pairs(
        rules.get('residual_preprocess', []), scheme))
    text, nucleus = consume_suffix(
        text, maps.get('nucleus', {}), parse_order.get('nucleus'))

    return NocmSyllable(
        original=token,
        onset=onset,
        glide=glide,
        residual=text,
        nucleus=nucleus,
        coda=coda,
        tone=tone,
    )
