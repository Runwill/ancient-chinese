"""侧边栏：多音字读音选择面板。"""

import re
import tkinter as tk

from constants import COLORS
from widgets import ScrollableFrame, bind_hover, bind_color_hover, bind_mousewheel, freeze_redraw, thaw_redraw


def _format_note(note_txt):
    """格式化注释文本：在数字+汉字前插入换行。"""
    if not note_txt:
        return note_txt
    s = note_txt.strip()
    s = re.sub(r'(?<!^)(?<![\n\d])(\d+)(?=[\u4e00-\u9fff])', r'\n\1', s)
    return s


def build_placeholder(sidebar):
    """构建占位内容（无多音字被选中时显示）"""
    for w in sidebar.winfo_children():
        w.destroy()
    box = tk.Frame(sidebar, bg=COLORS['bg_sidebar'])
    box.pack(fill=tk.BOTH, expand=True)
    center = tk.Frame(box, bg=COLORS['bg_sidebar'])
    center.place(relx=0.5, rely=0.5, anchor='center')
    tk.Label(center, text='✎', font=('Segoe UI Symbol', 28),
             bg=COLORS['bg_sidebar'], fg=COLORS['text_muted']).pack()
    tk.Label(center, text='点击多音字\n选择读音',
             font=('Microsoft YaHei', 10),
             bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
             justify='center').pack(pady=(10, 0))


def build_options(sidebar, li, ci, char, info, buffer, on_apply):
    """构建读音选项面板。on_apply(li, ci, phonetic, global_apply)"""
    # 保存滚动位置
    scroll_pos = None
    for w in sidebar.winfo_children():
        if isinstance(w, ScrollableFrame):
            try:
                scroll_pos = w.canvas.yview()[0]
            except tk.TclError:
                pass
            break

    freeze_redraw(sidebar)
    try:
        for w in sidebar.winfo_children():
            w.destroy()
        opts = info['options']
        if not opts:
            build_placeholder(sidebar)
            return

        # 头部
        hdr = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16, pady=14)
        hdr.pack(fill=tk.X)
        row = tk.Frame(hdr, bg=COLORS['bg_sidebar'])
        row.pack(fill=tk.X)
        tk.Label(row, text=char, font=('Microsoft YaHei', 24, 'bold'),
                 bg=COLORS['bg_sidebar'], fg=COLORS['poly_orange']).pack(side=tk.LEFT)
        detail_col = tk.Frame(row, bg=COLORS['bg_sidebar'])
        detail_col.pack(side=tk.LEFT, padx=(12, 0), fill=tk.Y)
        tk.Label(detail_col, text='选择读音', font=('Microsoft YaHei', 10),
                 bg=COLORS['bg_sidebar'], fg=COLORS['text_secondary']
                 ).pack(anchor='w', pady=(4, 0))

        tk.Frame(sidebar, bg=COLORS['divider'], height=1).pack(fill=tk.X, padx=16)

        total = sum(ln.count(char) for ln in buffer)

        sf = ScrollableFrame(sidebar, bg=COLORS['bg_sidebar'])
        sf.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for o in opts:
            _build_card(sf.inner, o, info, li, ci, total, on_apply)
        bind_mousewheel(sf.inner, sf.on_mousewheel)
        sf.canvas.bind('<MouseWheel>', sf.on_mousewheel)

        if scroll_pos is not None:
            sf.set_pending_yview(scroll_pos)

        sidebar.update_idletasks()
    finally:
        thaw_redraw(sidebar)


def _create_note_widget(parent, note_txt, bg):
    """创建带《》书名号着色的注释文本控件。"""
    tw = tk.Text(parent, wrap=tk.WORD, bg=bg, fg=COLORS['text_muted'],
                 font=('Microsoft YaHei', 9),
                 borderwidth=0, highlightthickness=0,
                 cursor='hand2', height=1,
                 padx=0, pady=0, spacing1=0, spacing3=0)
    tw.tag_configure('book', foreground='#00897B')
    tw.tag_configure('idx', foreground=COLORS['accent'])
    # 同时匹配行首序号(数字+紧跟汉字)和《》书名号
    for part in re.split(r'((?:^|\n)\d+(?=[\u4e00-\u9fff])|《[^》]*》)', note_txt):
        if not part:
            continue
        if part.startswith('《') and part.endswith('》'):
            tw.insert(tk.END, part, 'book')
        elif re.match(r'^(?:\n)?\d+$', part):
            tw.insert(tk.END, part, 'idx')
        else:
            tw.insert(tk.END, part)
    tw.configure(state=tk.DISABLED)

    _last_h = [0]

    def _fit_height(e=None):
        tw.update_idletasks()
        try:
            n = tw.count('1.0', 'end', 'displaylines')
            if isinstance(n, (list, tuple)):
                n = n[0]
            h = max(n or 1, 1)
            if h != _last_h[0]:
                _last_h[0] = h
                tw.configure(height=h)
        except (tk.TclError, TypeError):
            pass
    tw.bind('<Configure>', _fit_height, add='+')
    return tw


def _build_card(parent, opt, info, li, ci, total, on_apply):
    """构建单个读音选项卡片"""
    phon = opt.get('phonetic') if isinstance(opt, dict) else str(opt)
    note_raw = opt.get('note') if isinstance(opt, dict) else None
    note_txt = _format_note(str(note_raw).strip()) if note_raw else ''
    is_cur = info['phonetic'] == phon

    bg = COLORS['accent_light'] if is_cur else COLORS['bg_card']
    border = COLORS['accent'] if is_cur else COLORS['border_light']

    card = tk.Frame(parent, bg=bg, highlightbackground=border,
                    highlightthickness=1, padx=12, pady=10)
    card.pack(fill=tk.X, pady=3, padx=6)

    row = tk.Frame(card, bg=bg)
    row.pack(fill=tk.X)

    lbl = tk.Label(row, text=phon, font=('Consolas', 13, 'bold'),
                   bg=bg, fg=COLORS['accent'], cursor='hand2')
    lbl.pack(side=tk.LEFT)

    if is_cur:
        tk.Label(row, text='√', font=('Microsoft YaHei', 7),
                 bg=bg, fg=COLORS['accent'],
                 padx=0, pady=0).pack(side=tk.LEFT, padx=(8, 0))

    if total > 1:
        gb = tk.Label(row, text='全局', font=('Microsoft YaHei', 8),
                      bg=COLORS['tag_bg'], fg=COLORS['tag_fg'],
                      padx=6, pady=1, cursor='hand2')
        gb.pack(side=tk.RIGHT)
        gb.bind('<Button-1>', lambda e, p=phon: on_apply(li, ci, p, True))
        bind_color_hover(gb, {'bg': (COLORS['tag_bg'], COLORS['accent']),
                              'fg': (COLORS['tag_fg'], '#FFFFFF')})

    if note_txt:
        nl = _create_note_widget(card, note_txt, bg)
        nl.pack(fill=tk.X, pady=(6, 0))
        nl.bind('<Button-1>', lambda e, p=phon: on_apply(li, ci, p, False))

    click = lambda e, p=phon: on_apply(li, ci, p, False)
    card.bind('<Button-1>', click)
    lbl.bind('<Button-1>', click)

    if not is_cur:
        bind_hover(card, bg)
