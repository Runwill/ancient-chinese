import sys
import re
import os
import gzip
import json
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, List, Any, Optional

# 在线数据源（xlsx 的替代品）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_JSON_GZ_URL = 'https://qwert-ly.github.io/xtext/base.json.gz'
EXTRA_JSON_GZ_URL = 'https://qwert-ly.github.io/xtext/extra.json.gz'
BASE_JSON_GZ_LOCAL = os.path.join(_SCRIPT_DIR, 'base.json.gz')
EXTRA_JSON_GZ_LOCAL = os.path.join(_SCRIPT_DIR, 'extra.json.gz')


def download_and_update():
    """下载 base.json.gz 和 extra.json.gz 到脚本目录，静默失败。"""
    for url, local_path in [
        (BASE_JSON_GZ_URL, BASE_JSON_GZ_LOCAL),
        (EXTRA_JSON_GZ_URL, EXTRA_JSON_GZ_LOCAL),
    ]:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            tmp_path = local_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(data)
            os.replace(tmp_path, local_path)
            print(f'[更新] {os.path.basename(local_path)} ({len(data)} bytes)')
        except Exception as e:
            print(f'[跳过] {os.path.basename(local_path)} 下载失败: {e}')


def load_map_from_json_gz():
    """从本地 base.json.gz + extra.json.gz 构建映射字典。"""
    try:
        with gzip.open(BASE_JSON_GZ_LOCAL, 'rt', encoding='utf-8') as f:
            base_data = json.load(f)
    except Exception as e:
        print(f'[错误] 读取 base.json.gz 失败: {e}')
        return None

    extra_data = None
    try:
        with gzip.open(EXTRA_JSON_GZ_LOCAL, 'rt', encoding='utf-8') as f:
            extra_data = json.load(f)
    except Exception as e:
        print(f'[警告] 读取 extra.json.gz 失败 (注释将不可用): {e}')

    mapping: Dict[str, List[Dict[str, Any]]] = {}
    for i, entry in enumerate(base_data):
        ch = entry.get('z', '')
        phonetic = entry.get('p', '').strip()
        if not ch or not phonetic:
            continue

        note = None
        if extra_data and i < len(extra_data):
            ext = extra_data[i]
            parts = []
            d = ext.get('d')
            if d and isinstance(d, list):
                if len(d) > 0 and isinstance(d[0], str) and d[0].strip():
                    parts.append(d[0].strip())
                if len(d) > 1 and isinstance(d[1], list):
                    for j, defn in enumerate(d[1], 1):
                        if defn and isinstance(defn, str):
                            parts.append(f'{j}{defn}')
            e_val = ext.get('e')
            if e_val and isinstance(e_val, str) and e_val.strip():
                parts.append(e_val.strip())
            n_val = ext.get('n')
            if n_val and isinstance(n_val, str) and n_val.strip():
                parts.append(n_val.strip())
            if parts:
                note = '\n'.join(parts)

        mapping.setdefault(ch, []).append({'phonetic': phonetic, 'note': note})

    print(f'[加载] 从 JSON 加载了 {len(mapping)} 个字的音标数据')
    return mapping if mapping else None


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
        self._line_widgets: List[List[tk.Frame]] = [[]]
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
        old_snap = self._snapshot()
        self.redo_stack.append(old_snap)
        new_snap = self.undo_stack.pop()
        self._restore_snapshot(new_snap)
        if not self._try_incremental_swap(old_snap, new_snap):
            self._rebuild_display()
        self._refresh_output()

    def _redo(self):
        if not self.redo_stack:
            return
        old_snap = self._snapshot()
        self.undo_stack.append(old_snap)
        new_snap = self.redo_stack.pop()
        self._restore_snapshot(new_snap)
        if not self._try_incremental_swap(old_snap, new_snap):
            self._rebuild_display()
        self._refresh_output()

    def _try_incremental_swap(self, old_snap, new_snap):
        """Compare two snapshots; if only 1 char was added or removed
        on a single line (same line count, no bracket involvement),
        apply an incremental widget update and return True.
        Otherwise return False so caller does a full rebuild."""
        old_buf, old_info = old_snap[0], old_snap[1]
        new_buf, new_info = new_snap[0], new_snap[1]
        if len(old_buf) != len(new_buf):
            return False
        # find which line(s) differ
        diff_li = None
        for i in range(len(old_buf)):
            if old_buf[i] != new_buf[i]:
                if diff_li is not None:
                    return False  # more than one line differs
                diff_li = i
        if diff_li is None:
            # no data change — just move cursor
            self._update_cursor()
            return True
        old_line = old_buf[diff_li]
        new_line = new_buf[diff_li]
        delta = len(new_line) - len(old_line)
        if delta == 1:
            # one char was inserted — find which position
            ci = self._find_insert_pos(old_line, new_line)
            if ci is None:
                return False
            if self._line_has_brackets(new_line):
                return False
            ch = new_line[ci]
            info = new_info[diff_li][ci]
            self._incremental_insert(diff_li, ci, ch, info)
            self._update_cursor()
            return True
        if delta == -1:
            # one char was deleted — find which position
            ci = self._find_insert_pos(new_line, old_line)
            if ci is None:
                return False
            if self._line_has_brackets(old_line):
                return False
            self._incremental_delete(diff_li, ci)
            self._update_cursor()
            return True
        return False

    @staticmethod
    def _find_insert_pos(shorter, longer):
        """Given two lists where longer has exactly one extra element,
        find the index of the inserted element. Return None if the
        lists differ in more than just that one insertion."""
        n = len(shorter)
        ci = 0
        while ci < n and shorter[ci] == longer[ci]:
            ci += 1
        # verify the rest matches
        for j in range(ci, n):
            if shorter[j] != longer[ci + 1 + (j - ci)]:
                return None
        return ci

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

    @staticmethod
    def _line_has_brackets(line_chars):
        return any(ch in '[]' for ch in line_chars)

    def _incremental_delete(self, li, ci):
        """Remove one widget from display at (li, ci). O(line_len)."""
        self.edit_text.delete(f'{li + 1}.{ci}', f'{li + 1}.{ci + 1}')
        frame = self._line_widgets[li].pop(ci)
        frame.destroy()
        for i in range(ci, len(self._line_widgets[li])):
            self._line_widgets[li][i]._cell_ci = i

    def _incremental_insert(self, li, ci, ch, info):
        """Insert one widget into display at (li, ci). O(line_len)."""
        frame = self._make_cell_widget(
            ch, info['phonetic'], info['is_poly'],
            info['options'], li, ci,
            info.get('selected', 'none'))
        self.edit_text.window_create(f'{li + 1}.{ci}', window=frame)
        self._line_widgets[li].insert(ci, frame)
        for i in range(ci + 1, len(self._line_widgets[li])):
            self._line_widgets[li][i]._cell_ci = i

    def _insert_chars(self, text):
        """Single char insert with undo save."""
        self._save_undo()
        ch = text
        can_incr = (ch not in '[]'
                    and not self._line_has_brackets(self.buffer[self.cur_line]))
        self.buffer[self.cur_line].insert(self.cur_col, ch)
        info = self._make_cell_info(ch)
        self.cell_info[self.cur_line].insert(self.cur_col, info)
        if can_incr:
            self._incremental_insert(self.cur_line, self.cur_col, ch, info)
            self.cur_col += 1
            self._update_cursor()
            self._refresh_output()
        else:
            self.cur_col += 1
            self._rebuild_display()
            self._refresh_output()

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
        if self.cur_col > 0 and not self._line_has_brackets(self.buffer[self.cur_line]):
            # Incremental: same-line delete, no brackets
            self.cur_col -= 1
            del self.buffer[self.cur_line][self.cur_col]
            del self.cell_info[self.cur_line][self.cur_col]
            self._incremental_delete(self.cur_line, self.cur_col)
            self._update_cursor()
            self._refresh_output()
        else:
            # Full rebuild: cross-line merge or brackets on line
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
        if self.cur_col < len(line) and not self._line_has_brackets(line):
            # Incremental: same-line delete, no brackets
            del line[self.cur_col]
            del self.cell_info[self.cur_line][self.cur_col]
            self._incremental_delete(self.cur_line, self.cur_col)
            self._update_cursor()
            self._refresh_output()
        else:
            # Full rebuild: cross-line merge or brackets on line
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

        old_frames = [f for line in self._line_widgets for f in line]

        new_line_widgets: List[List[tk.Frame]] = []
        for li, (line_chars, line_info) in enumerate(
                zip(self.buffer, self.cell_info)):
            br = self._find_bracket_ranges(line_chars)
            line_frames: List[tk.Frame] = []
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
            new_line_widgets.append(line_frames)

        self.edit_text.delete('1.0', tk.END)
        for li, line_frames in enumerate(new_line_widgets):
            for frame in line_frames:
                self.edit_text.window_create(tk.END, window=frame)
            if li < len(new_line_widgets) - 1:
                self.edit_text.insert(tk.END, '\n')

        cursor_idx = f'{self.cur_line + 1}.{self.cur_col}'
        self.edit_text.mark_set(tk.INSERT, cursor_idx)
        self.edit_text.see(cursor_idx)

        self._line_widgets = new_line_widgets
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

        frame._cell_li = li
        frame._cell_ci = ci

        if is_poly and options:
            for w in (frame, char_lbl, phon_lbl):
                w.configure(cursor='hand2')
                w.bind('<Button-1>',
                       lambda e, _f=frame: self._on_cell_click(
                           _f._cell_li, _f._cell_ci))
        else:
            for w in (frame, char_lbl, phon_lbl):
                w.bind('<Button-1>',
                       lambda e, _f=frame: self._set_cursor(
                           _f._cell_li, _f._cell_ci + 1))

        return frame

    def _set_cursor(self, line, col):
        self.cur_line = line
        self.cur_col = col
        self._update_cursor()
        self.edit_text.focus_set()

    # ── 注释着色辅助 ─────────────────────────────

    def _create_note_widget(self, parent, note_txt, bg):
        """创建注释控件，《》内文字用独立颜色。"""
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

            # 注释（《》书名号内容着色）
            if note_txt:
                note_w = self._create_note_widget(row, note_txt, row_bg)
                note_w.pack(side=tk.LEFT, fill=tk.X, expand=True)

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
    print('正在更新在线音节数据...')
    download_and_update()
    print('数据更新完成。')

    mapping = load_map_from_json_gz()
    if mapping is None:
        _tmp = tk.Tk()
        _tmp.withdraw()
        messagebox.showerror('错误', '无法加载音节数据。\n请检查网络连接或确保数据文件存在。')
        _tmp.destroy()
        sys.exit(1)
    app = App(mapping)
    app.mainloop()
