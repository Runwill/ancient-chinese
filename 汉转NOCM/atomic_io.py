"""Crash-resistant helpers for small text file writes."""

import json
import os
import tempfile


def write_text_atomic(path, writer, encoding='utf-8'):
    """Write a text file through a flushed temp file and atomic replace."""
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(path) + '.', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            fd = None
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def save_json_atomic(path, data, *, indent=None, newline=False):
    """Atomically save JSON data using the project's UTF-8 settings."""
    def _write(f):
        json.dump(data, f, ensure_ascii=False, indent=indent)
        if newline:
            f.write('\n')

    write_text_atomic(path, _write)
