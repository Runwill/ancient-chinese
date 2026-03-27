"""GUI 模块：汉字转 NOCM 音标的可视化编辑器（现代化 UI）。"""

import tkinter as tk
import tkinter.font as tkFont
from tkinter import messagebox
from typing import List, Optional, Tuple

from constants import (COLORS, _CELL_PAD, _CELL_GAP,
                       _LINE_GAP, _CANVAS_MARGIN, MAX_UNDO)
from widgets import ModernButton
import draft_manager
import sidebar_drafts
import sidebar_options


class App(tk.Tk):
    def __init__(self, mapping):
        super().__init__()
        self.mapping = mapping
        self.title('汉字转 NOCM 音标')
        self.geometry('1200x720')
        self.minsize(900, 600)
        self.configure(bg=COLORS['bg_main'])

        self.buffer: List[List[str]] = [[]]
        self.cell_info: List[List[dict]] = [[]]
        self.cur_line = 0
        self.cur_col = 0
        self._cell_rects: List[List[Tuple[int, int, int, int]]] = [[]]
        self._line_y: List[int] = [_CANVAS_MARGIN]
        self._cursor_id = None
        self._last_canvas_w = 0
        self.undo_stack: list = []
        self.redo_stack: list = []
        
        # 当前选中的多音字信息（用于右侧边栏）
        self._selected_poly = None  # (line_idx, col_idx)
        # 当前文稿文件名（None表示新文稿）
        self._current_draft: Optional[str] = None
        # 未保存标记
        self._dirty = False

        self._build_ui()

    # ── 构建界面 ──────────────────────────────────

    def _build_ui(self):
        # 主容器
        main = tk.Frame(self, bg=COLORS['bg_main'], padx=20, pady=16)
        main.pack(fill=tk.BOTH, expand=True)
        
        # ── 顶部标题栏 ──
        header = tk.Frame(main, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 16))
        
        # 标题
        title_frame = tk.Frame(header, bg=COLORS['bg_main'])
        title_frame.pack(side=tk.LEFT)
        tk.Label(title_frame, text='汉字转 NOCM 音标',
                font=('Microsoft YaHei', 18, 'bold'),
                bg=COLORS['bg_main'], fg=COLORS['text_primary']).pack(side=tk.LEFT)
        self._subtitle_lbl = tk.Label(title_frame, text='  输入即注音 · 点击彩色字修改读音',
                font=('Microsoft YaHei', 10),
                bg=COLORS['bg_main'], fg=COLORS['text_muted'])
        self._subtitle_lbl.pack(side=tk.LEFT, pady=(6, 0))
        
        # 按钮组
        btn_frame = tk.Frame(header, bg=COLORS['bg_main'])
        btn_frame.pack(side=tk.RIGHT)
        
        for text, cmd, pri in [('帮助', self._on_help, False),
                               ('清空', self._on_clear, False),
                               ('保存', self._on_save, False),
                               ('复制', self._on_copy, True)]:
            ModernButton(btn_frame, text, command=cmd,
                        primary=pri, width=64).pack(
                side=tk.LEFT, padx=(0, 0 if pri else 8))

        # ── 主内容区（左侧文稿栏 + 编辑区 + 右侧读音栏） ──
        content = tk.Frame(main, bg=COLORS['bg_main'])
        content.pack(fill=tk.BOTH, expand=True)

        # ── 左侧边栏（文稿管理面板） ──
        self.left_sidebar = tk.Frame(content, bg=COLORS['bg_sidebar'], width=260,
                                    highlightbackground=COLORS['border'],
                                    highlightthickness=1)
        self.left_sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))
        self.left_sidebar.pack_propagate(False)

        # 编辑区卡片
        edit_card = tk.Frame(content, bg=COLORS['bg_card'], 
                            highlightbackground=COLORS['border'],
                            highlightcolor=COLORS['border'],
                            highlightthickness=1)
        edit_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 16))
        
        # 编辑区内部
        edit_inner = tk.Frame(edit_card, bg=COLORS['bg_card'], padx=4, pady=4)
        edit_inner.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(edit_inner, bg=COLORS['bg_canvas'],
                                highlightthickness=0,
                                yscrollincrement=20)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # ── 右侧边栏（音标选择面板） ──
        self.sidebar = tk.Frame(content, bg=COLORS['bg_sidebar'], width=280,
                               highlightbackground=COLORS['border'],
                               highlightthickness=1)
        self.sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        
        sidebar_options.build_placeholder(self.sidebar)

        # 初始构建文稿列表
        self._build_sidebar_drafts()

        # 字体设置
        self._char_font = tkFont.Font(family='Microsoft YaHei', size=14)
        self._phon_font = tkFont.Font(family='Consolas', size=10)
        self._char_h = self._char_font.metrics('linespace')
        self._phon_h = self._phon_font.metrics('linespace')
        self._cell_h = self._char_h + self._phon_h + _CELL_PAD * 2

        self.canvas.bind('<Key>', self._on_key)
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Configure>', self._on_configure)
        self.canvas.focus_set()
    
    # ── 撤回 / 重做 ──────────────────────────────

    def _snapshot(self):
        return (
            [row[:] for row in self.buffer],
            [[d.copy() for d in row] for row in self.cell_info],
            self.cur_line,
            self.cur_col,
        )

    def _restore_snapshot(self, snap):
        self.buffer, self.cell_info, self.cur_line, self.cur_col = (
            snap[0], snap[1], snap[2], snap[3])

    def _save_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _undo(self):
        self._do_undo_redo(self.undo_stack, self.redo_stack)

    def _redo(self):
        self._do_undo_redo(self.redo_stack, self.undo_stack)

    def _do_undo_redo(self, src, dst):
        if not src:
            return
        dst.append(self._snapshot())
        self._restore_snapshot(src.pop())
        self._rebuild_display()

    # ── 键盘处理 ──────────────────────────────────

    def _on_key(self, event):
        ctrl = bool(event.state & 0x4)
        if ctrl:
            _acts = {'v': self._on_paste, 'c': self._copy_raw,
                     'y': self._redo, 's': self._on_save}
            k = event.keysym.lower()
            if k == 'z':
                (self._redo if event.state & 0x1 else self._undo)()
            elif k in _acts:
                _acts[k]()
            return 'break'

        ks = event.keysym
        if ks == 'BackSpace':
            self._backspace()
            return 'break'
        if ks == 'Delete':
            self._delete_char()
            return 'break'
        if ks == 'Return':
            self._insert_newline()
            return 'break'
        if ks in ('Left', 'Right', 'Up', 'Down', 'Home', 'End'):
            self._handle_nav(ks)
            return 'break'

        if event.char and len(event.char) == 1 and event.char.isprintable():
            self._insert_chars(event.char)
            return 'break'

        return 'break'

    def _on_paste(self, event=None):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return 'break'
        if text:
            self._save_undo()
            self._insert_chars_raw(text)
        return 'break'

    def _on_canvas_click(self, event):
        self.canvas.focus_set()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        for li, line_rects in enumerate(self._cell_rects):
            for ci, (x1, y1, x2, y2) in enumerate(line_rects):
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    info = self.cell_info[li][ci]
                    br = self._find_bracket_ranges(self.buffer[li])
                    if info['is_poly'] and info['options'] and not self._in_bracket(ci, br):
                        self._on_cell_click(li, ci)
                        return
                    self.cur_line = li
                    self.cur_col = min(ci + 1, len(self.buffer[li]))
                    self._update_cursor()
                    return
        best_li = 0
        for i, ly in enumerate(self._line_y):
            if cy >= ly:
                best_li = i
        best_li = min(best_li, len(self.buffer) - 1)
        self.cur_line = best_li
        self.cur_col = len(self.buffer[best_li])
        self._update_cursor()

    def _on_mousewheel(self, event):
        if event.delta > 0 and self.canvas.yview()[0] <= 0:
            return
        self.canvas.yview_scroll(-event.delta // 40, 'units')

    def _on_configure(self, event):
        if event.width != self._last_canvas_w:
            self._last_canvas_w = event.width
            self._rebuild_display()

    # ── 缓冲区操作 ────────────────────────────────

    def _make_cell_info(self, ch):
        opts = self.mapping.get(ch)
        if not opts:
            return {'phonetic': ch, 'options': None, 'is_poly': False, 'selected': 'none'}
        first = opts[0]
        phon = first['phonetic'] if isinstance(first, dict) else str(first)
        is_poly = len(opts) > 1
        return {
            'phonetic': phon,
            'options': opts if is_poly else None,
            'is_poly': is_poly,
            'selected': 'none',
        }

    def _insert_chars(self, text):
        self._save_undo()
        self.buffer[self.cur_line].insert(self.cur_col, text)
        self.cell_info[self.cur_line].insert(self.cur_col, self._make_cell_info(text))
        self.cur_col += 1
        self._rebuild_display()

    def _insert_chars_raw(self, text):
        for ch in text:
            if ch == '\n':
                self._do_newline()
            elif ch == '\r':
                continue
            else:
                self.buffer[self.cur_line].insert(self.cur_col, ch)
                self.cell_info[self.cur_line].insert(self.cur_col,
                                                     self._make_cell_info(ch))
                self.cur_col += 1
        self._rebuild_display()

    def _do_newline(self):
        rest = self.buffer[self.cur_line][self.cur_col:]
        rest_info = self.cell_info[self.cur_line][self.cur_col:]
        self.buffer[self.cur_line] = self.buffer[self.cur_line][:self.cur_col]
        self.cell_info[self.cur_line] = self.cell_info[self.cur_line][:self.cur_col]
        self.cur_line += 1
        self.cur_col = 0
        self.buffer.insert(self.cur_line, rest)
        self.cell_info.insert(self.cur_line, rest_info)

    def _insert_newline(self):
        self._save_undo()
        self._do_newline()
        self._rebuild_display()

    def _backspace(self):
        if self.cur_col == 0 and self.cur_line == 0:
            return
        self._save_undo()
        if self.cur_col > 0:
            self.cur_col -= 1
            del self.buffer[self.cur_line][self.cur_col]
            del self.cell_info[self.cur_line][self.cur_col]
        elif self.cur_line > 0:
            prev = self.buffer[self.cur_line - 1]
            prev_info = self.cell_info[self.cur_line - 1]
            self.cur_col = len(prev)
            prev.extend(self.buffer[self.cur_line])
            prev_info.extend(self.cell_info[self.cur_line])
            del self.buffer[self.cur_line]
            del self.cell_info[self.cur_line]
            self.cur_line -= 1
        self._rebuild_display()

    def _delete_char(self):
        line = self.buffer[self.cur_line]
        if self.cur_col >= len(line) and self.cur_line >= len(self.buffer) - 1:
            return
        self._save_undo()
        if self.cur_col < len(line):
            del line[self.cur_col]
            del self.cell_info[self.cur_line][self.cur_col]
        elif self.cur_line < len(self.buffer) - 1:
            line.extend(self.buffer[self.cur_line + 1])
            self.cell_info[self.cur_line].extend(self.cell_info[self.cur_line + 1])
            del self.buffer[self.cur_line + 1]
            del self.cell_info[self.cur_line + 1]
        self._rebuild_display()

    def _handle_nav(self, ks):
        if ks == 'Left':
            if self.cur_col > 0:
                self.cur_col -= 1
            elif self.cur_line > 0:
                self.cur_line -= 1
                self.cur_col = len(self.buffer[self.cur_line])
        elif ks == 'Right':
            if self.cur_col < len(self.buffer[self.cur_line]):
                self.cur_col += 1
            elif self.cur_line < len(self.buffer) - 1:
                self.cur_line += 1
                self.cur_col = 0
        elif ks == 'Up':
            if self.cur_line > 0:
                self.cur_line -= 1
                self.cur_col = min(self.cur_col, len(self.buffer[self.cur_line]))
        elif ks == 'Down':
            if self.cur_line < len(self.buffer) - 1:
                self.cur_line += 1
                self.cur_col = min(self.cur_col, len(self.buffer[self.cur_line]))
        elif ks == 'Home':
            self.cur_col = 0
        elif ks == 'End':
            self.cur_col = len(self.buffer[self.cur_line])
        self._update_cursor()

    def _update_cursor(self):
        if self._cursor_id:
            self.canvas.delete(self._cursor_id)
            self._cursor_id = None
        li, ci = self.cur_line, self.cur_col
        rects = self._cell_rects[li] if li < len(self._cell_rects) else []
        if ci < len(rects):
            x, y1, y2 = rects[ci][0], rects[ci][1], rects[ci][3]
        elif rects:
            x, y1, y2 = rects[-1][2] + 1, rects[-1][1], rects[-1][3]
        else:
            ly = self._line_y[li] if li < len(self._line_y) else _CANVAS_MARGIN
            x, y1, y2 = _CANVAS_MARGIN, ly, ly + self._cell_h
        self._cursor_id = self.canvas.create_line(
            x, y1, x, y2, width=3, fill=COLORS['cursor'])
        sr = self.canvas.cget('scrollregion')
        if sr:
            parts = sr.split()
            if len(parts) == 4:
                total_h = float(parts[3])
                canvas_h = self.canvas.winfo_height()
                if total_h > canvas_h > 0:
                    vis = self.canvas.yview()
                    ft, fb = y1 / total_h, y2 / total_h
                    if ft < vis[0]:
                        self.canvas.yview_moveto(max(0, ft - 0.02))
                    elif fb > vis[1]:
                        self.canvas.yview_moveto(fb - (vis[1] - vis[0]) + 0.02)

    def _copy_raw(self):
        raw = '\n'.join(''.join(ln) for ln in self.buffer)
        if raw:
            self.clipboard_clear()
            self.clipboard_append(raw)

    # ── 显示重建 ──────────────────────────────────

    @staticmethod
    def _find_bracket_ranges(line_chars):
        ranges = []
        stk = []
        for i, ch in enumerate(line_chars):
            if ch == '[':
                stk.append(i)
            elif ch == ']' and stk:
                ranges.append((stk.pop(), i))
        return ranges

    @staticmethod
    def _in_bracket(pos, ranges):
        return any(s <= pos <= e for s, e in ranges)

    def _rebuild_display(self):
        self.canvas.delete('all')
        self._cell_rects = []
        self._line_y = []
        self._cursor_id = None
        canvas_w = max(self.canvas.winfo_width(), 200)
        ch_font, ph_font = self._char_font, self._phon_font
        ch_h, ph_h = self._char_h, self._phon_h
        cell_h = self._cell_h
        y = _CANVAS_MARGIN

        for li, (line_chars, line_info) in enumerate(
                zip(self.buffer, self.cell_info)):
            br = self._find_bracket_ranges(line_chars)
            line_rects: list = []
            x = _CANVAS_MARGIN
            self._line_y.append(y)

            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                in_brk = self._in_bracket(ci, br)
                phon = ch if in_brk else info['phonetic']
                cw = max(ch_font.measure(ch), ph_font.measure(phon)) + _CELL_PAD * 2
                if x + cw > canvas_w - _CANVAS_MARGIN and x > _CANVAS_MARGIN:
                    x = _CANVAS_MARGIN
                    y += cell_h + _CELL_GAP

                # 使用新的现代化配色
                if in_brk:
                    fg_ch, fg_ph, bg, outline = COLORS['text_muted'], COLORS['text_muted'], '', ''
                elif info['is_poly']:
                    sel = info.get('selected', 'none')
                    if sel == 'manual':
                        bg, fg_ch = COLORS['poly_green_bg'], COLORS['poly_green']
                    elif sel == 'global':
                        bg, fg_ch = COLORS['poly_blue_bg'], COLORS['poly_blue']
                    else:
                        bg, fg_ch = COLORS['poly_orange_bg'], COLORS['poly_orange']
                    fg_ph, outline = COLORS['accent'], COLORS['border']
                else:
                    fg_ch, fg_ph, bg, outline = COLORS['text_primary'], COLORS['text_muted'], '', ''

                if bg:
                    self.canvas.create_rectangle(
                        x, y, x + cw, y + cell_h,
                        fill=bg, outline=outline, width=1)
                mid = x + cw / 2
                self.canvas.create_text(
                    mid, y + _CELL_PAD, text=ch,
                    font=ch_font, fill=fg_ch, anchor='n')
                self.canvas.create_text(
                    mid, y + _CELL_PAD + ch_h, text=phon,
                    font=ph_font, fill=fg_ph, anchor='n')

                line_rects.append((x, y, x + cw, y + cell_h))
                x += cw + _CELL_GAP

            self._cell_rects.append(line_rects)
            y += cell_h + _LINE_GAP

        self.canvas.configure(
            scrollregion=(0, 0, canvas_w, max(y + _CANVAS_MARGIN, 1)))
        self._update_cursor()

    # ── 点击多音字显示侧边栏选项 ────────────────────────

    def _on_cell_click(self, li, ci):
        """点击多音字时，在侧边栏显示选项"""
        info = self.cell_info[li][ci]
        opts = info['options']
        if not opts:
            return

        self.cur_line = li
        self.cur_col = ci + 1
        self._selected_poly = (li, ci)
        sidebar_options.build_options(
            self.sidebar, li, ci, self.buffer[li][ci], info,
            self.buffer, on_apply=self._apply_reading)
        self._update_cursor()

    def _apply_reading(self, li, ci, phonetic, global_apply):
        """应用选中的读音"""
        self.after(20, lambda: self._do_apply(li, ci, phonetic, global_apply))

    def _do_apply(self, li, ci, phonetic, global_apply):
        self._save_undo()
        if global_apply:
            ch = self.buffer[li][ci]
            for _li, (lc, linfo) in enumerate(zip(self.buffer, self.cell_info)):
                for _ci, (c, info) in enumerate(zip(lc, linfo)):
                    if c == ch and info['is_poly']:
                        info['phonetic'] = phonetic
                        if _li == li and _ci == ci:
                            info['selected'] = 'manual'
                        else:
                            info['selected'] = 'global'
        else:
            self.cell_info[li][ci]['phonetic'] = phonetic
            self.cell_info[li][ci]['selected'] = 'manual'
        self._rebuild_display()
        if self._selected_poly:
            sli, sci = self._selected_poly
            sidebar_options.build_options(
                self.sidebar, sli, sci,
                self.buffer[sli][sci], self.cell_info[sli][sci],
                self.buffer, on_apply=self._apply_reading)

    # ── 辅助 ─────────────────────────────────────

    def _get_result(self):
        lines = []
        for line_chars, line_info in zip(self.buffer, self.cell_info):
            br = self._find_bracket_ranges(line_chars)
            parts = []
            bracket_buf = []
            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                if self._in_bracket(ci, br):
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

    def _reset_editor(self):
        """重置编辑器到空白状态。"""
        self.buffer = [[]]
        self.cell_info = [[]]
        self.cur_line = 0
        self.cur_col = 0
        self._selected_poly = None
        self._current_draft = None
        self._dirty = False
        self._update_title()

    def _on_clear(self):
        if any(self.buffer[0]) or len(self.buffer) > 1:
            self._save_undo()
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

    def _on_help(self):
        messagebox.showinfo('帮助', (
            '使用说明：\n\n'
            '1. 直接在编辑区输入或粘贴汉字文本\n'
            '2. 每个字实时显示注音\n'
            '3. 多音字颜色含义：\n'
            '   · 橙色 = 未手动选择读音\n'
            '   · 绿色 = 已手动选择读音\n'
            '   · 蓝色 = 通过「全局应用」间接选择\n'
            '4. 点击多音字在右侧面板选择读音\n'
            '   · 点击「全局应用」将读音应用到所有同字\n'
            '5. 点击「复制结果」复制输出到剪贴板\n'
            '6. 点击「保存」保存当前文稿\n'
            '7. 左侧文稿面板可加载/删除文稿，双击名称可重命名\n\n'
            '方括号 [] 内的内容原样保留，不做转换。\n'
            'Ctrl+Z 撤回，Ctrl+Y / Ctrl+Shift+Z 重做\n'
            'Ctrl+S 保存文稿\n'
            'Ctrl+C 复制原文，Ctrl+V 粘贴'
        ))

    # ── 文稿管理 ─────────────────────────

    def _update_title(self):
        """更新标题栏和副标题以反映保存状态。"""
        base = '汉字转 NOCM 音标'
        if self._current_draft:
            draft_name = draft_manager.get_draft_name(self._current_draft)
            base = f'{base} — {draft_name}'
        if self._dirty:
            self.title(f'● {base}')
            self._subtitle_lbl.configure(text='  ⚠ 未保存的更改', fg='#F59E0B')
        else:
            self.title(base)
            self._subtitle_lbl.configure(text='  输入即注音 · 点击彩色字修改读音', fg=COLORS['text_muted'])



    def _save_draft(self, filename=None, name=None):
        self._current_draft = draft_manager.save_draft(
            filename, name, self.buffer, self.cell_info)
        self._dirty = False
        self._update_title()

    def _load_draft(self, filename):
        """从文件加载文稿。"""
        self.buffer, self.cell_info = draft_manager.load_draft(filename, self.mapping)
        self.cur_line = 0
        self.cur_col = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._selected_poly = None
        self._current_draft = filename
        self._dirty = False
        self._update_title()
        self._rebuild_display()

    def _delete_draft(self, filename):
        """删除文稿文件。"""
        draft_manager.delete_draft(filename)
        if self._current_draft == filename:
            self._current_draft = None
            self._dirty = True
            self._update_title()

    def _rename_draft(self, filename, new_name):
        """重命名文稿。"""
        draft_manager.rename_draft(filename, new_name)

    def _on_save(self):
        """保存按钮回调。"""
        raw = ''.join(self.buffer[0]) if self.buffer[0] else ''
        if not raw.strip() and len(self.buffer) <= 1:
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
            on_rebuild=lambda: self.after(1, self._build_sidebar_drafts),
        )

    def _handle_load_draft(self, fn):
        self._load_draft(fn)
        self.after(1, self._build_sidebar_drafts)

    def _handle_delete_draft(self, fn, name):
        if messagebox.askyesno('确认删除', f'确定要删除文稿「{name}」吗？'):
            self._delete_draft(fn)
            self.after(1, self._build_sidebar_drafts)

    def _handle_rename_draft(self, fn, old_name):
        sidebar_drafts.show_rename_dialog(
            self, fn, old_name, on_done=self._build_sidebar_drafts)

    def _on_new_draft(self):
        self._reset_editor()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._rebuild_display()
        self._build_sidebar_drafts()
