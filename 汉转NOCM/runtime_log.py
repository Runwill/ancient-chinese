"""In-memory capture for stdout/stderr in the windowed desktop build."""

from __future__ import annotations

import sys
import threading
from datetime import datetime


_MAX_CHARS = 250_000
_LOCK = threading.RLock()
_TEXT = ''
_STARTED_AT = datetime.now().astimezone().isoformat(timespec='seconds')
_INSTALLED = False


def _append(text):
    global _TEXT
    value = str(text or '')
    if not value:
        return
    with _LOCK:
        _TEXT = (_TEXT + value)[-_MAX_CHARS:]


class _CapturedStream:
    def __init__(self, original):
        self.original = original

    @property
    def encoding(self):
        return getattr(self.original, 'encoding', None) or 'utf-8'

    @property
    def errors(self):
        return getattr(self.original, 'errors', None) or 'replace'

    def write(self, text):
        _append(text)
        if self.original is not None:
            self.original.write(text)
        return len(text or '')

    def flush(self):
        if self.original is not None:
            self.original.flush()

    def isatty(self):
        return bool(self.original and self.original.isatty())

    def fileno(self):
        if self.original is None:
            raise OSError('captured stream has no file descriptor')
        return self.original.fileno()

    def writable(self):
        return True


def install_output_capture():
    """Capture process output while preserving a source-launch console."""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        sys.stdout = _CapturedStream(sys.stdout)
        sys.stderr = _CapturedStream(sys.stderr)
        _INSTALLED = True


def write_runtime_log(message):
    timestamp = datetime.now().astimezone().strftime('%H:%M:%S')
    _append(f'[{timestamp}] {message}\n')


def get_runtime_logs():
    with _LOCK:
        return {
            'text': _TEXT,
            'started_at': _STARTED_AT,
            'characters': len(_TEXT),
        }


def clear_runtime_logs():
    global _TEXT
    with _LOCK:
        _TEXT = ''
