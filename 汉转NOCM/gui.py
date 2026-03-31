"""GUI 模块：汉字转 NOCM 音标的可视化编辑器（现代化 UI）。"""

import os
import sys
import tkinter as tk
import tkinter.font as tkFont
from tkinter import messagebox
from typing import Optional

from constants import COLORS, _CANVAS_MARGIN, find_bracket_ranges, in_bracket, set_theme, get_theme
from widgets import ModernButton, freeze_redraw, thaw_redraw
from editor_buffer import EditorBuffer
from editor_render import EditorRenderer
from draft_io import save_draft, load_draft, delete_draft, rename_draft, get_draft_name
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

        self._build_ui()

    # ── 构建界面 ──────────────────────────────────

    def _build_ui(self):
        # 主容器 — 无额外 padding，贴边布局
        main = tk.Frame(self, bg=COLORS['bg_main'])
        main.pack(fill=tk.BOTH, expand=True)

        # ── 顶部工具栏（紧凑型） ──
        toolbar = tk.Frame(main, bg=COLORS['bg_card'], height=52)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)

        toolbar_inner = tk.Frame(toolbar, bg=COLORS['bg_card'])
        toolbar_inner.pack(fill=tk.BOTH, expand=True, padx=20)

        # 左侧标题 + 副标题
        title_area = tk.Frame(toolbar_inner, bg=COLORS['bg_card'])
        title_area.pack(side=tk.LEFT, fill=tk.Y)

        title_row = tk.Frame(title_area, bg=COLORS['bg_card'])
        title_row.pack(expand=True)

        tk.Label(title_row, text='汉字转 NOCM 音标',
                font=('Microsoft YaHei', 13, 'bold'),
                bg=COLORS['bg_card'], fg=COLORS['text_primary']).pack(side=tk.LEFT)
        self._subtitle_lbl = tk.Label(title_row, text='  输入即注音 · 点击彩色字修改读音',
                font=('Microsoft YaHei', 9),
                bg=COLORS['bg_card'], fg=COLORS['text_muted'])
        self._subtitle_lbl.pack(side=tk.LEFT, pady=(3, 0))

        # 右侧按钮组
        btn_area = tk.Frame(toolbar_inner, bg=COLORS['bg_card'])
        btn_area.pack(side=tk.RIGHT, fill=tk.Y)
        btn_row = tk.Frame(btn_area, bg=COLORS['bg_card'])
        btn_row.pack(expand=True)

        theme_label = '☀' if get_theme() == 'dark' else '☾'
        for text, cmd, pri in [('?', self._on_help, False),
                               ('重启', self._on_restart, False),
                               (theme_label, self._on_toggle_theme, False),
                               ('清空', self._on_clear, False),
                               ('保存', self._on_save, False),
                               ('复制结果', self._on_copy, True)]:
            w = 32 if len(text) <= 1 else 64 if len(text) <= 2 else 72
            ModernButton(btn_row, text, command=cmd,
                        primary=pri, width=w, height=30).pack(
                side=tk.LEFT, padx=(0, 6))

        # 工具栏底部分隔线
        tk.Frame(main, bg=COLORS['divider'], height=1).pack(fill=tk.X)

        # ── 主内容区（三栏布局） ──
        content = tk.Frame(main, bg=COLORS['bg_main'])
        content.pack(fill=tk.BOTH, expand=True)

        # ── 左侧边栏（文稿管理面板） ──
        self.left_sidebar = tk.Frame(content, bg=COLORS['bg_sidebar'], width=240)
        self.left_sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.left_sidebar.pack_propagate(False)
        # 右边分割线
        tk.Frame(content, bg=COLORS['divider'], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # 编辑区（无边框，直接铺满中间）
        edit_area = tk.Frame(content, bg=COLORS['bg_canvas'])
        edit_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(edit_area, bg=COLORS['bg_canvas'],
                                highlightthickness=0,
                                yscrollincrement=20)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 右侧分割线
        tk.Frame(content, bg=COLORS['divider'], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # ── 右侧边栏（音标选择面板） ──
        self.sidebar = tk.Frame(content, bg=COLORS['bg_sidebar'], width=260)
        self.sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        
        sidebar_options.build_placeholder(self.sidebar)

        # 初始构建文稿列表
        self._build_sidebar_drafts()

        # 字体与渲染器
        self._char_font = tkFont.Font(family='Microsoft YaHei', size=14)
        self._phon_font = tkFont.Font(family='Consolas', size=10)
        self.renderer = EditorRenderer(self.canvas, self._char_font, self._phon_font)

        self.canvas.bind('<Key>', self._on_key)
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Configure>', self._on_configure)
        self.canvas.focus_set()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
    
    # ── 便捷委托 ──────────────────────────────────

    def _rebuild_display(self):
        self.renderer.rebuild(self.buf.buffer, self.buf.cell_info)
        self.renderer.update_cursor(self.buf.cur_line, self.buf.cur_col)
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

    # ── 键盘处理 ──────────────────────────────────

    def _on_key(self, event):
        ctrl = bool(event.state & 0x4)
        if ctrl:
            _acts = {'v': self._on_paste, 'c': self._copy_raw,
                     'y': lambda: (self.buf.redo() and self._rebuild_display()),
                     's': self._on_save}
            k = event.keysym.lower()
            if k == 'z':
                fn = self.buf.redo if event.state & 0x1 else self.buf.undo
                if fn():
                    self._rebuild_display()
            elif k in _acts:
                _acts[k]()
        else:
            ks = event.keysym
            if ks == 'BackSpace':
                if self.buf.backspace():
                    self._rebuild_display()
            elif ks == 'Delete':
                if self.buf.delete_char():
                    self._rebuild_display()
            elif ks == 'Return':
                self.buf.insert_newline()
                self._rebuild_display()
            elif ks in ('Left', 'Right', 'Up', 'Down', 'Home', 'End'):
                self.buf.handle_nav(ks)
                self._update_cursor()
            elif event.char and len(event.char) == 1 and event.char.isprintable():
                self.buf.insert_char(event.char)
                self._rebuild_display()
        return 'break'

    def _on_paste(self, event=None):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return 'break'
        if text:
            self.buf.save_undo()
            self.buf.insert_chars_raw(text)
            self._rebuild_display()
        return 'break'

    def _on_canvas_click(self, event):
        self.canvas.focus_set()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        for li, line_rects in enumerate(self.renderer.cell_rects):
            for ci, (x1, y1, x2, y2) in enumerate(line_rects):
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    info = self.buf.cell_info[li][ci]
                    br = find_bracket_ranges(self.buf.buffer[li])
                    if info['is_poly'] and info['options'] and not in_bracket(ci, br):
                        self._on_cell_click(li, ci)
                        return
                    self.buf.cur_line = li
                    self.buf.cur_col = min(ci + 1, len(self.buf.buffer[li]))
                    self._update_cursor()
                    return
        best_li = 0
        for i, ly in enumerate(self.renderer.line_y):
            if cy >= ly:
                best_li = i
        best_li = min(best_li, len(self.buf.buffer) - 1)
        self.buf.cur_line = best_li
        self.buf.cur_col = len(self.buf.buffer[best_li])
        self._update_cursor()

    def _on_mousewheel(self, event):
        if event.delta > 0 and self.canvas.yview()[0] <= 0:
            return
        self.canvas.yview_scroll(-event.delta // 40, 'units')

    def _on_configure(self, event):
        self.renderer.on_configure(event, self.buf.buffer, self.buf.cell_info,
                                   self.buf.cur_line, self.buf.cur_col)

    def _copy_raw(self):
        raw = self.buf.copy_raw()
        if raw:
            self.clipboard_clear()
            self.clipboard_append(raw)

    # ── 点击多音字显示侧边栏选项 ────────────────────────

    def _on_cell_click(self, li, ci):
        """点击多音字时，在侧边栏显示选项"""
        info = self.buf.cell_info[li][ci]
        opts = info['options']
        if not opts:
            return

        self.buf.cur_line = li
        self.buf.cur_col = ci + 1
        self._selected_poly = (li, ci)
        sidebar_options.build_options(
            self.sidebar, li, ci, self.buf.buffer[li][ci], info,
            self.buf.buffer, on_apply=self._apply_reading)
        self._update_cursor()

    def _apply_reading(self, li, ci, phonetic, global_apply):
        """应用选中的读音"""
        self.after(20, lambda: self._do_apply(li, ci, phonetic, global_apply))

    def _do_apply(self, li, ci, phonetic, global_apply):
        self.buf.save_undo()
        if global_apply:
            # 将上次的紫色（global_recent）降级为蓝色（global）
            for linfo in self.buf.cell_info:
                for info in linfo:
                    if info.get('selected') == 'global_recent':
                        info['selected'] = 'global'
            ch = self.buf.buffer[li][ci]
            for _li, (lc, linfo) in enumerate(zip(self.buf.buffer, self.buf.cell_info)):
                for _ci, (c, info) in enumerate(zip(lc, linfo)):
                    if c == ch and info['is_poly']:
                        info['phonetic'] = phonetic
                        if _li == li and _ci == ci:
                            info['selected'] = 'manual'
                        else:
                            info['selected'] = 'global_recent'
        else:
            self.buf.cell_info[li][ci]['phonetic'] = phonetic
            self.buf.cell_info[li][ci]['selected'] = 'manual'
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

    def _on_help(self):
        messagebox.showinfo('帮助', (
            '使用说明：\n\n'
            '1. 直接在编辑区输入或粘贴汉字文本\n'
            '2. 每个字实时显示注音\n'
            '3. 多音字颜色含义：\n'
            '   · 橙色 = 未手动选择读音\n'
            '   · 绿色 = 已手动选择读音\n'
            '   · 蓝色 = 通过「全局应用」间接选择\n'
            '   · 紫色 = 上一次「全局应用」间接选择\n'
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
        """切换深色/浅色主题并重建整个界面。"""
        new = 'light' if get_theme() == 'dark' else 'dark'
        set_theme(new)
        freeze_redraw(self)
        try:
            # 销毁旧 UI
            for w in self.winfo_children():
                w.destroy()
            self.configure(bg=COLORS['bg_main'])
            # 重建
            self._build_ui()
            self._rebuild_display()
            self._update_title()
        finally:
            thaw_redraw(self)

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
