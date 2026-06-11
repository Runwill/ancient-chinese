"""GUI 模块：汉字转 NOCM 音标的可视化编辑器（现代化 UI）。"""

import os
import sys
import tkinter as tk
import tkinter.font as tkFont
from tkinter import messagebox
from typing import Optional

from constants import COLORS, _CANVAS_MARGIN, find_bracket_ranges, in_bracket, set_theme, get_theme
from widgets import ModernButton, freeze_redraw, thaw_redraw, style, apply_theme_transition
from editor_buffer import EditorBuffer
from editor_render import EditorRenderer
from draft_io import save_draft, load_draft, delete_draft, rename_draft, get_draft_name
from data_loader import get_changed_chars, clear_changed_char
from nocm_transcriber import DEFAULT_SCHEME_ID, NocmTranscriber, list_schemes, load_scheme
import sidebar_drafts
import sidebar_options


class App(tk.Tk):
    def __init__(self, mapping):
        super().__init__()
        self.mapping = mapping
        self.title('汉字转 NOCM 音标')
        self.geometry('1280x760')
        self.minsize(960, 600)
        self.configure(bg=COLORS['bg_main'])

        self.buf = EditorBuffer(mapping)
        self.buf.set_dirty_callback(self._update_title)

        # 当前选中的多音字信息（用于右侧边栏）
        self._selected_poly = None  # (line_idx, col_idx)
        # 当前文稿文件名（None表示新文稿）
        self._current_draft: Optional[str] = None
        # 手动高亮模式开关
        self._highlight_mode = False
        # 搜索状态
        self._search_visible = False
        self._search_matches = []  # [(li, ci), ...]
        self._search_idx = 0
        # 导出选项
        self._export_punct_to_newline = False
        self._export_mode = 'phon'  # 'phon' 音标 / 'raw' 原文
        self._export_scheme_id = DEFAULT_SCHEME_ID
        # 选区相关：复制模式 + 侧边栏面板状态
        self._sel_copy_mode = 'raw'  # 'raw' | 'phon'
        self._sel_panel_active = False  # 当前侧边栏是否为选区面板
        self._sel_refs = None        # 选区面板的控件引用（更新计数用）

        self._build_ui()

    # ── 构建界面 ──────────────────────────────────

    def _build_ui(self):
        style(self, bg='bg_main')

        # 主容器 — 无额外 padding，贴边布局
        main = tk.Frame(self, bg=COLORS['bg_main'])
        main.pack(fill=tk.BOTH, expand=True)
        style(main, bg='bg_main')

        # ── 顶部工具栏（紧凑型） ──
        toolbar = tk.Frame(main, bg=COLORS['bg_card'], height=52)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)
        style(toolbar, bg='bg_card')

        toolbar_inner = tk.Frame(toolbar, bg=COLORS['bg_card'])
        toolbar_inner.pack(fill=tk.BOTH, expand=True, padx=20)
        style(toolbar_inner, bg='bg_card')

        # 左侧标题 + 副标题
        title_area = tk.Frame(toolbar_inner, bg=COLORS['bg_card'])
        title_area.pack(side=tk.LEFT, fill=tk.Y)
        style(title_area, bg='bg_card')

        title_row = tk.Frame(title_area, bg=COLORS['bg_card'])
        title_row.pack(expand=True)
        style(title_row, bg='bg_card')

        title_lbl = tk.Label(title_row, text='汉字转 NOCM 音标',
                font=('Microsoft YaHei', 13, 'bold'),
                bg=COLORS['bg_card'], fg=COLORS['text_primary'])
        title_lbl.pack(side=tk.LEFT)
        style(title_lbl, bg='bg_card', fg='text_primary')

        self._subtitle_lbl = tk.Label(title_row, text='  输入即注音 · 点击彩色字修改读音',
                font=('Microsoft YaHei', 9),
                bg=COLORS['bg_card'], fg=COLORS['text_muted'])
        self._subtitle_lbl.pack(side=tk.LEFT, pady=(3, 0))
        style(self._subtitle_lbl, bg='bg_card')

        # 右侧按钮组
        btn_area = tk.Frame(toolbar_inner, bg=COLORS['bg_card'])
        btn_area.pack(side=tk.RIGHT, fill=tk.Y)
        style(btn_area, bg='bg_card')

        btn_row = tk.Frame(btn_area, bg=COLORS['bg_card'])
        btn_row.pack(expand=True)
        style(btn_row, bg='bg_card')

        self._mod_buttons = []
        self._theme_btn = None
        self._highlight_btn = None
        theme_label = '☀' if get_theme() == 'dark' else '☾'
        for text, cmd, pri in [('?', self._on_help, False),
                               ('重启', self._on_restart, False),
                               (theme_label, self._on_toggle_theme, False),
                               ('高亮', self._on_toggle_highlight, False),
                               ('保存', self._on_save, False),
                               ('导出', self._on_export, True)]:
            w = 32 if len(text) <= 1 else 56 if len(text) <= 2 else 72
            btn = ModernButton(btn_row, text, command=cmd,
                        primary=pri, width=w, height=30)
            btn.pack(side=tk.LEFT, padx=(0, 6))
            style(btn, bg='bg_card')
            self._mod_buttons.append(btn)
            if cmd == self._on_toggle_theme:
                self._theme_btn = btn
            elif cmd == self._on_toggle_highlight:
                self._highlight_btn = btn

        # 工具栏底部分隔线
        div = tk.Frame(main, bg=COLORS['divider'], height=1)
        div.pack(fill=tk.X)
        style(div, bg='divider')

        # ── 主内容区（三栏布局） ──
        content = tk.Frame(main, bg=COLORS['bg_main'])
        content.pack(fill=tk.BOTH, expand=True)
        style(content, bg='bg_main')

        # ── 左侧边栏（文稿管理面板） ──
        self.left_sidebar = tk.Frame(content, bg=COLORS['bg_sidebar'], width=240)
        self.left_sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.left_sidebar.pack_propagate(False)
        style(self.left_sidebar, bg='bg_sidebar')

        # 右边分割线
        div2 = tk.Frame(content, bg=COLORS['divider'], width=1)
        div2.pack(side=tk.LEFT, fill=tk.Y)
        style(div2, bg='divider')

        # 编辑区（无边框，直接铺满中间）
        edit_area = tk.Frame(content, bg=COLORS['bg_canvas'])
        edit_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        style(edit_area, bg='bg_canvas')

        # 搜索栏（默认隐藏）
        self._build_search_bar(edit_area)

        self.canvas = tk.Canvas(edit_area, bg=COLORS['bg_canvas'],
                                highlightthickness=0,
                                yscrollincrement=20)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        style(self.canvas, bg='bg_canvas')

        # 右侧分割线
        div3 = tk.Frame(content, bg=COLORS['divider'], width=1)
        div3.pack(side=tk.LEFT, fill=tk.Y)
        style(div3, bg='divider')

        # ── 右侧边栏（音标选择面板） ──
        self.sidebar = tk.Frame(content, bg=COLORS['bg_sidebar'], width=260)
        self.sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        style(self.sidebar, bg='bg_sidebar')
        
        sidebar_options.build_placeholder(self.sidebar)

        # 初始构建文稿列表
        self._build_sidebar_drafts()

        # 字体与渲染器
        self._char_font = tkFont.Font(family='Microsoft YaHei', size=14)
        self._phon_font = tkFont.Font(family='Consolas', size=10)
        self.renderer = EditorRenderer(self.canvas, self._char_font, self._phon_font)

        self.canvas.bind('<Key>', self._on_key)
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        self.canvas.bind('<Shift-Button-1>', self._on_canvas_shift_click)
        self.canvas.bind('<B1-Motion>', self._on_canvas_drag)
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Configure>', self._on_configure)
        self.canvas.focus_set()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
    
    # ── 便捷委托 ──────────────────────────────────

    def _rebuild_display(self):
        self.renderer.rebuild(self.buf.buffer, self.buf.cell_info)
        self.renderer.update_cursor(self.buf.cur_line, self.buf.cur_col)
        self.renderer.set_selection(self.buf.selection_range())
        # 撤回/重做后复位多音字选中
        if self._selected_poly:
            sli, sci = self._selected_poly
            if (sli >= len(self.buf.buffer)
                    or sci >= len(self.buf.buffer[sli])
                    or sci >= len(self.buf.cell_info[sli])
                    or not self.buf.cell_info[sli][sci].get('is_poly')):
                self._selected_poly = None
                sidebar_options.build_placeholder(self.sidebar)

    def _update_cursor(self):
        self.renderer.update_cursor(self.buf.cur_line, self.buf.cur_col)
        self.renderer.set_selection(self.buf.selection_range())
        self._sync_selection_sidebar()

    def _sync_selection_sidebar(self):
        """选区出现/消失时切换侧边栏；选区扩展时刷新计数。"""
        rng = self.buf.selection_range()
        # 通过 count_lbl 是否存活判定面板是否还在屏上
        # （build_options/build_char_info 会销毁 sidebar 子控件）
        panel_alive = False
        if self._sel_panel_active and self._sel_refs:
            lbl = self._sel_refs.get('count_lbl')
            try:
                panel_alive = bool(lbl and lbl.winfo_exists())
            except tk.TclError:
                panel_alive = False
            if not panel_alive:
                self._sel_panel_active = False
                self._sel_refs = None
        if rng is None:
            if panel_alive:
                # 选区被清除 → 恢复占位（仅当无其它面板内容）
                self._sel_panel_active = False
                self._sel_refs = None
                if self._selected_poly is None:
                    sidebar_options.build_placeholder(self.sidebar)
            return
        cc, lc = self._selection_metrics(rng)
        if not panel_alive:
            self._sel_panel_active = True
            self._selected_poly = None
            self._sel_refs = sidebar_options.build_selection_info(
                self.sidebar, cc, lc, self._sel_copy_mode,
                on_copy=self._copy_selection_as,
                on_set_mode=self._set_sel_copy_mode,
                on_delete=self._delete_selection_action)
        else:
            sidebar_options.update_selection_count(self._sel_refs, cc, lc)

    def _selection_metrics(self, rng):
        (sli, sci), (eli, eci) = rng
        if sli == eli:
            return eci - sci, 1
        cc = len(self.buf.buffer[sli]) - sci
        for li in range(sli + 1, eli):
            cc += len(self.buf.buffer[li])
        cc += eci
        return cc, eli - sli + 1

    def _selection_phonetic(self):
        """构造选区的音标文本（与 _get_result 一致格式）。"""
        rng = self.buf.selection_range()
        if rng is None:
            return ''
        (sli, sci), (eli, eci) = rng
        out_lines = []
        for li in range(sli, eli + 1):
            line_chars = self.buf.buffer[li]
            line_info = self.buf.cell_info[li]
            lo = sci if li == sli else 0
            hi = eci if li == eli else len(line_chars)
            br = find_bracket_ranges(line_chars)
            parts = []
            bracket_buf = []
            for ci in range(lo, hi):
                if in_bracket(ci, br):
                    bracket_buf.append(line_chars[ci])
                else:
                    if bracket_buf:
                        parts.append(''.join(bracket_buf))
                        bracket_buf = []
                    parts.append(line_info[ci]['phonetic'])
            if bracket_buf:
                parts.append(''.join(bracket_buf))
            out_lines.append(' '.join(parts))
        return '\n'.join(out_lines).strip()

    def _set_sel_copy_mode(self, mode):
        if mode in ('raw', 'phon'):
            self._sel_copy_mode = mode

    def _copy_selection_as(self, mode):
        text = (self._selection_phonetic() if mode == 'phon'
                else self.buf.selection_text())
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _delete_selection_action(self):
        if self._delete_selection_if_any():
            self._update_cursor()

    # ── 选区辅助 ──────────────────────────────────

    def _caret_at(self, cx, cy):
        """canvas 坐标 → caret 位置 (li, ci)。ci 是字符之间的位置（0..len）。

        正确处理自动换行（每个逻辑行可能有多个视觉行 y）以及空行。
        cy 落在任意 cell 的 y1..y2 范围 → 命中该视觉行；否则按 y 距离吸附到最近视觉行。
        """
        cell_h = self.renderer.cell_h
        cell_rects = self.renderer.cell_rects

        # 1. 收集所有视觉行：[(y1, y2, li, [(ci, x1, x2)])]
        rows = []
        for li, lr in enumerate(cell_rects):
            if not lr:
                # 空逻辑行：取该行的 line_y，造一个虚拟视觉行（只允许 caret 0）
                ly = (self.renderer.line_y[li]
                      if li < len(self.renderer.line_y) else _CANVAS_MARGIN)
                rows.append((ly, ly + cell_h, li, []))
                continue
            # 按 y1 分组（同一 y1 = 同一视觉行）
            cur_y = lr[0][1]
            cur_cells = []
            for ci, (x1, y1, x2, y2) in enumerate(lr):
                if y1 != cur_y and cur_cells:
                    rows.append((cur_y, cur_y + cell_h, li, cur_cells))
                    cur_cells = []
                cur_y = y1
                cur_cells.append((ci, x1, x2))
            if cur_cells:
                rows.append((cur_y, cur_y + cell_h, li, cur_cells))

        if not rows:
            return 0, 0

        # 2. 选定目标视觉行：优先 cy 落入 y1..y2，否则取 y 距离最小者
        target = None
        for r in rows:
            if r[0] <= cy <= r[1]:
                target = r
                break
        if target is None:
            target = min(rows, key=lambda r: abs((r[0] + r[1]) / 2 - cy))

        y1, y2, li, cells = target
        if not cells:
            return li, 0
        # 3. 在该视觉行上取 caret：以 cell 中线为分界
        # 第一个 cell 的左侧
        if cx < cells[0][1]:
            return li, cells[0][0]
        for ci, x1, x2 in cells:
            if cx < (x1 + x2) / 2:
                return li, ci
        # 落到最后一个 cell 的右侧 → caret 在该 cell 之后
        last_ci = cells[-1][0]
        return li, last_ci + 1

    def _set_caret(self, li, ci, extend=False):
        """移动光标；extend=True 保留/建立选区锚点。"""
        if extend:
            if self.buf.sel_anchor is None:
                self.buf.sel_anchor = (self.buf.cur_line, self.buf.cur_col)
        else:
            self.buf.sel_anchor = None
        self.buf.cur_line = li
        self.buf.cur_col = ci
        self._update_cursor()

    def _delete_selection_if_any(self):
        """若有选区则删除并重绘，返回是否删除了。"""
        if self.buf.delete_selection():
            self._rebuild_display()
            return True
        return False

    # ── 键盘处理 ──────────────────────────────────

    def _on_key(self, event):
        ctrl = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        ks = event.keysym
        # 方向键 / Home / End：无论 ctrl 是否按下，都按选区逻辑处理（Shift = 扩展选区）
        # 这样 Ctrl+Shift+方向 仍可触发多选（Ctrl 暂不支持词级跳转，行为与不带 Ctrl 一致）
        if ks in ('Left', 'Right', 'Home', 'End', 'Up', 'Down'):
            if shift and self.buf.sel_anchor is None:
                self.buf.sel_anchor = (self.buf.cur_line, self.buf.cur_col)
            elif not shift:
                self.buf.sel_anchor = None
            if ks in ('Up', 'Down'):
                nl, nc = self.renderer.visual_nav(
                    self.buf.cur_line, self.buf.cur_col, ks)
                self.buf.cur_line = nl
                self.buf.cur_col = nc
            else:
                self.buf.handle_nav(ks)
            self._update_cursor()
            return 'break'

        # Esc：优先清除选区
        if ks == 'Escape' and self.buf.has_selection():
            self.buf.sel_anchor = None
            self._update_cursor()
            return 'break'

        if ctrl:
            _acts = {'v': self._on_paste, 'c': self._copy_raw,
                     'y': lambda: (self.buf.redo() and self._rebuild_display()),
                     's': self._on_save,
                     'f': self._on_toggle_search,
                     'a': self._select_all}
            k = ks.lower()
            if k == 'z':
                fn = self.buf.redo if shift else self.buf.undo
                if fn():
                    self._rebuild_display()
            elif k in _acts:
                _acts[k]()
        else:
            if ks == 'BackSpace':
                if self._delete_selection_if_any():
                    pass
                elif self.buf.backspace():
                    self._rebuild_display()
            elif ks == 'Delete':
                if self._delete_selection_if_any():
                    pass
                elif self.buf.delete_char():
                    self._rebuild_display()
            elif ks == 'Return':
                self._delete_selection_if_any()
                self.buf.insert_newline()
                self._rebuild_display()
            elif event.char and len(event.char) == 1 and event.char.isprintable():
                self._delete_selection_if_any()
                self.buf.insert_char(event.char)
                self._rebuild_display()
        return 'break'

    def _on_paste(self, event=None):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return 'break'
        if text:
            # 粘贴覆盖选区：先 delete_selection（其内部 save_undo），无选区则手动 save_undo
            if not self.buf.delete_selection():
                self.buf.save_undo()
            self.buf.insert_chars_raw(text)
            self._rebuild_display()
        return 'break'

    def _select_all(self):
        if not self.buf.buffer:
            return
        last_li = len(self.buf.buffer) - 1
        last_ci = len(self.buf.buffer[last_li])
        if last_li == 0 and last_ci == 0:
            return
        self.buf.sel_anchor = (0, 0)
        self.buf.cur_line = last_li
        self.buf.cur_col = last_ci
        self._update_cursor()

    def _on_canvas_shift_click(self, event):
        self.canvas.focus_set()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        li, ci = self._caret_at(cx, cy)
        if self.buf.sel_anchor is None:
            self.buf.sel_anchor = (self.buf.cur_line, self.buf.cur_col)
        self.buf.cur_line = li
        self.buf.cur_col = ci
        self._update_cursor()
        return 'break'

    def _on_canvas_drag(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        li, ci = self._caret_at(cx, cy)
        # 锚点尚未建立 → 用上次点击位置为锚
        if self.buf.sel_anchor is None:
            self.buf.sel_anchor = (self.buf.cur_line, self.buf.cur_col)
        if (li, ci) != (self.buf.cur_line, self.buf.cur_col):
            self.buf.cur_line = li
            self.buf.cur_col = ci
            self._update_cursor()
        return 'break'

    def _on_canvas_click(self, event):
        self.canvas.focus_set()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        # 任意点击都先清除选区
        had_selection = self.buf.has_selection()
        self.buf.sel_anchor = None
        for li, line_rects in enumerate(self.renderer.cell_rects):
            for ci, (x1, y1, x2, y2) in enumerate(line_rects):
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    info = self.buf.cell_info[li][ci]
                    ch = self.buf.buffer[li][ci]
                    br = find_bracket_ranges(self.buf.buffer[li])
                    in_brk = in_bracket(ci, br)
                    # 高亮模式：点击非括号字 -> 切换 manual_hl
                    if self._highlight_mode and not in_brk:
                        self.buf.save_undo()
                        info['manual_hl'] = not info.get('manual_hl', False)
                        self.buf.cur_line = li
                        self.buf.cur_col = min(ci + 1, len(self.buf.buffer[li]))
                        self._rebuild_display()
                        return
                    if not in_brk:
                        if info['is_poly'] and info['options']:
                            self._on_cell_click(li, ci)
                            # 设为该 cell 的左 caret，便于继续拖选
                            self.buf.cur_line = li
                            self.buf.cur_col = ci
                            self._update_cursor()
                            return
                        # 普通字：显示字符信息
                        # caret 取点击位置（左/右半决定）
                        ci_caret = ci if cx < (x1 + x2) / 2 else ci + 1
                        self.buf.cur_line = li
                        self.buf.cur_col = ci_caret
                        self._selected_poly = None
                        sidebar_options.build_char_info(
                            self.sidebar, ch, self.mapping)
                        self._update_cursor()
                        return
                    ci_caret = ci if cx < (x1 + x2) / 2 else ci + 1
                    self.buf.cur_line = li
                    self.buf.cur_col = ci_caret
                    self._update_cursor()
                    return
        li, ci = self._caret_at(cx, cy)
        self.buf.cur_line = li
        self.buf.cur_col = ci
        self._update_cursor()
        if had_selection:
            self._update_cursor()

    def _on_mousewheel(self, event):
        if event.delta > 0 and self.canvas.yview()[0] <= 0:
            return
        self.canvas.yview_scroll(-event.delta // 40, 'units')
        self.renderer.render_on_scroll()

    def _on_configure(self, event):
        self.renderer.on_configure(event, self.buf.buffer, self.buf.cell_info,
                                   self.buf.cur_line, self.buf.cur_col)

    def _copy_raw(self):
        # 有选区时按选区复制模式复制；否则复制全文
        if self.buf.has_selection():
            self._copy_selection_as(self._sel_copy_mode)
            return
        text = self.buf.copy_raw()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    # ── 点击多音字显示侧边栏选项 ────────────────────────

    def _on_cell_click(self, li, ci):
        """点击多音字时，在侧边栏显示选项"""
        info = self.buf.cell_info[li][ci]
        ch = self.buf.buffer[li][ci]
        opts = info['options']

        # 非多音字但被标记 stale：点击即确认，更新读音并清除标记
        if not opts and info.get('stale'):
            new_opts = self.mapping.get(ch)
            if new_opts:
                first = new_opts[0]
                info['phonetic'] = first['phonetic'] if isinstance(first, dict) else str(first)
            info.pop('stale', None)
            clear_changed_char(ch)
            self._rebuild_display()
            self._build_sidebar_drafts()
            return

        if not opts:
            return

        self.buf.cur_line = li
        self.buf.cur_col = ci + 1
        self._selected_poly = (li, ci)
        sidebar_options.build_options(
            self.sidebar, li, ci, ch, info,
            self.buf.buffer, on_apply=self._apply_reading)
        self._update_cursor()

    def _apply_reading(self, li, ci, phonetic, global_apply):
        """应用选中的读音"""
        self.after(20, lambda: self._do_apply(li, ci, phonetic, global_apply))

    def _do_apply(self, li, ci, phonetic, global_apply):
        ch = self.buf.buffer[li][ci]

        # 全局应用时，逐个询问已手动选择不同读音的位置
        skip_positions = set()  # 用户选择跳过的 (li, ci)
        if global_apply:
            for _li, (lc, linfo) in enumerate(zip(self.buf.buffer, self.buf.cell_info)):
                for _ci, (c, info) in enumerate(zip(lc, linfo)):
                    if c == ch and info['is_poly'] and (_li != li or _ci != ci):
                        if info.get('selected') == 'manual' and info['phonetic'] != phonetic:
                            sentence = ''.join(self.buf.buffer[_li])
                            # 标记目标字位置
                            before = sentence[:_ci]
                            after = sentence[_ci + 1:]
                            ctx = f'{before}【{ch}】{after}'
                            if len(ctx) > 40:
                                start = max(0, _ci - 15)
                                end = min(len(sentence), _ci + 16)
                                seg_b = sentence[start:_ci]
                                seg_a = sentence[_ci + 1:end]
                                ctx = f'…{seg_b}【{ch}】{seg_a}…'
                            ans = messagebox.askyesnocancel(
                                '确认替换',
                                f'第 {_li + 1} 行：{ctx}\n\n'
                                f'该处「{ch}」已手动选为 {info["phonetic"]}，'
                                f'要替换为 {phonetic} 吗？\n\n'
                                f'是 = 替换此处　　否 = 跳过此处　　取消 = 中止全局应用')
                            if ans is None:  # 取消
                                return
                            if not ans:  # 否 → 跳过
                                skip_positions.add((_li, _ci))

        self.buf.save_undo()
        # 清除该字的 stale 标记
        had_stale = False
        if global_apply:
            # 将上次的紫色（global_recent）降级为蓝色（global）
            for linfo in self.buf.cell_info:
                for info in linfo:
                    if info.get('selected') == 'global_recent':
                        info['selected'] = 'global'
            for _li, (lc, linfo) in enumerate(zip(self.buf.buffer, self.buf.cell_info)):
                for _ci, (c, info) in enumerate(zip(lc, linfo)):
                    if c == ch and info['is_poly']:
                        if (_li, _ci) in skip_positions:
                            continue
                        if _li == li and _ci == ci:
                            info['phonetic'] = phonetic
                            info['selected'] = 'manual'
                        elif info['phonetic'] == phonetic and info.get('selected') == 'manual':
                            pass  # 读音已相同且为手动选择，保留不变
                        else:
                            info['phonetic'] = phonetic
                            info['selected'] = 'global_recent'
                    if c == ch and info.get('stale'):
                        info.pop('stale', None)
                        had_stale = True
        else:
            self.buf.cell_info[li][ci]['phonetic'] = phonetic
            self.buf.cell_info[li][ci]['selected'] = 'manual'
            if self.buf.cell_info[li][ci].get('stale'):
                self.buf.cell_info[li][ci].pop('stale', None)
                had_stale = True
        if had_stale:
            clear_changed_char(ch)
            self._build_sidebar_drafts()
        self._rebuild_display()
        if self._selected_poly:
            sli, sci = self._selected_poly
            sidebar_options.build_options(
                self.sidebar, sli, sci,
                self.buf.buffer[sli][sci], self.buf.cell_info[sli][sci],
                self.buf.buffer, on_apply=self._apply_reading)

    # ── 辅助 ─────────────────────────────────────

    def _get_result(self):
        lines = []
        for line_chars, line_info in zip(self.buf.buffer, self.buf.cell_info):
            br = find_bracket_ranges(line_chars)
            parts = []
            bracket_buf = []
            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                if in_bracket(ci, br):
                    bracket_buf.append(ch)
                else:
                    if bracket_buf:
                        parts.append(''.join(bracket_buf))
                        bracket_buf = []
                    parts.append(info['phonetic'])
            if bracket_buf:
                parts.append(''.join(bracket_buf))
            lines.append(' '.join(parts))
        return '\n'.join(lines).strip()

    def _get_suno_result(self, scheme_id=None):
        scheme_id = scheme_id or self._export_scheme_id
        transcriber = NocmTranscriber(load_scheme(scheme_id))
        return transcriber.convert_text(self._get_result())

    def _reset_editor(self):
        """重置编辑器到空白状态。"""
        self.buf.reset()
        self._selected_poly = None
        self._current_draft = None
        self.buf.dirty = False

    def _on_clear(self):
        if not self._check_unsaved():
            return
        if any(self.buf.buffer[0]) or len(self.buf.buffer) > 1:
            self.buf.save_undo()
        self._reset_editor()
        sidebar_options.build_placeholder(self.sidebar)
        self._rebuild_display()

    def _on_copy(self):
        text = self._get_result()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo('提示', '结果已复制到剪贴板。')
        else:
            messagebox.showinfo('提示', '没有可复制的内容。')

    # ── 标点 → 换行 转换 ──────────────────────────

    # 中英文常见标点（不含小数点 . 以免误伤数字/英文缩写；不含括号 [] 因括号内容原样保留）
    _PUNCT_TO_NEWLINE = '，。！？；：、,!?;:…—○'
    # 句号转换为两个换行（段落分隔）
    _PUNCT_DOUBLE_NEWLINE = '。'

    def _convert_punct_to_newline(self, text):
        """每个标点替换成换行；句号 `。` 替换为两个换行（产生空行作段落分隔）。"""
        if not text:
            return text
        out = []
        for ch in text:
            if ch in self._PUNCT_DOUBLE_NEWLINE:
                out.append('\n\n')
            elif ch in self._PUNCT_TO_NEWLINE:
                out.append('\n')
            else:
                out.append(ch)
        # 去除每行首尾空白，但保留空行（让多个换行得以保留）
        lines = [l.strip() for l in ''.join(out).split('\n')]
        return '\n'.join(lines)

    def _build_both_text(self, punct_split):
        """构造「原文 + 音标」交替文本：每行原文下面紧跟一行音标。

        启用 punct_split 时，按标点切分每个 buffer 行，使原文/音标按短句对齐；
        遇到 `。` 时额外插入一个空行。
        """
        out_lines = []  # 最终行序列
        pending_blank = False

        def emit(raw, phon, double=False):
            nonlocal pending_blank
            r = raw.strip()
            p = phon.strip()
            if not r and not p:
                return
            if pending_blank and out_lines:
                out_lines.append('')
                pending_blank = False
            out_lines.append(r)
            out_lines.append(p)
            if double:
                pending_blank = True

        for line_chars, line_info in zip(self.buf.buffer, self.buf.cell_info):
            br = find_bracket_ranges(line_chars)
            raw_buf = []
            phon_parts = []

            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                if in_bracket(ci, br):
                    # 括号内容仅保留在原文侧；音标侧跳过以免与原文行重复
                    raw_buf.append(ch)
                    continue
                if punct_split and ch in self._PUNCT_TO_NEWLINE:
                    emit(''.join(raw_buf), ' '.join(phon_parts),
                         double=(ch in self._PUNCT_DOUBLE_NEWLINE))
                    raw_buf = []
                    phon_parts = []
                else:
                    raw_buf.append(ch)
                    phon_parts.append(info['phonetic'])
            emit(''.join(raw_buf), ' '.join(phon_parts))
            # 缓冲区原始换行视为段落边界（添加空行分隔），但避免开头空行
            if out_lines and not pending_blank:
                pending_blank = True

        return '\n'.join(out_lines).rstrip()

    # ── 导出对话框：可选中复制 + 标点转换行 ──────────

    def _on_export(self):
        phon_text = self._get_result()
        raw_text = self.buf.copy_raw().strip()
        if not phon_text and not raw_text:
            messagebox.showinfo('提示', '没有可导出的内容。')
            return
        schemes = list_schemes()
        if not schemes:
            schemes = [{'id': DEFAULT_SCHEME_ID, 'name': '当前 Suno 方案'}]
        scheme_names = {s['name']: s['id'] for s in schemes}
        scheme_labels = list(scheme_names.keys())
        current_scheme_label = next(
            (s['name'] for s in schemes if s['id'] == self._export_scheme_id),
            scheme_labels[0])

        dlg = tk.Toplevel(self)
        dlg.title('导出')
        dlg.configure(bg=COLORS['bg_card'])
        dlg.transient(self)
        dlg.geometry('640x520')

        # 顶部选项栏
        opts = tk.Frame(dlg, bg=COLORS['bg_card'])
        opts.pack(fill=tk.X, padx=16, pady=(14, 8))

        # ── 内容选择（chip 段控件） ──
        mode_var = tk.StringVar(value=self._export_mode)
        chips = {}

        scheme_var = tk.StringVar(value=current_scheme_label)

        def _refresh():
            self._export_mode = mode_var.get()
            self._export_punct_to_newline = punct_var.get()
            self._export_scheme_id = scheme_names.get(
                scheme_var.get(), self._export_scheme_id)
            mode = mode_var.get()
            if mode == 'both':
                t = self._build_both_text(punct_var.get())
            elif mode == 'suno':
                base = self._get_suno_result(self._export_scheme_id)
                t = (self._convert_punct_to_newline(base)
                     if punct_var.get() else base)
            else:
                base = phon_text if mode == 'phon' else raw_text
                t = (self._convert_punct_to_newline(base)
                     if punct_var.get() else base)
            for val, c in chips.items():
                _set_chip_active(c, val == mode)
            # 音标用 Cambria，原文/全部用 YaHei；字号都用 10
                font = (('Cambria', 10) if mode in ('phon', 'suno')
                    else ('Microsoft YaHei', 10))
            txt.configure(state=tk.NORMAL, font=font)
            txt.delete('1.0', tk.END)
            txt.insert('1.0', t)

        def _set_chip_active(chip, active):
            if active:
                chip.configure(bg=COLORS['accent_light'], fg=COLORS['accent'])
            else:
                chip.configure(bg=COLORS['bg_card'], fg=COLORS['text_secondary'])

        seg = tk.Frame(opts, bg=COLORS['bg_card'],
                       highlightbackground=COLORS['border'],
                       highlightthickness=1)
        seg.pack(side=tk.LEFT)
        for label, val in [('NOCM', 'phon'), ('Suno', 'suno'),
                           ('原文', 'raw'), ('全部', 'both')]:
            chip = tk.Label(seg, text=label, font=('Microsoft YaHei', 9),
                            bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                            padx=14, pady=4, cursor='hand2')
            chip.pack(side=tk.LEFT)
            chip.bind('<Button-1>',
                      lambda e, v=val: (mode_var.set(v), _refresh()))
            chips[val] = chip

        scheme_menu = tk.OptionMenu(opts, scheme_var, *scheme_labels,
                                    command=lambda _v: _refresh())
        scheme_menu.configure(font=('Microsoft YaHei', 9),
                              bg=COLORS['bg_card'],
                              fg=COLORS['text_secondary'],
                              activebackground=COLORS['accent_light'],
                              activeforeground=COLORS['accent'],
                              highlightbackground=COLORS['border'],
                              highlightthickness=1,
                              borderwidth=0,
                              cursor='hand2')
        scheme_menu['menu'].configure(font=('Microsoft YaHei', 9),
                                      bg=COLORS['bg_card'],
                                      fg=COLORS['text_primary'],
                                      activebackground=COLORS['accent_light'],
                                      activeforeground=COLORS['accent'])
        scheme_menu.pack(side=tk.LEFT, padx=(10, 0))

        punct_var = tk.BooleanVar(value=self._export_punct_to_newline)

        def _refresh_punct_chip():
            on = punct_var.get()
            if on:
                punct_chip.configure(bg=COLORS['accent_light'],
                                     fg=COLORS['accent'],
                                     text='☑  把标点转换为换行')
            else:
                punct_chip.configure(bg=COLORS['bg_card'],
                                     fg=COLORS['text_secondary'],
                                     text='☐  把标点转换为换行')

        def _toggle_punct(_e=None):
            punct_var.set(not punct_var.get())
            _refresh_punct_chip()
            _refresh()

        punct_chip = tk.Label(opts, text='☐  把标点转换为换行',
                              font=('Microsoft YaHei', 9),
                              bg=COLORS['bg_card'],
                              fg=COLORS['text_secondary'],
                              padx=12, pady=4, cursor='hand2',
                              highlightbackground=COLORS['border'],
                              highlightthickness=1)
        punct_chip.pack(side=tk.LEFT, padx=(10, 0))
        punct_chip.bind('<Button-1>', _toggle_punct)
        _refresh_punct_chip()

        def _do_copy():
            content = txt.get('1.0', 'end-1c')
            self.clipboard_clear()
            self.clipboard_append(content)
            copy_btn.set_text('已复制 ✓')
            self.after(1200, lambda: copy_btn.set_text('复制全部'))

        copy_btn = ModernButton(opts, '复制全部', command=_do_copy,
                                primary=True, width=88, height=28)
        copy_btn.pack(side=tk.RIGHT, padx=(8, 0))
        ModernButton(opts, '关闭', command=dlg.destroy,
                     primary=False, width=64, height=28).pack(side=tk.RIGHT)

        # 文本框 + 滚动条
        body = tk.Frame(dlg, bg=COLORS['bg_card'])
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 14))
        sb = tk.Scrollbar(body)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt = tk.Text(body, wrap=tk.WORD,
                      font=('Cambria', 10),
                      bg=COLORS['bg_canvas'], fg=COLORS['text_primary'],
                      insertbackground=COLORS['cursor'],
                      borderwidth=0, relief='flat',
                      highlightthickness=1,
                      highlightbackground=COLORS['border'],
                      highlightcolor=COLORS['accent'],
                      yscrollcommand=sb.set, padx=10, pady=8)
        txt.pack(fill=tk.BOTH, expand=True)
        sb.config(command=txt.yview)

        _refresh()
        txt.focus_set()

        # 居中
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        x = self.winfo_x() + (self.winfo_width() - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        dlg.geometry(f'+{x}+{y}')

    def _on_help(self):
        import webbrowser
        dlg = tk.Toplevel(self)
        dlg.title('帮助')
        dlg.configure(bg=COLORS['bg_card'])
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        inner = tk.Frame(dlg, bg=COLORS['bg_card'])
        inner.pack(fill=tk.BOTH, expand=True)

        pad = {'padx': 20}

        # ─── 使用说明 ───
        tk.Label(inner, text='使用说明', font=('Microsoft YaHei', 14, 'bold'),
                 bg=COLORS['bg_card'], fg=COLORS['text_primary']
                 ).pack(anchor='w', pady=(16, 8), **pad)

        help_text = (
            '1. 直接在编辑区输入或粘贴汉字文本\n'
            '2. 每个字实时显示注音\n'
            '3. 多音字颜色含义：\n'
            '   · 橙色 = 未手动选择读音\n'
            '   · 绿色 = 已手动选择读音\n'
            '   · 蓝色 = 通过「全局应用」间接选择\n'
            '   · 紫色 = 上一次「全局应用」间接选择\n'
            '   · 琥珀色边框 = 数据更新后读音有变化\n'
            '   · 粉色双条 = 手动高亮（独立于以上颜色）\n'
            '4. 点击多音字在右侧面板选择读音\n'
            '   · 点击「全局应用」将读音应用到所有同字\n'
            '5. 点击任意文字可在右侧查看读音和释义\n'
            '6. 点击「导出」打开导出对话框（音标 / 原文 · 标点转换行 · 复制）\n'
            '7. 按 Ctrl+F 在当前文稿中搜索汉字 / 音标\n'
            '   · 回车下一个，Shift+回车上一个，Esc 关闭\n'
            '8. 点击「高亮」进入高亮模式后点击字可添加/取消手动高亮\n'
            '   · 再次点击「高亮」或按 Esc 退出该模式\n'
            '9. 点击「保存」保存当前文稿\n\n'
            '方括号 [] 内的内容原样保留，不做转换。\n'
            'Ctrl+Z 撤回　Ctrl+Y / Ctrl+Shift+Z 重做\n'
            'Ctrl+S 保存文稿　Ctrl+C 复制原文（或选区）　Ctrl+V 粘贴　Ctrl+F 搜索　Ctrl+A 全选\n'
            '鼠标拖动 / Shift+点击 / Shift+方向键 选择文本，Delete / Backspace 删除选区'
        )
        tk.Label(inner, text=help_text, font=('Microsoft YaHei', 9),
                 bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                 justify='left'
                 ).pack(anchor='w', **pad)

        # ─── 分隔线 ───
        tk.Frame(inner, bg=COLORS['divider'], height=1
                 ).pack(fill=tk.X, pady=12, **pad)

        # ─── 关于 ───
        tk.Label(inner, text='关于', font=('Microsoft YaHei', 14, 'bold'),
                 bg=COLORS['bg_card'], fg=COLORS['text_primary']
                 ).pack(anchor='w', pady=(0, 8), **pad)

        about_items = [
            ('作者', 'Bilibili-@-凛武-'),
            ('拟音', '知乎-@Nulll'),
            ('源数据1', 'https://zhuanlan.zhihu.com/p/12987993957'),
            ('源数据2', 'https://github.com/qwert-ly/xtext'),
            ('测试', 'Bilibili-@Freegrep'),
        ]
        for label, value in about_items:
            row = tk.Frame(inner, bg=COLORS['bg_card'])
            row.pack(fill=tk.X, pady=2, **pad)
            tk.Label(row, text=f'{label}：', font=('Microsoft YaHei', 9, 'bold'),
                     bg=COLORS['bg_card'], fg=COLORS['text_primary']
                     ).pack(side=tk.LEFT)
            if value.startswith('https://'):
                link = tk.Label(row, text=value, font=('Microsoft YaHei', 9),
                                bg=COLORS['bg_card'], fg=COLORS['accent'],
                                cursor='hand2')
                link.pack(side=tk.LEFT)
                link.bind('<Button-1>',
                          lambda e, url=value: webbrowser.open(url))
            else:
                tk.Label(row, text=value, font=('Microsoft YaHei', 9),
                         bg=COLORS['bg_card'], fg=COLORS['text_secondary']
                         ).pack(side=tk.LEFT)

        # 底部留白
        tk.Frame(inner, bg=COLORS['bg_card'], height=16).pack()

        # 等内容排列完毕后自适应大小并居中
        dlg.update_idletasks()
        w = inner.winfo_reqwidth()
        h = inner.winfo_reqheight()
        x = self.winfo_x() + (self.winfo_width() - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        dlg.geometry(f'{w}x{h}+{x}+{y}')

    # ── 文稿管理 ─────────────────────────

    def _update_title(self):
        """更新标题栏和副标题以反映保存状态。"""
        base = '汉字转 NOCM 音标'
        if self._current_draft:
            draft_name = get_draft_name(self._current_draft)
            base = f'{base} — {draft_name}'
        if self.buf.dirty:
            self.title(f'● {base}')
            self._subtitle_lbl.configure(text='  ⚠ 未保存的更改', fg=COLORS['warning'])
        else:
            self.title(base)
            self._subtitle_lbl.configure(text='  输入即注音 · 点击彩色字修改读音', fg=COLORS['text_muted'])



    def _check_unsaved(self):
        """检查未保存的更改，返回 True 表示可以继续。"""
        if not self.buf.dirty:
            return True
        result = messagebox.askyesnocancel(
            '未保存的更改', '当前文稿有未保存的更改，是否保存？')
        if result is None:
            return False
        if result:
            self._save_draft(filename=self._current_draft)
            self._build_sidebar_drafts()
        return True

    def _on_close(self):
        if not self._check_unsaved():
            return
        self.destroy()

    def _on_restart(self):
        """重启应用程序。"""
        if not self._check_unsaved():
            return
        self.destroy()
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    def _on_toggle_theme(self):
        """切换深色/浅色主题，平滑过渡颜色（不销毁控件）。"""
        new = 'light' if get_theme() == 'dark' else 'dark'
        set_theme(new)

        # 1) 所有通过 style() 注册的控件平滑过渡
        apply_theme_transition(250)

        # 2) ModernButton（Canvas 多边形）单独更新
        for btn in self._mod_buttons:
            btn.update_theme()
        self._theme_btn.set_text('☀' if new == 'dark' else '☾')

        # 2.5) 搜索栏 chip 的 active/inactive 颜色由 _set_search_scope
        # 直接读取 COLORS 写入，未走 style() 注册，需手动重新应用
        if hasattr(self, '_scope_chips') and self._scope_chips:
            self._set_search_scope(self._search_scope.get(), refresh=False)

        # 3) 重绘编辑器 Canvas（内容用新色重建）
        self._rebuild_display()

        # 4) 侧边栏内容用新色重建（内容轻量，freeze/thaw 无闪烁）
        self._build_sidebar_drafts()
        if self._selected_poly:
            sli, sci = self._selected_poly
            if (sli < len(self.buf.buffer)
                    and sci < len(self.buf.buffer[sli])
                    and sci < len(self.buf.cell_info[sli])
                    and self.buf.cell_info[sli][sci].get('is_poly')):
                sidebar_options.build_options(
                    self.sidebar, sli, sci,
                    self.buf.buffer[sli][sci],
                    self.buf.cell_info[sli][sci],
                    self.buf.buffer, on_apply=self._apply_reading)
            else:
                self._selected_poly = None
                sidebar_options.build_placeholder(self.sidebar)
        else:
            sidebar_options.build_placeholder(self.sidebar)

        self._update_title()

    def _save_draft(self, filename=None, name=None):
        self._current_draft = save_draft(
            filename, name, self.buf.buffer, self.buf.cell_info)
        self.buf.dirty = False

    def _load_draft(self, filename):
        """从文件加载文稿。"""
        self.buf.buffer, self.buf.cell_info = load_draft(filename, self.mapping)
        self.buf.cur_line = 0
        self.buf.cur_col = 0
        self.buf.undo_stack.clear()
        self.buf.redo_stack.clear()
        self._selected_poly = None
        self._current_draft = filename
        self.buf.dirty = False
        # 标记数据更新后读音变化的字
        changed = get_changed_chars()
        if changed:
            for line_chars, line_info in zip(self.buf.buffer, self.buf.cell_info):
                for ch, info in zip(line_chars, line_info):
                    if ch in changed:
                        info['stale'] = True
        self._rebuild_display()

    def _delete_draft(self, filename):
        """删除文稿文件。"""
        delete_draft(filename)
        if self._current_draft == filename:
            self._current_draft = None
            self.buf.dirty = True

    def _rename_draft(self, filename, new_name):
        """重命名文稿。"""
        rename_draft(filename, new_name)

    def _on_save(self):
        """保存按钮回调。"""
        raw = ''.join(self.buf.buffer[0]) if self.buf.buffer[0] else ''
        if not raw.strip() and len(self.buf.buffer) <= 1:
            messagebox.showinfo('提示', '没有可保存的内容。')
            return
        self._save_draft(filename=self._current_draft)
        self._build_sidebar_drafts()

    # ── 文稿侧边栏委托 ──────────────────────────

    def _build_sidebar_drafts(self):
        sidebar_drafts.build(
            self.left_sidebar,
            current_draft=self._current_draft,
            on_load=self._handle_load_draft,
            on_new=self._on_new_draft,
            on_delete=self._handle_delete_draft,
            on_rename=self._handle_rename_draft,
            on_rebuild=self._build_sidebar_drafts,
        )

    def _handle_load_draft(self, fn):
        if not self._check_unsaved():
            return
        freeze_redraw(self)
        try:
            self._load_draft(fn)
            self._build_sidebar_drafts()
        finally:
            thaw_redraw(self)

    def _handle_delete_draft(self, fn, name):
        if messagebox.askyesno('确认删除', f'确定要删除文稿「{name}」吗？'):
            self._delete_draft(fn)
            self._build_sidebar_drafts()

    def _handle_rename_draft(self, fn, old_name):
        sidebar_drafts.show_rename_dialog(
            self, fn, old_name, on_done=self._build_sidebar_drafts)

    def _on_new_draft(self):
        if not self._check_unsaved():
            return
        self._reset_editor()
        self._save_draft(filename=None, name='未命名文稿')
        self._rebuild_display()
        self._build_sidebar_drafts()

    # ── 搜索栏 ────────────────────────────────────

    def _build_search_bar(self, parent):
        """创建搜索栏（默认隐藏，外观与工具栏一致）。"""
        # 包含分隔线 + 主体的容器
        bar = tk.Frame(parent, bg=COLORS['bg_card'])
        style(bar, bg='bg_card')
        self._search_bar = bar

        inner = tk.Frame(bar, bg=COLORS['bg_card'])
        inner.pack(fill=tk.X, padx=20, pady=8)
        style(inner, bg='bg_card')

        # 搜索图标
        icon = tk.Label(inner, text='🔍', font=('Segoe UI Symbol', 11),
                        bg=COLORS['bg_card'], fg=COLORS['text_muted'])
        icon.pack(side=tk.LEFT, padx=(0, 6))
        style(icon, bg='bg_card', fg='text_muted')

        # 输入框（细边框，圆角观感由 padding 替代）
        entry_wrap = tk.Frame(inner, bg=COLORS['bg_canvas'],
                              highlightbackground=COLORS['border'],
                              highlightcolor=COLORS['accent'],
                              highlightthickness=1)
        entry_wrap.pack(side=tk.LEFT)
        style(entry_wrap, bg='bg_canvas',
              highlightbackground='border', highlightcolor='accent')
        self._search_var = tk.StringVar()
        entry = tk.Entry(entry_wrap, textvariable=self._search_var,
                         font=('Microsoft YaHei', 10),
                         bg=COLORS['bg_canvas'], fg=COLORS['text_primary'],
                         insertbackground=COLORS['cursor'],
                         relief='flat', borderwidth=0,
                         highlightthickness=0, width=22)
        entry.pack(padx=8, pady=4, ipady=1)
        style(entry, bg='bg_canvas', fg='text_primary',
              insertbackground='cursor')
        self._search_entry = entry

        self._search_var.trace_add('write', lambda *a: self._run_search())
        entry.bind('<Return>', lambda e: self._jump_match(1))
        entry.bind('<Shift-Return>', lambda e: self._jump_match(-1))
        entry.bind('<Escape>', lambda e: self._on_toggle_search())
        entry.bind('<Control-f>', lambda e: (self._on_toggle_search(), 'break')[1])
        entry.bind('<Control-F>', lambda e: (self._on_toggle_search(), 'break')[1])

        # 范围 chip 段控件
        self._search_scope = tk.StringVar(value='all')
        self._scope_chips = {}
        seg = tk.Frame(inner, bg=COLORS['bg_card'],
                       highlightbackground=COLORS['border'],
                       highlightthickness=1)
        seg.pack(side=tk.LEFT, padx=(10, 0))
        style(seg, bg='bg_card', highlightbackground='border')
        for label, val in [('全部', 'all'), ('汉字', 'char'), ('音标', 'phon')]:
            chip = tk.Label(seg, text=label, font=('Microsoft YaHei', 9),
                            bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                            padx=10, pady=3, cursor='hand2')
            chip.pack(side=tk.LEFT)
            chip.bind('<Button-1>',
                      lambda e, v=val: self._set_search_scope(v))
            self._scope_chips[val] = chip
        self._set_search_scope('all', refresh=False)

        # 计数
        self._search_count_lbl = tk.Label(inner, text='',
                                          font=('Microsoft YaHei', 9),
                                          bg=COLORS['bg_card'],
                                          fg=COLORS['text_muted'])
        self._search_count_lbl.pack(side=tk.LEFT, padx=(12, 0))
        style(self._search_count_lbl, bg='bg_card', fg='text_muted')

        # 右侧按钮（与工具栏同款 ModernButton）
        btn_close = ModernButton(inner, '关闭', command=self._on_toggle_search,
                                 primary=False, width=56, height=26)
        btn_close.pack(side=tk.RIGHT)
        btn_next = ModernButton(inner, '下一个',
                                command=lambda: self._jump_match(1),
                                primary=False, width=56, height=26)
        btn_next.pack(side=tk.RIGHT, padx=(0, 6))
        btn_prev = ModernButton(inner, '上一个',
                                command=lambda: self._jump_match(-1),
                                primary=False, width=56, height=26)
        btn_prev.pack(side=tk.RIGHT, padx=(0, 6))
        for b in (btn_close, btn_next, btn_prev):
            style(b, bg='bg_card')
            self._mod_buttons.append(b)

        # 底部分隔线
        div = tk.Frame(bar, bg=COLORS['divider'], height=1)
        div.pack(fill=tk.X)
        style(div, bg='divider')

    def _set_search_scope(self, val, refresh=True):
        self._search_scope.set(val)
        for v, chip in self._scope_chips.items():
            if v == val:
                chip.configure(bg=COLORS['accent_light'], fg=COLORS['accent'])
            else:
                chip.configure(bg=COLORS['bg_card'],
                               fg=COLORS['text_secondary'])
        if refresh:
            self._run_search()

    def _on_toggle_search(self):
        if self._search_visible:
            # 关闭搜索
            self._search_bar.pack_forget()
            self._search_visible = False
            self._clear_search_hits()
            self._rebuild_display()
            self.canvas.focus_set()
        else:
            self._search_bar.pack(side=tk.TOP, fill=tk.X,
                                  before=self.canvas)
            self._search_visible = True
            self._search_entry.focus_set()
            self._search_entry.select_range(0, tk.END)
            self._run_search()

    def _clear_search_hits(self):
        for line_info in self.buf.cell_info:
            for info in line_info:
                if 'search_hit' in info:
                    info.pop('search_hit', None)
        self._search_matches = []
        self._search_idx = 0

    def _run_search(self):
        q = self._search_var.get().strip()
        scope = self._search_scope.get()
        self._clear_search_hits()
        if not q:
            self._search_count_lbl.configure(text='')
            self._rebuild_display()
            return
        ql = q.lower()
        matches = []
        for li, (lc, linfo) in enumerate(zip(self.buf.buffer, self.buf.cell_info)):
            for ci, (ch, info) in enumerate(zip(lc, linfo)):
                hit = False
                if scope in ('all', 'char') and ch and q in ch:
                    hit = True
                if not hit and scope in ('all', 'phon'):
                    phon = info.get('phonetic', '') or ''
                    if phon and ql in phon.lower():
                        hit = True
                if hit:
                    info['search_hit'] = True
                    matches.append((li, ci))
        self._search_matches = matches
        if matches:
            self._search_idx = 0
            li, ci = matches[0]
            self.buf.cell_info[li][ci]['search_hit'] = 'current'
            self._search_count_lbl.configure(
                text=f'{self._search_idx + 1}/{len(matches)}')
        else:
            self._search_count_lbl.configure(text='无匹配')
        self._rebuild_display()

    def _jump_match(self, step):
        if not self._search_matches:
            return
        # 还原上一个 current 为普通 hit
        cur_li, cur_ci = self._search_matches[self._search_idx]
        if (cur_li < len(self.buf.cell_info)
                and cur_ci < len(self.buf.cell_info[cur_li])):
            self.buf.cell_info[cur_li][cur_ci]['search_hit'] = True
        self._search_idx = (self._search_idx + step) % len(self._search_matches)
        li, ci = self._search_matches[self._search_idx]
        self.buf.cell_info[li][ci]['search_hit'] = 'current'
        self.buf.cur_line = li
        self.buf.cur_col = min(ci + 1, len(self.buf.buffer[li]))
        self._search_count_lbl.configure(
            text=f'{self._search_idx + 1}/{len(self._search_matches)}')
        self._rebuild_display()

    # ── 高亮模式 ──────────────────────────────────

    def _on_toggle_highlight(self):
        self._highlight_mode = not self._highlight_mode
        # 视觉反馈：切换按钮 primary 状态
        if self._highlight_btn is not None:
            self._highlight_btn.primary = self._highlight_mode
            self._highlight_btn.update_theme()
        # 副标题提示
        if self._highlight_mode:
            self._subtitle_lbl.configure(
                text='  高亮模式：点击字添加/取消高亮（Esc 退出）',
                fg=COLORS['manual_hl'])
            self.bind_all('<Escape>', lambda e: self._exit_highlight_mode())
        else:
            self._exit_highlight_mode()

    def _exit_highlight_mode(self):
        self._highlight_mode = False
        if self._highlight_btn is not None:
            self._highlight_btn.primary = False
            self._highlight_btn.update_theme()
        try:
            self.unbind_all('<Escape>')
        except tk.TclError:
            pass
        self._update_title()
