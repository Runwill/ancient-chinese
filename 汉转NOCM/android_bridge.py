"""JSON bridge used by the Android WebView host."""

from __future__ import annotations

import json
import os
import traceback


_api = None


def initialize(data_dir):
    """Configure Android storage before importing modules with path globals."""
    global _api
    os.environ['HAN_NOCM_DATA_DIR'] = os.path.abspath(str(data_dir))
    os.environ['HAN_NOCM_RUNTIME'] = 'android'
    os.makedirs(os.environ['HAN_NOCM_DATA_DIR'], exist_ok=True)
    if _api is None:
        from web_api import WebApi
        _api = WebApi()
    return True


def invoke(method, arguments_json='[]'):
    """Invoke one public WebApi method and return a JSON result envelope."""
    try:
        if _api is None:
            raise RuntimeError('Android 后端尚未初始化')
        name = str(method or '')
        if not name or name.startswith('_'):
            raise ValueError('不允许调用该接口')
        target = getattr(_api, name, None)
        if not callable(target):
            raise AttributeError(f'API 不可用: {name}')
        arguments = json.loads(arguments_json or '[]')
        if not isinstance(arguments, list):
            raise ValueError('接口参数必须是数组')
        value = target(*arguments)
        return json.dumps(
            {'ok': True, 'value': value}, ensure_ascii=False,
            separators=(',', ':'))
    except Exception as exc:
        return json.dumps({
            'ok': False,
            'error': str(exc) or type(exc).__name__,
            'type': type(exc).__name__,
            'details': traceback.format_exc(limit=6),
        }, ensure_ascii=False, separators=(',', ':'))
