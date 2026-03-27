"""自定义控件与通用 UI 工具函数。"""

import tkinter as tk

from constants import COLORS


# ── 可滚动容器 ──────────────────────────────────────


class ScrollableFrame(tk.Frame):
    """隐藏滚动条的可滚动区域。子控件添加到 ``inner`` 属性上。"""

    def __init__(self, parent, bg='white', **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.inner.bind('<Configure>', lambda e: self._sync())
        self.canvas.bind('<Configure>', self._on_resize)

    def _sync(self):
        self.canvas.update_idletasks()
        bbox = self.canvas.bbox('all')
        if not bbox:
            return
        ch, cvh = bbox[3] - bbox[1], self.canvas.winfo_height()
        if ch > cvh:
            self.canvas.configure(scrollregion=bbox)
        else:
            self.canvas.configure(scrollregion=(0, 0, bbox[2], cvh))
            self.canvas.yview_moveto(0)

    def _on_resize(self, e):
        self.canvas.itemconfig(self._win, width=e.width)
        self._sync()

    def on_mousewheel(self, e):
        """处理鼠标滚轮事件（仅内容溢出时滚动）"""
        bbox = self.canvas.bbox('all')
        if bbox and bbox[3] - bbox[1] > self.canvas.winfo_height():
            self.canvas.yview_scroll(-e.delta // 120, 'units')


# ── 通用 hover / 滚轮工具 ──────────────────────────


def _set_bg(widget, bg, depth=2):
    """递归设置控件及子控件背景色"""
    try:
        widget.configure(bg=bg)
    except tk.TclError:
        pass
    if depth > 0:
        for ch in widget.winfo_children():
            _set_bg(ch, bg, depth - 1)


def bind_hover(card, normal_bg, hover_bg=None, depth=2):
    """为卡片及所有子控件绑定悬停变色效果"""
    hbg = hover_bg or COLORS['border_light']
    enter = lambda e: _set_bg(card, hbg, depth)
    leave = lambda e: _set_bg(card, normal_bg, depth)
    card.bind('<Enter>', enter)
    card.bind('<Leave>', leave)
    for child in card.winfo_children():
        child.bind('<Enter>', enter)
        child.bind('<Leave>', leave)
        if depth > 1:
            for gc in child.winfo_children():
                gc.bind('<Enter>', enter)
                gc.bind('<Leave>', leave)


def bind_mousewheel(widget, handler):
    """递归绑定鼠标滚轮事件到控件及其所有子控件"""
    widget.bind('<MouseWheel>', handler)
    for ch in widget.winfo_children():
        bind_mousewheel(ch, handler)


# ── 现代化圆角按钮 ──────────────────────────────────


class ModernButton(tk.Canvas):
    """现代化圆角按钮"""
    def __init__(self, parent, text, command=None, primary=False, width=80, height=32, **kwargs):
        super().__init__(parent, width=width, height=height, 
                        highlightthickness=0, bg=COLORS['bg_main'], **kwargs)
        self.text = text
        self.command = command
        self.primary = primary
        self.width = width
        self.height = height
        self._hovered = False
        
        self._draw()
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)
    
    def _draw(self):
        self.delete('all')
        r = 6  # 圆角半径
        if self.primary:
            fill = COLORS['btn_primary_hover'] if self._hovered else COLORS['btn_primary']
            text_color = '#FFFFFF'
        else:
            fill = COLORS['btn_secondary_hover'] if self._hovered else COLORS['btn_secondary']
            text_color = COLORS['text_primary']
        
        # 绘制圆角矩形
        self._round_rect(2, 2, self.width-2, self.height-2, r, fill=fill, outline='')
        # 绘制文字
        self.create_text(self.width/2, self.height/2, text=self.text,
                        font=('Microsoft YaHei', 9), fill=text_color)
    
    def _round_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1
        ]
        return self.create_polygon(points, smooth=True, **kwargs)
    
    def _on_enter(self, e):
        self._hovered = True
        self._draw()
        self.config(cursor='hand2')
    
    def _on_leave(self, e):
        self._hovered = False
        self._draw()
    
    def _on_click(self, e):
        if self.command:
            self.command()
