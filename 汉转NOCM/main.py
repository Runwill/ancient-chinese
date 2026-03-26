"""汉字转 NOCM 音标 — 主入口。"""

import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from data_loader import download_and_update, load_map_from_json_gz
from gui import App


def _fatal(msg):
    """显示错误弹窗后退出。"""
    _tmp = tk.Tk()
    _tmp.withdraw()
    messagebox.showerror('错误', msg)
    _tmp.destroy()
    sys.exit(1)


class SplashScreen(tk.Tk):
    """启动画面：显示数据下载/加载进度。"""

    def __init__(self):
        super().__init__()
        self.title('汉字转 NOCM 音标')
        self.resizable(False, False)
        self.overrideredirect(True)

        frame = ttk.Frame(self, padding=20)
        frame.pack()

        ttk.Label(frame, text='汉字转 NOCM 音标',
                  font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 10))

        self.status_var = tk.StringVar(value='正在初始化...')
        ttk.Label(frame, textvariable=self.status_var,
                  font=('Microsoft YaHei', 9)).pack(pady=(0, 6))

        self.progress = ttk.Progressbar(frame, length=320, mode='determinate')
        self.progress.pack(pady=(0, 4))

        # 居中
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f'+{x}+{y}')

        self.mapping = None
        self._error = None

    def on_status(self, msg):
        self.status_var.set(msg)
        self.update_idletasks()

    def on_progress(self, pct, name):
        if pct < 0:
            if str(self.progress.cget('mode')) != 'indeterminate':
                self.progress.configure(mode='indeterminate')
                self.progress.start(15)
        else:
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.progress['value'] = pct
        self.update_idletasks()

    def _worker(self):
        try:
            download_and_update(
                on_status=lambda msg: self.after(0, self.on_status, msg),
                on_progress=lambda p, n: self.after(0, self.on_progress, p, n),
            )
            self.after(0, self.on_status, '正在加载音标数据...')
            self.mapping = load_map_from_json_gz()
        except Exception as e:
            self._error = str(e)
        finally:
            self.after(0, self._on_done)

    def _on_done(self):
        self.destroy()

    def run(self):
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        self.mainloop()
        return self.mapping, self._error


def main():
    splash = SplashScreen()
    mapping, error = splash.run()

    if error:
        _fatal(f'启动失败:\n{error}')
    if mapping is None:
        _fatal('无法加载音节数据。\n请检查网络连接或确保数据文件存在。')

    app = App(mapping)
    app.mainloop()


if __name__ == '__main__':
    main()
