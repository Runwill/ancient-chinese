"""汉字转 NOCM 音标 — 主入口。"""

import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from data_loader import download_and_update, load_map_from_json_gz
from gui import App, COLORS


def _fatal(msg):
    """显示错误弹窗后退出。"""
    _tmp = tk.Tk()
    _tmp.withdraw()
    messagebox.showerror('错误', msg)
    _tmp.destroy()
    sys.exit(1)


class SplashScreen(tk.Tk):
    """启动画面：显示数据下载/加载进度（现代化样式）。"""

    def __init__(self):
        super().__init__()
        self.title('汉字转 NOCM 音标')
        self.resizable(False, False)
        self.overrideredirect(True)
        self.configure(bg=COLORS['bg_card'])

        # 主容器
        frame = tk.Frame(self, bg=COLORS['bg_card'], padx=40, pady=32)
        frame.pack()

        # 标题
        tk.Label(frame, text='汉字转 NOCM 音标',
                font=('Microsoft YaHei', 18, 'bold'),
                bg=COLORS['bg_card'], fg=COLORS['text_primary']).pack(pady=(0, 20))

        # 状态文本
        self.status_var = tk.StringVar(value='正在初始化...')
        tk.Label(frame, textvariable=self.status_var,
                font=('Microsoft YaHei', 9),
                bg=COLORS['bg_card'], fg=COLORS['text_secondary']).pack(pady=(0, 10))

        # 进度条容器
        progress_frame = tk.Frame(frame, bg=COLORS['bg_card'])
        progress_frame.pack(fill=tk.X, pady=(0, 8))
        
        # 自定义进度条背景
        self.progress_bg = tk.Canvas(progress_frame, width=340, height=8,
                                     bg=COLORS['border_light'], highlightthickness=0)
        self.progress_bg.pack()
        
        # 进度条填充
        self._progress_fill = self.progress_bg.create_rectangle(
            0, 0, 0, 8, fill=COLORS['accent'], outline='')
        
        self._progress_value = 0
        self._indeterminate = False
        self._indeterminate_pos = 0

        # 居中
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f'+{x}+{y}')

        self.mapping = None
        self._error = None

    def _animate_indeterminate(self):
        if not self._indeterminate:
            return
        self._indeterminate_pos = (self._indeterminate_pos + 5) % 340
        width = 80
        x1 = self._indeterminate_pos
        x2 = min(x1 + width, 340)
        self.progress_bg.coords(self._progress_fill, x1, 0, x2, 8)
        if x1 + width > 340:
            # 绘制环绕部分
            pass
        self.after(30, self._animate_indeterminate)

    def on_status(self, msg):
        self.status_var.set(msg)
        self.update_idletasks()

    def on_progress(self, pct, name):
        if pct < 0:
            if not self._indeterminate:
                self._indeterminate = True
                self._animate_indeterminate()
        else:
            self._indeterminate = False
            self._progress_value = pct
            fill_width = int(340 * pct / 100)
            self.progress_bg.coords(self._progress_fill, 0, 0, fill_width, 8)
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
