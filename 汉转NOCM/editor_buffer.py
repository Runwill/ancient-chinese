"""编辑器缓冲区：文本编辑操作、撤回/重做、光标导航。"""

from constants import MAX_UNDO


class EditorBuffer:
    """管理编辑器的文本缓冲区和撤回/重做栈。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.buffer = [[]]
        self.cell_info = [[]]
        self.cur_line = 0
        self.cur_col = 0
        self.undo_stack = []
        self.redo_stack = []
        self._dirty = False
        self._on_dirty = None  # 回调：脏标记变化时调用

    def set_dirty_callback(self, cb):
        self._on_dirty = cb

    @property
    def dirty(self):
        return self._dirty

    @dirty.setter
    def dirty(self, val):
        self._dirty = val
        if self._on_dirty:
            self._on_dirty()

    # ── 快照与撤回/重做 ──────────────────────────

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

    def save_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        if not self._dirty:
            self.dirty = True

    def undo(self):
        return self._do_undo_redo(self.undo_stack, self.redo_stack)

    def redo(self):
        return self._do_undo_redo(self.redo_stack, self.undo_stack)

    def _do_undo_redo(self, src, dst):
        if not src:
            return False
        dst.append(self._snapshot())
        self._restore_snapshot(src.pop())
        return True

    # ── 单字信息构建 ──────────────────────────────

    def make_cell_info(self, ch):
        opts = self.mapping.get(ch)
        if not opts:
            return {'phonetic': ch, 'options': None, 'is_poly': False,
                    'selected': 'none'}
        first = opts[0]
        phon = first['phonetic'] if isinstance(first, dict) else str(first)
        is_poly = len(opts) > 1
        return {
            'phonetic': phon,
            'options': opts if is_poly else None,
            'is_poly': is_poly,
            'selected': 'none',
        }

    # ── 缓冲区编辑 ────────────────────────────────

    def insert_char(self, ch):
        """插入单个字符（自动 save_undo）。"""
        self.save_undo()
        self.buffer[self.cur_line].insert(self.cur_col, ch)
        self.cell_info[self.cur_line].insert(self.cur_col,
                                             self.make_cell_info(ch))
        self.cur_col += 1

    def insert_chars_raw(self, text):
        """插入原始文本（可含换行），调用前需手动 save_undo。"""
        for ch in text:
            if ch == '\n':
                self._do_newline()
            elif ch == '\r':
                continue
            else:
                self.buffer[self.cur_line].insert(self.cur_col, ch)
                self.cell_info[self.cur_line].insert(
                    self.cur_col, self.make_cell_info(ch))
                self.cur_col += 1

    def _do_newline(self):
        rest = self.buffer[self.cur_line][self.cur_col:]
        rest_info = self.cell_info[self.cur_line][self.cur_col:]
        self.buffer[self.cur_line] = self.buffer[self.cur_line][:self.cur_col]
        self.cell_info[self.cur_line] = self.cell_info[self.cur_line][:self.cur_col]
        self.cur_line += 1
        self.cur_col = 0
        self.buffer.insert(self.cur_line, rest)
        self.cell_info.insert(self.cur_line, rest_info)

    def insert_newline(self):
        self.save_undo()
        self._do_newline()

    def backspace(self):
        if self.cur_col == 0 and self.cur_line == 0:
            return False
        self.save_undo()
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
        return True

    def delete_char(self):
        line = self.buffer[self.cur_line]
        if self.cur_col >= len(line) and self.cur_line >= len(self.buffer) - 1:
            return False
        self.save_undo()
        if self.cur_col < len(line):
            del line[self.cur_col]
            del self.cell_info[self.cur_line][self.cur_col]
        elif self.cur_line < len(self.buffer) - 1:
            line.extend(self.buffer[self.cur_line + 1])
            self.cell_info[self.cur_line].extend(
                self.cell_info[self.cur_line + 1])
            del self.buffer[self.cur_line + 1]
            del self.cell_info[self.cur_line + 1]
        return True

    # ── 光标导航 ──────────────────────────────────

    def handle_nav(self, ks):
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
                self.cur_col = min(self.cur_col,
                                   len(self.buffer[self.cur_line]))
        elif ks == 'Down':
            if self.cur_line < len(self.buffer) - 1:
                self.cur_line += 1
                self.cur_col = min(self.cur_col,
                                   len(self.buffer[self.cur_line]))
        elif ks == 'Home':
            self.cur_col = 0
        elif ks == 'End':
            self.cur_col = len(self.buffer[self.cur_line])

    # ── 工具方法 ──────────────────────────────────

    def copy_raw(self):
        """返回缓冲区纯文本。"""
        return '\n'.join(''.join(ln) for ln in self.buffer)

    def reset(self):
        """重置为空白状态。"""
        self.buffer = [[]]
        self.cell_info = [[]]
        self.cur_line = 0
        self.cur_col = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._dirty = False
