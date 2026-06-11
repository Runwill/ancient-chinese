"""自定义控件与通用 UI 工具函数。"""

import ctypes
import sys
import tkinter as tk

from constants import COLORS


# ── Windows 窗口重绘冻结 ─────────────────────────────

_WM_SETREDRAW = 0x000B


def freeze_redraw(widget):
    """冻结控件所在顶层窗口的重绘（Windows）。"""
    if sys.platform == 'win32':
        hwnd = widget.winfo_toplevel().winfo_id()
        ctypes.windll.user32.SendMessageW(hwnd, _WM_SETREDRAW, 0, 0)


def thaw_redraw(widget):
    """恢复重绘并强制刷新（Windows）。"""
    if sys.platform == 'win32':
        hwnd = widget.winfo_toplevel().winfo_id()
        ctypes.windll.user32.SendMessageW(hwnd, _WM_SETREDRAW, 1, 0)
        # RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW
        ctypes.windll.user32.RedrawWindow(hwnd, None, None, 0x0181)


# ── 颜色动画引擎 ────────────────────────────────────────

_anim_registry = {}  # (widget_id, prop_key) -> after_id


def _parse_hex(c):
    """将 #RRGGBB 解析为 (r, g, b)。"""
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _lerp_color(c1, c2, t):
    """在两个 #RRGGBB 颜色之间线性插值。"""
    r1, g1, b1 = _parse_hex(c1)
    r2, g2, b2 = _parse_hex(c2)
    return '#{:02x}{:02x}{:02x}'.format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t))


def _resolve_color(widget, color_str):
    """将颜色名或 hex 字符串统一为 #RRGGBB 格式。"""
    if color_str.startswith('#') and len(color_str) == 7:
        return color_str
    try:
        rgb = widget.winfo_rgb(color_str)
        return '#{:02x}{:02x}{:02x}'.format(rgb[0] >> 8, rgb[1] >> 8, rgb[2] >> 8)
    except Exception:
        return color_str


def animate_color(widget, prop, target, duration=120, steps=8, prop_key=None):
    """平滑过渡控件的某个颜色属性到目标色。"""
    key = (id(widget), prop_key or prop)
    old_id = _anim_registry.pop(key, None)
    if old_id is not None:
        try:
            widget.after_cancel(old_id)
        except Exception:
            pass

    try:
        current = _resolve_color(widget, str(widget.cget(prop)))
    except Exception:
        return
    target_r = _resolve_color(widget, target)
    if current == target_r:
        return

    interval = max(duration // steps, 8)

    def _step(i):
        if i > steps:
            _anim_registry.pop(key, None)
            return
        t = 1 - (1 - i / steps) ** 3          # ease-out cubic
        color = _lerp_color(current, target_r, t)
        try:
            widget.configure(**{prop: color})
        except Exception:
            _anim_registry.pop(key, None)
            return
        if i < steps:
            _anim_registry[key] = widget.after(interval, lambda: _step(i + 1))
        else:
            _anim_registry.pop(key, None)

    _step(1)


def animate_widget_bg(widget, target, duration=120, depth=2):
    """递归地平滑过渡控件及子控件的背景色。"""
    animate_color(widget, 'bg', target, duration)
    if depth > 0:
        for ch in widget.winfo_children():
            animate_widget_bg(ch, target, duration, depth - 1)


# ── 主题样式注册 ────────────────────────────────────────

_style_registry = []  # [(widget, {prop: color_key})]


def style(widget, **mappings):
    """注册控件的颜色绑定并立即应用当前主题色。

    示例: style(lbl, bg='bg_sidebar', fg='text_primary')
    切换主题时调用 apply_theme_transition() 即可平滑过渡所有已注册控件。
    """
    cfg = {prop: COLORS[key] for prop, key in mappings.items()}
    widget.configure(**cfg)
    _style_registry.append((widget, mappings))


def apply_theme_transition(duration=250):
    """将所有已注册控件平滑过渡到当前主题色，自动清理已销毁的控件。"""
    alive = []
    for widget, mappings in _style_registry:
        try:
            if not widget.winfo_exists():
                continue
        except Exception:
            continue
        alive.append((widget, mappings))
        for prop, key in mappings.items():
            animate_color(widget, prop, COLORS[key], duration)
    _style_registry[:] = alive


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
        self._pending_yview = None

    def set_pending_yview(self, pos):
        """设置待恢复的滚动位置，在短时间窗口内持续生效以抵抗多次 _sync 重置。"""
        self._pending_yview = pos
        # 延迟清除，确保窗口期内每次 _sync 都应用保存的位置
        if hasattr(self, '_yview_clear_id'):
            self.after_cancel(self._yview_clear_id)
        self._yview_clear_id = self.after(120, self._clear_pending_yview)

    def _clear_pending_yview(self):
        self._pending_yview = None

    def _sync(self):
        bbox = self.canvas.bbox('all')
        if not bbox:
            return
        ch, cvh = bbox[3] - bbox[1], self.canvas.winfo_height()
        if ch > cvh:
            self.canvas.configure(scrollregion=bbox)
        else:
            self.canvas.configure(scrollregion=(0, 0, bbox[2], cvh))
        if self._pending_yview is not None:
            self.canvas.yview_moveto(self._pending_yview)
        elif ch <= cvh:
            self.canvas.yview_moveto(0)

    def _on_resize(self, e):
        self.canvas.itemconfig(self._win, width=e.width)
        self._sync()

    def on_mousewheel(self, e):
        """处理鼠标滚轮事件（仅内容溢出时滚动）"""
        bbox = self.canvas.bbox('all')
        if bbox and bbox[3] - bbox[1] > self.canvas.winfo_height():
            self.canvas.yview_scroll(-e.delta // 120, 'units')


# ── 通用 hover / 滚轮 / 点击工具 ──────────────────────


def set_widget_bg(widget, bg, depth=1):
    """递归设置控件及子控件背景色。"""
    try:
        widget.configure(bg=bg)
    except tk.TclError:
        pass
    if depth > 0:
        for ch in widget.winfo_children():
            set_widget_bg(ch, bg, depth - 1)


def bind_hover(card, normal_bg, hover_bg=None, depth=2):
    """为卡片及所有子控件绑定悬停变色效果（带动画）"""
    hbg = hover_bg or COLORS['hover_overlay']
    enter = lambda e: animate_widget_bg(card, hbg, depth=depth)
    leave = lambda e: animate_widget_bg(card, normal_bg, depth=depth)
    card.bind('<Enter>', enter)
    card.bind('<Leave>', leave)
    for child in card.winfo_children():
        child.bind('<Enter>', enter)
        child.bind('<Leave>', leave)
        if depth > 1:
            for gc in child.winfo_children():
                gc.bind('<Enter>', enter)
                gc.bind('<Leave>', leave)


def bind_color_hover(widget, props):
    """声明式悬停颜色动画。

    props: {属性名: (常态色, 悬停色)}
    示例: bind_color_hover(btn, {'bg': ('#fff', '#eee'), 'fg': ('#000', '#333')})
    """
    def _enter(e):
        for prop, (_, hover) in props.items():
            animate_color(widget, prop, hover)

    def _leave(e):
        for prop, (normal, _) in props.items():
            animate_color(widget, prop, normal)

    widget.bind('<Enter>', _enter)
    widget.bind('<Leave>', _leave)


def bind_single_double(widget, on_single, on_double, delay=250):
    """为控件绑定单击 / 双击事件，自动区分。"""
    _timer = [None]

    def _single(e):
        if _timer[0]:
            e.widget.after_cancel(_timer[0])
        _timer[0] = e.widget.after(delay, on_single)

    def _double(e):
        if _timer[0]:
            e.widget.after_cancel(_timer[0])
            _timer[0] = None
        on_double()

    widget.bind('<Button-1>', _single)
    widget.bind('<Double-Button-1>', _double)


def bind_mousewheel(widget, handler):
    """递归绑定鼠标滚轮事件到控件及其所有子控件"""
    widget.bind('<MouseWheel>', handler)
    for ch in widget.winfo_children():
        bind_mousewheel(ch, handler)


# ── 现代化胶囊按钮 ──────────────────────────────────


class ModernButton(tk.Canvas):
    """圆角胶囊按钮控件（含 hover 动画）"""

    def __init__(self, parent, text, command=None, primary=False,
                 width=80, height=32, **kwargs):
        # 默认背景跟随父容器，避免在卡片色背景上出现 bg_main 的圆角"漏边"
        if 'bg' not in kwargs:
            try:
                kwargs['bg'] = parent.cget('bg')
            except Exception:
                kwargs['bg'] = COLORS['bg_main']
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, **kwargs)
        self.text = text
        self.command = command
        self.primary = primary
        self.width = width
        self.height = height
        self._hover = False
        self._poly_id = None
        self._text_id = None
        self._current_fill = None

        self._draw()
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)

    def _colors(self):
        """返回 (fill_normal, fill_hover, text_color)。"""
        if self.primary:
            return (COLORS['btn_primary'], COLORS['btn_primary_hover'],
                    '#FFFFFF')
        return (COLORS['btn_secondary'], COLORS['btn_secondary_hover'],
                COLORS.get('btn_text_secondary', COLORS['text_primary']))

    def _draw(self):
        self.delete('all')
        fn, fh, tc = self._colors()
        fill = fh if self._hover else fn
        self._current_fill = fill
        r = self.height // 2  # 胶囊形，半径 = 高度的一半
        self._poly_id = self._round_rect(1, 1, self.width - 1, self.height - 1, r,
                         fill=fill, outline='')
        self._text_id = self.create_text(self.width / 2, self.height / 2, text=self.text,
                         font=('Microsoft YaHei', 9), fill=tc)

    def _round_rect(self, x1, y1, x2, y2, r, **kwargs):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kwargs)

    def _animate_fill(self, target):
        """平滑过渡按钮背景色。"""
        key = (id(self), '_btn_fill')
        old_id = _anim_registry.pop(key, None)
        if old_id is not None:
            try:
                self.after_cancel(old_id)
            except Exception:
                pass

        current = self._current_fill
        if not current or not self._poly_id:
            return
        current_r = _resolve_color(self, current)
        target_r = _resolve_color(self, target)
        if current_r == target_r:
            return

        steps = 8
        interval = 15

        def _step(i):
            if i > steps:
                _anim_registry.pop(key, None)
                return
            t = 1 - (1 - i / steps) ** 3
            color = _lerp_color(current_r, target_r, t)
            self._current_fill = color
            try:
                self.itemconfigure(self._poly_id, fill=color)
            except Exception:
                _anim_registry.pop(key, None)
                return
            if i < steps:
                _anim_registry[key] = self.after(interval, lambda: _step(i + 1))
            else:
                _anim_registry.pop(key, None)

        _step(1)

    def update_theme(self, duration=250):
        """更新按钮颜色以匹配当前主题。"""
        fn, fh, tc = self._colors()
        target = fh if self._hover else fn
        self._animate_fill(target)
        self.itemconfigure(self._text_id, fill=tc)

    def set_text(self, text):
        """更新按钮显示文本。"""
        self.text = text
        self.itemconfigure(self._text_id, text=text)

    def _on_enter(self, e):
        self.config(cursor='hand2')
        self._hover = True
        _, fh, _ = self._colors()
        self._animate_fill(fh)

    def _on_leave(self, e):
        self._hover = False
        fn, _, _ = self._colors()
        self._animate_fill(fn)

    def _on_click(self, e):
        if self.command:
            self.command()
