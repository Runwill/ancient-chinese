"""Release checking and local diagnostic information."""

from __future__ import annotations

import json
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

from app_version import (CHANGELOG, DRAFT_SCHEMA_VERSION, RELEASES_API_URL,
                         RELEASES_PAGE_URL, SCHEME_SCHEMA_VERSION, __version__,
                         get_app_dir, version_tuple)
from draft_io import DRAFTS_DIR, list_drafts
from nocm_transcriber import get_scheme_dir, list_schemes


UPDATE_MANIFEST_NAME = 'update.json'
UPDATE_MANIFEST_SCHEMA = 1


def _read_json_url(url, timeout=12):
    request = urllib.request.Request(
        url, headers={'Accept': 'application/vnd.github+json, application/json',
                      'User-Agent': f'han-to-nocm/{__version__}'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8-sig'))


def _runtime_platform():
    if os.environ.get('HAN_NOCM_RUNTIME') == 'android':
        return 'android'
    return 'windows' if sys.platform == 'win32' else 'unsupported'


def _release_manifest(payload):
    asset = next((item for item in payload.get('assets', [])
                  if item.get('name') == UPDATE_MANIFEST_NAME), None)
    if not asset or not asset.get('browser_download_url'):
        return None
    manifest = _read_json_url(asset['browser_download_url'])
    if int(manifest.get('schema', 0)) != UPDATE_MANIFEST_SCHEMA:
        raise ValueError('更新清单格式不受支持')
    return manifest


def _validate_asset(asset):
    if not isinstance(asset, dict):
        return None
    url = str(asset.get('url', '')).strip()
    filename = os.path.basename(str(asset.get('filename', '')).strip())
    digest = str(asset.get('sha256', '')).strip().lower()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or not parsed.netloc:
        raise ValueError('更新下载地址必须使用 HTTPS')
    if not filename or filename in ('.', '..'):
        raise ValueError('更新清单缺少文件名')
    if len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
        raise ValueError('更新清单缺少有效的 SHA-256')
    return {
        'filename': filename,
        'url': url,
        'sha256': digest,
        'size': max(0, int(asset.get('size', 0) or 0)),
    }


def check_for_updates():
    """Query the configured GitHub release endpoint on explicit user action."""
    try:
        payload = _read_json_url(RELEASES_API_URL, timeout=8)
        latest = str(payload.get('tag_name', '')).lstrip('vV')
        if not latest:
            raise ValueError('发布信息缺少版本号')
        manifest = _release_manifest(payload)
        if manifest and str(manifest.get('version', '')).lstrip('vV') != latest:
            raise ValueError('更新清单版本与 Release 标签不一致')
        runtime = _runtime_platform()
        asset = _validate_asset((manifest or {}).get('assets', {}).get(runtime))
        available = version_tuple(latest) > version_tuple(__version__)
        return {
            'ok': True,
            'current': __version__,
            'latest': latest,
            'available': available,
            'url': payload.get('html_url') or RELEASES_PAGE_URL,
            'notes': (manifest or {}).get('notes') or payload.get('body', ''),
            'published_at': payload.get('published_at', ''),
            'platform': runtime,
            'asset': asset,
            'can_install': bool(available and asset and (
                runtime == 'android' or getattr(sys, 'frozen', False))),
        }
    except (OSError, ValueError, urllib.error.URLError,
            json.JSONDecodeError) as exc:
        return {
            'ok': False, 'current': __version__,
            'message': f'无法获取版本信息：{exc}',
            'url': RELEASES_PAGE_URL,
        }


def _updates_dir():
    path = os.path.join(get_app_dir(), 'updates')
    os.makedirs(path, exist_ok=True)
    return path


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().lower()


def download_update():
    """Download and verify the current platform asset from the latest release."""
    update = check_for_updates()
    if not update.get('ok'):
        raise RuntimeError(update.get('message') or '无法检查更新')
    if not update.get('available'):
        raise RuntimeError('当前已经是最新版本')
    asset = update.get('asset')
    if not asset:
        raise RuntimeError('此版本没有适用于当前平台的更新包')
    destination = os.path.join(_updates_dir(), asset['filename'])
    temporary = f'{destination}.part'
    try:
        request = urllib.request.Request(
            asset['url'], headers={'User-Agent': f'han-to-nocm/{__version__}'})
        with urllib.request.urlopen(request, timeout=45) as response, \
                open(temporary, 'wb') as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if asset['size'] and os.path.getsize(temporary) != asset['size']:
            raise ValueError('更新包大小与发布清单不一致')
        actual = _sha256(temporary)
        if actual != asset['sha256']:
            raise ValueError('更新包 SHA-256 校验失败')
        os.replace(temporary, destination)
        verification = {
            'schema': UPDATE_MANIFEST_SCHEMA,
            'version': update['latest'],
            'platform': update['platform'],
            'filename': asset['filename'],
            'sha256': asset['sha256'],
        }
        with open(f'{destination}.verified.json', 'w', encoding='utf-8') as file:
            json.dump(verification, file, ensure_ascii=False)
        return {
            'ok': True, 'path': destination, 'filename': asset['filename'],
            'version': update['latest'], 'platform': update['platform'],
            'sha256': actual,
        }
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass


def validate_downloaded_update(path):
    """Revalidate a downloaded asset before handing it to an installer."""
    path = os.path.abspath(str(path or ''))
    root = os.path.abspath(_updates_dir())
    if os.path.commonpath((path, root)) != root or not os.path.isfile(path):
        raise ValueError('更新包不在受信任的下载目录中')
    metadata_path = f'{path}.verified.json'
    with open(metadata_path, encoding='utf-8') as file:
        metadata = json.load(file)
    if metadata.get('platform') != _runtime_platform():
        raise ValueError('更新包与当前平台不匹配')
    if metadata.get('filename') != os.path.basename(path):
        raise ValueError('更新包文件名与校验记录不一致')
    if _sha256(path) != metadata.get('sha256'):
        raise ValueError('更新包在下载后发生了变化')
    return {'ok': True, 'path': path, **metadata}


def launch_windows_update(path):
    """Launch a detached helper which replaces this frozen executable."""
    verified = validate_downloaded_update(path)
    if _runtime_platform() != 'windows' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Windows 自动替换仅适用于打包后的 EXE')
    target = os.path.abspath(sys.executable)
    script = os.path.join(_updates_dir(), 'apply-update.ps1')
    content = r'''param([int]$AppPid, [string]$Source, [string]$Target, [string]$Cleanup)
$ErrorActionPreference = 'Stop'
try { Wait-Process -Id $AppPid -Timeout 45 -ErrorAction SilentlyContinue } catch {}
$installed = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        Copy-Item -LiteralPath $Source -Destination $Target -Force
        $installed = $true
        break
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $installed) { exit 1 }
Start-Process -FilePath $Target
Remove-Item -LiteralPath $Source -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Cleanup -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
'''
    with open(script, 'w', encoding='utf-8-sig', newline='\r\n') as file:
        file.write(content)
    flags = (getattr(subprocess, 'CREATE_NO_WINDOW', 0)
             | getattr(subprocess, 'DETACHED_PROCESS', 0))
    subprocess.Popen([
        'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', script, '-AppPid', str(os.getpid()), '-Source', verified['path'],
        '-Target', target, '-Cleanup', f"{verified['path']}.verified.json",
    ], creationflags=flags, close_fds=True)
    return {'ok': True, 'scheduled': True, 'version': verified['version']}


def diagnostic_info():
    """Return non-sensitive local runtime and data-path diagnostics."""
    try:
        webview_version = version('pywebview')
    except PackageNotFoundError:
        webview_version = '未安装'
    app_dir = get_app_dir()
    runtime = os.environ.get('HAN_NOCM_RUNTIME', '').strip().lower()
    if runtime == 'android':
        runtime_mode = 'Android APK'
    elif getattr(sys, 'frozen', False):
        runtime_mode = '单文件 EXE'
    else:
        runtime_mode = '源码'
    data_files = {}
    for filename in ('base.json.gz', 'extra.json.gz', 'changed_chars.json'):
        path = os.path.join(app_dir, filename)
        if os.path.isfile(path):
            stat = os.stat(path)
            data_files[filename] = {
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
    return {
        'app_version': __version__,
        'draft_schema_version': DRAFT_SCHEMA_VERSION,
        'scheme_schema_version': SCHEME_SCHEMA_VERSION,
        'python': platform.python_version(),
        'python_executable': sys.executable,
        'platform': platform.platform(),
        'frozen': bool(getattr(sys, 'frozen', False)),
        'runtime_mode': runtime_mode,
        'webview': webview_version,
        'app_dir': app_dir,
        'draft_dir': DRAFTS_DIR,
        'scheme_dir': get_scheme_dir(),
        'log_path': os.path.join(app_dir, 'data_update.log'),
        'draft_count': len(list_drafts()),
        'scheme_count': len(list_schemes()),
        'data_files': data_files,
        'changelog': CHANGELOG,
        'releases_url': RELEASES_PAGE_URL,
    }
