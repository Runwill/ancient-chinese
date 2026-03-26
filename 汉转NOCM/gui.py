"""GUI 模块：汉字转 NOCM 音标的可视化编辑器。"""

import re
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk, messagebox
from typing import List, Optional, Tuple


def format_note(note_txt):
    if not note_txt:
        return note_txt
    s = note_txt.strip()
    s = re.sub(r'(?<!^)(?<!\n)(\d+)(?=[\u4e00-\u9fff])', r'\n\1', s)
    return s


_CELL_PAD = 4
_CELL_GAP = 2
_LINE_GAP = 10
_CANVAS_MARGIN = 4

MAX_UNDO = 200


class App(tk.Tk):
    def __init__(self, mapping):
        super().__init__()
        self.mapping = mapping
        self.title('汉字转 NOCM 音标')
        self.geometry('960x680')
        self.minsize(720, 480)

        self.buffer: List[List[str]] = [[]]
        self.cell_info: List[List[dict]] = [[]]
        self.cur_line = 0
        self.cur_col = 0
        self.popup: Optional[tk.Toplevel] = None
        self._overlay: Optional[tk.Toplevel] = None
        self._cell_rects: List[List[Tuple[int, int, int, int]]] = [[]]
        self._line_y: List[int] = [_CANVAS_MARGIN]
        self._cursor_id = None
        self._last_canvas_w = 0
        self.undo_stack: list = []
        self.redo_stack: list = []

        self._build_ui()

    # ── 构建界面 ──────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        btn = ttk.Frame(main)
        btn.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn, text='清空', command=self._on_clear).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn, text='帮助', command=self._on_help).pack(side=tk.LEFT)
        ttk.Button(btn, text='复制结果', command=self._on_copy).pack(side=tk.RIGHT)

        edit_lf = ttk.LabelFrame(
            main, text='编辑区（输入即注音 · 点击彩色字修改读音）', padding=5)
        edit_lf.pack(fill=tk.BOTH, expand=True, pady=4)
        edit_inner = ttk.Frame(edit_lf)
        edit_inner.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(edit_inner, bg='#FAFAFA',
                                highlightthickness=0,
                                yscrollincrement=20)
        edit_scroll = ttk.Scrollbar(edit_inner, orient=tk.VERTICAL,
                                     command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=edit_scroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        edit_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._char_font = tkFont.Font(family='Microsoft YaHei', size=13)
        self._phon_font = tkFont.Font(family='Consolas', size=9)
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
            k = event.keysym.lower()
            if k == 'v':
                self._on_paste()
                return 'break'
            if k == 'c':
                self._copy_raw()
                return 'break'
            if k == 'z':
                if event.state & 0x1:
                    self._redo()
                else:
                    self._undo()
                return 'break'
            if k == 'y':
                self._redo()
                return 'break'
            if k == 'a':
                return 'break'
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
        self.canvas.yview_scroll(-event.delta // 120, 'units')

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
            x, y1, x, y2, width=3, fill='#5C6BC0')
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
        self._close_popup()
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

                if in_brk:
                    fg_ch, fg_ph, bg, outline = '#9E9E9E', '#9E9E9E', '', ''
                elif info['is_poly']:
                    sel = info.get('selected', 'none')
                    if sel == 'manual':
                        bg, fg_ch = '#E8F5E9', '#2E7D32'
                    elif sel == 'global':
                        bg, fg_ch = '#E3F2FD', '#1565C0'
                    else:
                        bg, fg_ch = '#FFF8E1', '#F57F17'
                    fg_ph, outline = '#5C6BC0', '#DDD'
                else:
                    fg_ch, fg_ph, bg, outline = '#37474F', '#B0BEC5', '', ''

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

    # ── 注释着色辅助 ─────────────────────────────

    def _create_note_widget(self, parent, note_txt, bg):
        text_lines = note_txt.split('\n')
        est_h = sum(max(1, (len(ln) + 44) // 45) for ln in text_lines)
        tw = tk.Text(parent, wrap=tk.WORD, bg=bg, fg='#9E9E9E',
                     font=('Microsoft YaHei', 8),
                     borderwidth=0, highlightthickness=0,
                     cursor='hand2', height=est_h,
                     padx=0, pady=0, spacing1=0, spacing3=0)
        tw.tag_configure('book', foreground='#00897B')
        for part in re.split(r'(《[^》]*》)', note_txt):
            if part.startswith('《') and part.endswith('》'):
                tw.insert(tk.END, part, 'book')
            else:
                tw.insert(tk.END, part)
        tw.configure(state=tk.DISABLED)
        return tw

    # ── 点击多音字弹出选择 ────────────────────────

    def _on_cell_click(self, li, ci):
        self._close_popup()
        info = self.cell_info[li][ci]
        ch = self.buffer[li][ci]
        opts = info['options']
        if not opts:
            return

        self.cur_line = li
        self.cur_col = ci + 1

        overlay = tk.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.attributes('-alpha', 0.01)
        overlay.geometry(f'{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0')
        overlay.bind('<Button-1>', lambda e: self._close_popup())
        overlay.lift()

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg='white', bd=0)
        popup.attributes('-topmost', True)
        self.popup = popup
        self._overlay = overlay

        shadow = tk.Frame(popup, bg='#D5D5D5')
        shadow.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        card = tk.Frame(shadow, bg='white', padx=14, pady=10)
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        title_f = tk.Frame(card, bg='white')
        title_f.pack(fill=tk.X, pady=(0, 8))
        tk.Label(title_f, text=ch,
                 font=('Microsoft YaHei', 18, 'bold'),
                 bg='white', fg='#F57F17').pack(side=tk.LEFT)
        tk.Label(title_f, text='  选择读音',
                 font=('Microsoft YaHei', 10),
                 bg='white', fg='#9E9E9E').pack(side=tk.LEFT, padx=(4, 0))

        sep = tk.Frame(card, bg='#EEEEEE', height=1)
        sep.pack(fill=tk.X, pady=(0, 8))

        total = sum(ln.count(ch) for ln in self.buffer)

        for oi, o in enumerate(opts):
            phon = o.get('phonetic') if isinstance(o, dict) else str(o)
            note_raw = o.get('note') if isinstance(o, dict) else None
            note_txt = format_note(str(note_raw).strip()) if note_raw else ''
            is_current = (info['phonetic'] == phon)

            row_bg = '#F5F5F5' if is_current else 'white'
            row = tk.Frame(card, bg=row_bg, padx=8, pady=6,
                           bd=0, relief=tk.FLAT)
            row.pack(fill=tk.X, pady=1)

            def _enter(e, r=row):
                r.configure(bg='#EEEEEE')
                for w in r.winfo_children():
                    try: w.configure(bg='#EEEEEE')
                    except tk.TclError: pass
            def _leave(e, r=row, bg=row_bg):
                r.configure(bg=bg)
                for w in r.winfo_children():
                    try: w.configure(bg=bg)
                    except tk.TclError: pass
            row.bind('<Enter>', _enter)
            row.bind('<Leave>', _leave)

            phon_lbl = tk.Label(row, text=phon,
                                font=('Consolas', 12, 'bold'),
                                bg=row_bg, fg='#5C6BC0',
                                cursor='hand2')
            phon_lbl.pack(side=tk.LEFT, padx=(0, 6))

            if total > 1:
                ga = tk.Label(row, text='全局',
                              font=('Microsoft YaHei', 8),
                              bg='#FFF8E1', fg='#F57F17',
                              padx=4, pady=1, cursor='hand2',
                              relief=tk.FLAT, bd=1)
                ga.pack(side=tk.LEFT, padx=(0, 8))
                ga.bind('<Button-1>',
                        lambda e, p=phon: (self._apply_reading(li, ci, p, True), 'break')[-1])
                ga.bind('<Enter>', lambda e, w=ga: w.configure(bg='#FFE082'))
                ga.bind('<Leave>', lambda e, w=ga: w.configure(bg='#FFF8E1'))

            if note_txt:
                note_w = self._create_note_widget(row, note_txt, row_bg)
                note_w.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def _bind_click(widget, p=phon):
                widget.bind('<Button-1>',
                            lambda e: (self._apply_reading(li, ci, p, False), 'break')[-1])
            _bind_click(row)
            _bind_click(phon_lbl)

            for child in row.winfo_children():
                child.bind('<Enter>', _enter)
                child.bind('<Leave>', _leave)

        popup.update_idletasks()
        x = self.winfo_pointerx() - 20
        y = self.winfo_pointery() + 16
        pw = popup.winfo_reqwidth()
        ph = popup.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if x + pw > sw:
            x = max(0, sw - pw - 8)
        if x < 0:
            x = 4
        if y + ph > sh:
            y = max(0, self.winfo_pointery() - ph - 8)
        popup.geometry(f'+{x}+{y}')

        popup.bind('<Escape>', lambda e: self._close_popup())
        popup.focus_set()

    def _close_popup(self):
        if self._overlay:
            try:
                self._overlay.destroy()
            except tk.TclError:
                pass
            self._overlay = None
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()
        self.popup = None
        self.canvas.focus_set()

    def _apply_reading(self, li, ci, phonetic, global_apply):
        self._close_popup()
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

    def _on_clear(self):
        self._close_popup()
        if any(self.buffer[0]) or len(self.buffer) > 1:
            self._save_undo()
        self.buffer = [[]]
        self.cell_info = [[]]
        self.cur_line = 0
        self.cur_col = 0
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
            '   · 蓝色 = 通过「全局」间接选择\n'
            '4. 点击多音字可弹出面板修改读音\n'
            '   · 点击「全局」将读音应用到所有同字\n'
            '5. 点击「复制结果」复制输出到剪贴板\n\n'
            '方括号 [] 内的内容原样保留，不做转换。\n'
            'Ctrl+Z 撤回，Ctrl+Y / Ctrl+Shift+Z 重做\n'
            'Ctrl+C 复制原文，Ctrl+V 粘贴'
        ))
