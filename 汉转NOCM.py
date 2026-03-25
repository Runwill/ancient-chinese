import pandas as pd
import sys
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, List, Any, Optional

# == openpyxl 3.1.x Fill bug workaround ============================
try:
    import openpyxl.descriptors.sequence as _seq_mod
    from openpyxl.styles.fills import Fill as _Fill, PatternFill as _PFill
    _orig_convert = _seq_mod._convert
    def _safe_convert(expected_type, value):
        try:
            return _orig_convert(expected_type, value)
        except TypeError:
            if expected_type is _Fill:
                return _PFill()
            raise
    _seq_mod._convert = _safe_convert
except Exception:
    pass
# ===================================================================

EXCEL_FILE = '上古汉语音节表.xlsx'
EXCEL_NOTE_COL = 10


def load_map_from_excel(file_path, sheet_name='字典表', note_col_index=2):
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine='openpyxl')
        df = df.dropna(how='any', subset=[0, 1])
        mapping: Dict[str, List[Dict[str, Any]]] = {}
        for row in df.itertuples(index=False, name=None):
            c = str(row[0])
            p = str(row[1]).strip() if row[1] is not None else ''
            if not p:
                continue
            note = None
            if note_col_index is not None and isinstance(note_col_index, int) and note_col_index >= 0:
                if len(row) > note_col_index:
                    n = row[note_col_index]
                    if n is not None:
                        nt = str(n).strip()
                        if nt and nt.lower() not in ('nan', 'none'):
                            note = nt
            mapping.setdefault(c, []).append({'phonetic': p, 'note': note})
        return mapping
    except FileNotFoundError:
        messagebox.showerror('错误', f"找不到 '{file_path}' 文件。\n请确保该文件与脚本位于同一目录中。")
        return None
    except Exception as e:
        messagebox.showerror('错误', f'读取Excel文件时出错: {e}')
        return None


def format_note(note_txt):
    if not note_txt:
        return note_txt
    s = note_txt.strip()
    s = re.sub(r'(?<!^)(?<!\n)(\d+)(?=[\u4e00-\u9fff])', r'\n\1', s)
    return s


# ====================================================================
#  GUI — 即编即显，实时注音
# ====================================================================

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
        self._cell_frames: List[tk.Frame] = []
        self.undo_stack: list = []
        self.redo_stack: list = []

        self._build_ui()

    # ── 构建界面 ──────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        btn = ttk.Frame(main)
        btn.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn, text='撤回', command=self._undo).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn, text='重做', command=self._redo).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn, text='清空', command=self._on_clear).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn, text='帮助', command=self._on_help).pack(side=tk.LEFT)
        ttk.Button(btn, text='复制结果', command=self._on_copy).pack(side=tk.RIGHT)

        edit_lf = ttk.LabelFrame(
            main, text='编辑区（输入即注音 · 点击彩色字修改读音）', padding=5)
        edit_lf.pack(fill=tk.BOTH, expand=True, pady=4)
        edit_inner = ttk.Frame(edit_lf)
        edit_inner.pack(fill=tk.BOTH, expand=True)

        self.edit_text = tk.Text(
            edit_inner, wrap=tk.WORD,
            bg='#FAFAFA', relief=tk.FLAT,
            font=('Microsoft YaHei', 12),
            spacing1=4, spacing3=4,
            insertwidth=3, insertbackground='#5C6BC0')
        edit_scroll = ttk.Scrollbar(edit_inner, orient=tk.VERTICAL,
                                     command=self.edit_text.yview)
        self.edit_text.configure(yscrollcommand=edit_scroll.set)
        self.edit_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        edit_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.edit_text.bind('<Key>', self._on_key)
        self.edit_text.bind('<<Paste>>', self._on_paste)
        self.edit_text.bind('<Button-1>', self._on_text_click)
        self.edit_text.bind('<B1-Motion>', lambda e: 'break')
        self.edit_text.bind('<Double-Button-1>', lambda e: 'break')
        self.edit_text.bind('<Triple-Button-1>', lambda e: 'break')
        self.edit_text.focus_set()

        out_lf = ttk.LabelFrame(main, text='输出结果', padding=5)
        out_lf.pack(fill=tk.X, pady=(4, 0))
        self.output_text = scrolledtext.ScrolledText(
            out_lf, wrap=tk.WORD, height=4,
            font=('Consolas', 11), state=tk.DISABLED)
        self.output_text.pack(fill=tk.BOTH, expand=True)

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
        if not self.undo_stack:
            return
        self.redo_stack.append(self._snapshot())
        self._restore_snapshot(self.undo_stack.pop())
        self._rebuild_display()
        self._refresh_output()

    def _redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        self._restore_snapshot(self.redo_stack.pop())
        self._rebuild_display()
        self._refresh_output()

    # ── 键盘处理 ──────────────────────────────────

    def _on_key(self, event):
        ctrl = bool(event.state & 0x4)
        if ctrl:
            k = event.keysym.lower()
            if k == 'v':
                return  # let <<Paste>> handle
            if k == 'c':
                self._copy_raw()
                return 'break'
            if k == 'z':
                if event.state & 0x1:  # Shift → redo
                    self._redo()
                else:
                    self._undo()
                return 'break'
            if k == 'y':
                self._redo()
                return 'break'
            if k == 'a':
                return 'break'  # no select-all in this widget
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

    def _on_paste(self, event):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return 'break'
        if text:
            self._save_undo()
            self._insert_chars_raw(text)
        return 'break'

    def _on_text_click(self, event):
        self.after_idle(self._sync_cursor)

    def _sync_cursor(self):
        try:
            idx = self.edit_text.index(tk.INSERT)
            ln, col = idx.split('.')
            self.cur_line = max(0, min(int(ln) - 1, len(self.buffer) - 1))
            self.cur_col = max(0, min(int(col), len(self.buffer[self.cur_line])))
        except (ValueError, IndexError):
            pass

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
        """Single char insert with undo save."""
        self._save_undo()
        self._insert_chars_raw(text)

    def _insert_chars_raw(self, text):
        """Insert without saving undo (caller must save)."""
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
        self._refresh_output()

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
        self._refresh_output()

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
        self._refresh_output()

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
        self._refresh_output()

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
        cursor_idx = f'{self.cur_line + 1}.{self.cur_col}'
        self.edit_text.mark_set(tk.INSERT, cursor_idx)
        self.edit_text.see(cursor_idx)

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

        # Phase 1: pre-create all new widgets (slow, but no visual change)
        new_frames = []
        all_line_frames = []
        for li, (line_chars, line_info) in enumerate(
                zip(self.buffer, self.cell_info)):
            br = self._find_bracket_ranges(line_chars)
            line_frames = []
            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                in_brk = self._in_bracket(ci, br)
                if in_brk:
                    frame = self._make_cell_widget(ch, ch, False, None, li, ci)
                else:
                    frame = self._make_cell_widget(
                        ch, info['phonetic'], info['is_poly'],
                        info['options'], li, ci,
                        info.get('selected', 'none'))
                line_frames.append(frame)
                new_frames.append(frame)
            all_line_frames.append(line_frames)

        # Phase 2: swap content (fast — just delete + window_create)
        old_frames = self._cell_frames
        self.edit_text.delete('1.0', tk.END)
        for li, line_frames in enumerate(all_line_frames):
            for frame in line_frames:
                self.edit_text.window_create(tk.END, window=frame)
            if li < len(all_line_frames) - 1:
                self.edit_text.insert(tk.END, '\n')

        cursor_idx = f'{self.cur_line + 1}.{self.cur_col}'
        self.edit_text.mark_set(tk.INSERT, cursor_idx)
        self.edit_text.see(cursor_idx)

        # Phase 3: destroy old widgets (cleanup, no visual impact)
        self._cell_frames = new_frames
        for f in old_frames:
            f.destroy()

    def _make_cell_widget(self, char_disp, phonetic, is_poly, options, li, ci,
                          selected='none'):
        if is_poly:
            if selected == 'manual':
                bg, fg_ch = '#E8F5E9', '#2E7D32'
            elif selected == 'global':
                bg, fg_ch = '#E3F2FD', '#1565C0'
            else:
                bg, fg_ch = '#FFF8E1', '#F57F17'
            fg_ph = '#5C6BC0'
            relief = tk.RIDGE
        else:
            bg, fg_ch, fg_ph = '#FAFAFA', '#37474F', '#B0BEC5'
            relief = tk.FLAT
        frame = tk.Frame(self.edit_text, bg=bg, padx=1, pady=1,
                         bd=1, relief=relief)

        char_lbl = tk.Label(frame, text=char_disp,
                            font=('Microsoft YaHei', 13),
                            bg=bg, fg=fg_ch)
        char_lbl.pack()

        phon_lbl = tk.Label(frame, text=phonetic,
                            font=('Consolas', 9),
                            bg=bg, fg=fg_ph)
        phon_lbl.pack()

        if is_poly and options:
            for w in (frame, char_lbl, phon_lbl):
                w.configure(cursor='hand2')
                w.bind('<Button-1>',
                       lambda e, _li=li, _ci=ci: self._on_cell_click(_li, _ci))
        else:
            for w in (frame, char_lbl, phon_lbl):
                w.bind('<Button-1>',
                       lambda e, _li=li, _ci=ci: self._set_cursor(_li, _ci + 1))

        return frame

    def _set_cursor(self, line, col):
        self.cur_line = line
        self.cur_col = col
        self._update_cursor()
        self.edit_text.focus_set()

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

        # 全屏透明遮罩，点击即关闭
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

        # 阴影边框
        shadow = tk.Frame(popup, bg='#D5D5D5')
        shadow.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        card = tk.Frame(shadow, bg='white', padx=14, pady=10)
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 标题行
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

            # 悬停效果
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
            for w in (row,):
                w.bind('<Enter>', _enter)
                w.bind('<Leave>', _leave)

            # 音标
            phon_lbl = tk.Label(row, text=phon,
                                font=('Consolas', 12, 'bold'),
                                bg=row_bg, fg='#5C6BC0',
                                cursor='hand2')
            phon_lbl.pack(side=tk.LEFT, padx=(0, 6))

            # 全局应用
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

            # 注释
            if note_txt:
                tk.Label(row, text=note_txt, fg='#9E9E9E', bg=row_bg,
                         font=('Microsoft YaHei', 8),
                         wraplength=360, justify=tk.LEFT,
                         anchor=tk.W
                         ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 整行可点击
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
        if hasattr(self, '_overlay') and self._overlay:
            try:
                self._overlay.destroy()
            except tk.TclError:
                pass
            self._overlay = None
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()
        self.popup = None

    def _apply_reading(self, li, ci, phonetic, global_apply):
        self._close_popup()
        # Defer data update + rebuild so ButtonRelease finishes first,
        # preventing the Text widget from interpreting it as a selection drag.
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
        self._refresh_output()

    # ── 输出刷新 ──────────────────────────────────

    def _refresh_output(self):
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
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.delete('1.0', tk.END)
        self.output_text.insert(tk.END, '\n'.join(lines))
        self.output_text.configure(state=tk.DISABLED)

    # ── 辅助 ─────────────────────────────────────

    def _on_clear(self):
        self._close_popup()
        if any(self.buffer[0]) or len(self.buffer) > 1:
            self._save_undo()
        self.buffer = [[]]
        self.cell_info = [[]]
        self.cur_line = 0
        self.cur_col = 0
        self._rebuild_display()
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.delete('1.0', tk.END)
        self.output_text.configure(state=tk.DISABLED)

    def _on_copy(self):
        text = self.output_text.get('1.0', tk.END).strip()
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


if __name__ == '__main__':
    _tmp = tk.Tk()
    _tmp.withdraw()
    mapping = load_map_from_excel(EXCEL_FILE, note_col_index=EXCEL_NOTE_COL)
    _tmp.destroy()
    if mapping is None:
        sys.exit(1)
    app = App(mapping)
    app.mainloop()
