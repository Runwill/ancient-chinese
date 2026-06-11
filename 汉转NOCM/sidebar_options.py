"""侧边栏：多音字读音选择面板。"""

import re
import tkinter as tk

from constants import COLORS
from widgets import (ScrollableFrame, ModernButton, bind_hover, bind_color_hover,
                     bind_mousewheel, freeze_redraw, thaw_redraw)


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
    tk.Label(center, text='点击文字\n查看读音',
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


def build_char_info(sidebar, char, mapping):
    """构建普通字（非多音字）的信息面板。"""
    freeze_redraw(sidebar)
    try:
        for w in sidebar.winfo_children():
            w.destroy()

        opts = mapping.get(char)

        # 头部
        hdr = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16, pady=14)
        hdr.pack(fill=tk.X)
        row = tk.Frame(hdr, bg=COLORS['bg_sidebar'])
        row.pack(fill=tk.X)
        tk.Label(row, text=char, font=('Microsoft YaHei', 24, 'bold'),
                 bg=COLORS['bg_sidebar'], fg=COLORS['text_primary']).pack(side=tk.LEFT)
        detail_col = tk.Frame(row, bg=COLORS['bg_sidebar'])
        detail_col.pack(side=tk.LEFT, padx=(12, 0), fill=tk.Y)

        if not opts:
            tk.Label(detail_col, text='未收录',
                     font=('Microsoft YaHei', 10),
                     bg=COLORS['bg_sidebar'], fg=COLORS['text_muted']
                     ).pack(anchor='w', pady=(4, 0))
        else:
            first = opts[0]
            phon = first['phonetic'] if isinstance(first, dict) else str(first)
            tk.Label(detail_col, text=phon,
                     font=('Consolas', 13, 'bold'),
                     bg=COLORS['bg_sidebar'], fg=COLORS['accent']
                     ).pack(anchor='w', pady=(2, 0))

        tk.Frame(sidebar, bg=COLORS['divider'], height=1).pack(fill=tk.X, padx=16)

        if opts:
            sf = ScrollableFrame(sidebar, bg=COLORS['bg_sidebar'])
            sf.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            for o in opts:
                _build_info_card(sf.inner, o)
            bind_mousewheel(sf.inner, sf.on_mousewheel)
            sf.canvas.bind('<MouseWheel>', sf.on_mousewheel)
        else:
            box = tk.Frame(sidebar, bg=COLORS['bg_sidebar'])
            box.pack(fill=tk.BOTH, expand=True)
            tk.Label(box, text='该字符不在数据库中',
                     font=('Microsoft YaHei', 9),
                     bg=COLORS['bg_sidebar'], fg=COLORS['text_muted']
                     ).pack(pady=20)
    finally:
        thaw_redraw(sidebar)


def _build_info_card(parent, opt):
    """构建普通字的只读信息卡片（不可选择读音）。"""
    phon = opt.get('phonetic') if isinstance(opt, dict) else str(opt)
    note_raw = opt.get('note') if isinstance(opt, dict) else None
    note_txt = _format_note(str(note_raw).strip()) if note_raw else ''
    bg = COLORS['bg_card']

    card = tk.Frame(parent, bg=bg, highlightbackground=COLORS['border_light'],
                    highlightthickness=1, padx=12, pady=10)
    card.pack(fill=tk.X, pady=3, padx=6)

    tk.Label(card, text=phon, font=('Consolas', 13, 'bold'),
             bg=bg, fg=COLORS['accent']).pack(anchor='w')

    if note_txt:
        nl = _create_note_widget(card, note_txt, bg)
        nl.pack(fill=tk.X, pady=(6, 0))


# ── 选区信息面板 ───────────────────────────────────


def build_selection_info(sidebar, char_count, line_count, copy_mode,
                         on_copy, on_set_mode, on_delete):
    """构建选区面板：显示选区统计、复制模式切换、复制/删除按钮、快捷键提示。

    参数:
      char_count, line_count: 选区统计
      copy_mode: 'raw' 或 'phon' 当前 Ctrl+C 默认复制模式
      on_copy(mode): 立即复制（mode='raw'/'phon'）
      on_set_mode(mode): 设置默认复制模式
      on_delete(): 删除选区
    返回 dict: {'count_lbl': Label, 'mode_chips': {mode: Label}, 'set_active': fn}
    """
    freeze_redraw(sidebar)
    refs = {}
    try:
        for w in sidebar.winfo_children():
            w.destroy()

        # 头部
        hdr = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text='已选择文本',
                 font=('Microsoft YaHei', 11, 'bold'),
                 bg=COLORS['bg_sidebar'], fg=COLORS['text_primary']
                 ).pack(anchor='w')
        count_lbl = tk.Label(hdr, text=_fmt_sel_count(char_count, line_count),
                             font=('Microsoft YaHei', 9),
                             bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'])
        count_lbl.pack(anchor='w', pady=(4, 0))
        refs['count_lbl'] = count_lbl

        tk.Frame(sidebar, bg=COLORS['divider'], height=1).pack(
            fill=tk.X, padx=16)

        body = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16, pady=14)
        body.pack(fill=tk.X)
        tk.Label(body, text='Ctrl+C 默认复制',
                 font=('Microsoft YaHei', 9),
                 bg=COLORS['bg_sidebar'], fg=COLORS['text_secondary']
                 ).pack(anchor='w')

        seg = tk.Frame(body, bg=COLORS['bg_sidebar'],
                       highlightbackground=COLORS['border'],
                       highlightthickness=1)
        seg.pack(anchor='w', pady=(6, 0))

        mode_chips = {}

        def _set_active(mode):
            for v, c in mode_chips.items():
                if v == mode:
                    c.configure(bg=COLORS['accent_light'],
                                fg=COLORS['accent'])
                else:
                    c.configure(bg=COLORS['bg_sidebar'],
                                fg=COLORS['text_secondary'])

        for label, val in [('原文', 'raw'), ('音标', 'phon')]:
            chip = tk.Label(seg, text=label, font=('Microsoft YaHei', 9),
                            bg=COLORS['bg_sidebar'],
                            fg=COLORS['text_secondary'],
                            padx=14, pady=4, cursor='hand2')
            chip.pack(side=tk.LEFT)
            chip.bind('<Button-1>',
                      lambda e, v=val: (on_set_mode(v), _set_active(v)))
            mode_chips[val] = chip
        _set_active(copy_mode)
        refs['mode_chips'] = mode_chips
        refs['set_active'] = _set_active

        btn_row = tk.Frame(body, bg=COLORS['bg_sidebar'])
        btn_row.pack(anchor='w', pady=(14, 0))
        ModernButton(btn_row, '复制原文', command=lambda: on_copy('raw'),
                     primary=False, width=80, height=28
                     ).pack(side=tk.LEFT, padx=(0, 6))
        ModernButton(btn_row, '复制音标', command=lambda: on_copy('phon'),
                     primary=False, width=80, height=28
                     ).pack(side=tk.LEFT, padx=(0, 6))
        ModernButton(btn_row, '删除', command=on_delete,
                     primary=False, width=56, height=28
                     ).pack(side=tk.LEFT)

        tk.Frame(sidebar, bg=COLORS['divider'], height=1).pack(
            fill=tk.X, padx=16, pady=(4, 0))

        tips = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16, pady=12)
        tips.pack(fill=tk.BOTH, expand=True)
        tk.Label(tips, text='快捷键',
                 font=('Microsoft YaHei', 9, 'bold'),
                 bg=COLORS['bg_sidebar'], fg=COLORS['text_secondary']
                 ).pack(anchor='w', pady=(0, 6))
        for k, desc in [
            ('Ctrl+C', '复制（按上方模式）'),
            ('Ctrl+A', '全选'),
            ('Shift+方向', '扩展选区'),
            ('Shift+点击', '扩展到位置'),
            ('Backspace', '删除选区'),
            ('点击 / Esc', '取消选区'),
        ]:
            row = tk.Frame(tips, bg=COLORS['bg_sidebar'])
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=k, font=('Consolas', 9),
                     bg=COLORS['bg_sidebar'], fg=COLORS['accent'],
                     width=12, anchor='w').pack(side=tk.LEFT)
            tk.Label(row, text=desc, font=('Microsoft YaHei', 9),
                     bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
                     anchor='w').pack(side=tk.LEFT)
    finally:
        thaw_redraw(sidebar)
    return refs


def _fmt_sel_count(char_count, line_count):
    if line_count <= 1:
        return f'{char_count} 个字符'
    return f'{char_count} 个字符 · {line_count} 行'


def update_selection_count(refs, char_count, line_count):
    """更新已构建的选区面板的计数标签。"""
    lbl = refs.get('count_lbl') if refs else None
    if lbl is None:
        return
    try:
        lbl.configure(text=_fmt_sel_count(char_count, line_count))
    except tk.TclError:
        pass
