"""NOCM syllable parsing utilities."""

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
    """Parsed NOCM syllable components."""

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


def _ordered_keys(source: Mapping[str, str], order: Iterable[str] = None) -> List[str]:
    if order:
        keys = [key for key in order if key in source]
        keys.extend(key for key in source if key not in keys)
        return keys
    return sorted(source.keys(), key=len, reverse=True)


def consume_suffix(text: str, source: Mapping[str, str], order: Iterable[str] = None):
    """Consume a suffix according to an explicit order or longest-match order."""
    for key in _ordered_keys(source, order):
        if key and text.endswith(key):
            return text[:-len(key)], key
    return text, ''


def consume_prefix(text: str, source: Mapping[str, str], order: Iterable[str] = None):
    """Consume a prefix according to an explicit order or longest-match order."""
    for key in _ordered_keys(source, order):
        if key and text.startswith(key):
            return text[len(key):], key
    return text, ''


def parse_syllable(token: str, scheme: Dict = None) -> NocmSyllable:
    """Parse one NOCM token into phonological components."""
    scheme = scheme or {}
    maps = scheme.get('maps', {})
    parse_order = scheme.get('parse_order', {})
    rules = scheme.get('rules', {})

    text = apply_replacements(token, rules.get('pre_normalize', []))

    text, tone = consume_suffix(
        text, maps.get('tone', {}), parse_order.get('tone', DEFAULT_TONE_ORDER))
    text, coda = consume_suffix(
        text, maps.get('coda', {}), parse_order.get('coda', DEFAULT_CODA_ORDER))
    text, onset = consume_prefix(
        text, maps.get('onset', {}), parse_order.get('onset', DEFAULT_ONSET_ORDER))
    text, glide = consume_prefix(
        text, maps.get('glide', {}), parse_order.get('glide', DEFAULT_GLIDE_ORDER))

    text = apply_replacements(text, rules.get('residual_preprocess', []))
    text, nucleus = consume_suffix(
        text, maps.get('nucleus', {}), parse_order.get('nucleus', DEFAULT_NUCLEUS_ORDER))

    return NocmSyllable(
        original=token,
        onset=onset,
        glide=glide,
        residual=text,
        nucleus=nucleus,
        coda=coda,
        tone=tone,
    )
