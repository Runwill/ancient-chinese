"""Generate deterministic GitHub Release metadata for the current version."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_version import CHANGELOG, __version__


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default='Runwill/ancient-chinese')
    parser.add_argument('--windows', required=True, type=Path)
    parser.add_argument('--android', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    if CHANGELOG[0]['version'] != __version__:
        raise SystemExit('CHANGELOG first entry does not match __version__')
    for path in (args.windows, args.android):
        if not path.is_file():
            raise SystemExit(f'Release asset not found: {path}')

    args.output.mkdir(parents=True, exist_ok=True)
    notes = CHANGELOG[0]
    notes_text = '\n'.join(f'- {item}' for item in notes['items'])
    (args.output / 'release-notes.md').write_text(
        f"## {notes['title']}\n\n{notes_text}\n",
        encoding='utf-8', newline='\n')

    def asset(path: Path) -> dict:
        filename = path.name
        return {
            'filename': filename,
            'url': (f'https://github.com/{args.repo}/releases/download/'
                    f'v{__version__}/{quote(filename)}'),
            'sha256': sha256(path),
            'size': path.stat().st_size,
        }

    manifest = {
        'schema': 1,
        'version': __version__,
        'published_at': notes['date'],
        'notes': '\n'.join(notes['items']),
        'assets': {
            'windows': asset(args.windows),
            'android': asset(args.android),
        },
    }
    (args.output / 'update.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8', newline='\n')
    sums = '\n'.join(
        f"{sha256(path)}  {path.name}" for path in (args.windows, args.android))
    (args.output / 'SHA256SUMS.txt').write_text(
        sums + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
