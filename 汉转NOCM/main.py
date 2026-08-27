"""汉字转 PBOC 音标桌面程序入口。"""

from __future__ import annotations

import os
import importlib
import subprocess
import sys

from app_version import APP_NAME, __version__


def _fatal(message):
    """Display a native Windows error without importing the legacy UI."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), '汉字转 PBOC 音标', 0x10)
    except Exception:
        print(message, file=sys.stderr)
    raise SystemExit(1)


def _load_webview():
    """Import pywebview, bootstrapping it for source-tree launches."""
    try:
        return importlib.import_module('webview')
    except ImportError as first_error:
        if getattr(sys, 'frozen', False):
            _fatal(f'打包程序缺少 HTML 界面组件：\n{first_error}')

    requirements = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'requirements.txt')
    try:
        completed = subprocess.run(
            [sys.executable, '-m', 'pip', 'install',
             '--disable-pip-version-check', '-r', requirements],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            check=False,
        )
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or '').strip()
            raise RuntimeError(details or f'pip 退出代码 {completed.returncode}')
        importlib.invalidate_caches()
        return importlib.import_module('webview')
    except Exception as exc:
        _fatal(
            'HTML 界面组件自动安装失败。\n\n'
            f'当前 Python：{sys.executable}\n'
            f'错误：{exc}')


def run_legacy():
    """Temporary Tkinter fallback while the HTML migration settles."""
    import threading
    import tkinter as tk
    from tkinter import messagebox

    from data_loader import download_and_update, load_map_from_json_gz
    from gui import App, COLORS

    splash = tk.Tk()
    splash.title('汉字转 PBOC 音标')
    splash.geometry('420x170')
    splash.resizable(False, False)
    splash.configure(bg=COLORS['bg_card'])
    status = tk.StringVar(value='正在初始化...')
    tk.Label(splash, text='汉字转 PBOC 音标', font=('Microsoft YaHei', 18, 'bold'),
             bg=COLORS['bg_card'], fg=COLORS['text_primary']).pack(pady=(34, 16))
    tk.Label(splash, textvariable=status, font=('Microsoft YaHei', 9),
             bg=COLORS['bg_card'], fg=COLORS['text_muted']).pack()
    result = {'mapping': None, 'error': None}

    def worker():
        try:
            download_and_update(on_status=lambda text: splash.after(0, status.set, text))
            result['mapping'] = load_map_from_json_gz()
        except Exception as exc:
            result['error'] = str(exc)
        splash.after(0, splash.destroy)

    threading.Thread(target=worker, daemon=True).start()
    splash.mainloop()
    if result['error'] or result['mapping'] is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('启动失败', result['error'] or '无法加载音节数据。')
        root.destroy()
        raise SystemExit(1)
    app = App(result['mapping'])
    app.mainloop()


def main():
    if '--version' in sys.argv:
        print(f'{APP_NAME} {__version__}')
        return
    if '--legacy' in sys.argv:
        run_legacy()
        return
    webview = _load_webview()

    from web_api import WebApi, web_asset_path
    from constants import get_theme

    index_path = web_asset_path()
    if not os.path.isfile(index_path):
        _fatal(f'找不到界面文件：\n{index_path}')

    api = WebApi()
    window = webview.create_window(
        APP_NAME,
        url=index_path,
        js_api=api,
        width=1280,
        height=780,
        min_size=(960, 600),
        background_color='#1D2226' if get_theme() == 'dark' else '#F4F6F8',
        text_select=True,
    )
    api.set_window(window)
    try:
        webview.start(gui='edgechromium', debug='--debug-webview' in sys.argv)
    except Exception as exc:
        _fatal(f'HTML 界面启动失败：\n{exc}\n\n请确认系统已安装 Microsoft Edge WebView2 Runtime。')


if __name__ == '__main__':
    main()
