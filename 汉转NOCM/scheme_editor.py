"""Visual editor for PBOC transcription schemes."""

import copy
import tkinter as tk
from tkinter import messagebox

from constants import COLORS
from nocm_phonology import resolve_rule_lookup
from nocm_transcriber import (DEFAULT_SCHEME_ID, list_schemes, load_scheme,
                              normalize_scheme_id, save_scheme)
from widgets import (FlatDropdown, ModernButton, ScrollableFrame,
                     bind_mousewheel, style, style_scrollbar)


MAP_SECTIONS = [
    ('tone', '声调'),
    ('coda', '韵尾'),
    ('nucleus', '元音'),
    ('onset', '声母'),
    ('glide', '韵头'),
    ('residual', '剩余片段'),
]

RULE_SECTIONS = [
    ('pre_normalize', '预处理替换'),
    ('residual_preprocess', '剩余片段预处理'),
    ('residual_replace', '剩余片段替换'),
    ('pharyngeal_relax', '咽化改善'),
    ('syllable_relax', '音节改善'),
    ('post_replace', '合写与改写'),
]

LOOKUP_TEXT_MODE = '文本'
LOOKUP_MAP_MODE = '映射拼接'
LOOKUP_FIELD_LABELS = {
    'target': '输出',
    'source': 'PBOC 项',
}
LOOKUP_FIELD_VALUES = {label: key for key, label in LOOKUP_FIELD_LABELS.items()}
MAP_SECTION_LABELS = {key: label for key, label in MAP_SECTIONS}
MAP_SECTION_VALUES = {label: key for key, label in MAP_SECTIONS}
MAP_TABLE_COLUMNS = [
    (0, 150, 1),
    (1, 150, 1),
    (2, 300, 2),
    (3, 64, 0),
]
RULE_TABLE_COLUMNS = [
    (0, 112, 0),
    (1, 280, 2),
    (2, 62, 0),
    (3, 220, 1),
    (4, 64, 0),
]
MAX_SCHEME_HISTORY = 100
HISTORY_DEBOUNCE_MS = 350


class SchemeEditor(tk.Toplevel):
    """Editable scheme window with per-entry controls."""

    def __init__(self, parent, scheme_id=None, on_saved=None):
        super().__init__(parent)
        self.parent = parent
        self.on_saved = on_saved
        self.scheme = copy.deepcopy(load_scheme(scheme_id or DEFAULT_SCHEME_ID))
        self.entries = {}
        self.option_vars = {}
        self._map_body = None
        self._rule_body = None
        self._history = []
        self._history_index = -1
        self._history_after_id = None
        self._history_restoring = True

        self.title('替换方案编辑')
        self.configure(bg=COLORS['bg_card'])
        self.transient(parent)
        self.geometry('860x680')
        self.minsize(760, 520)

        self._build_ui()
        self._history_restoring = False
        self._bind_history_shortcuts(self)
        self._commit_history()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = self.parent.winfo_x() + max((self.parent.winfo_width() - w) // 2, 0)
        y = self.parent.winfo_y() + max((self.parent.winfo_height() - h) // 2, 0)
        self.geometry(f'+{x}+{y}')

    def _bind_history_shortcuts(self, widget):
        widget.bind('<Control-z>', self._undo)
        widget.bind('<Control-y>', self._redo)
        widget.bind('<Control-Shift-Z>', self._redo)

    def _watch_var(self, var):
        var.trace_add('write', self._schedule_history_snapshot)
        return var

    def _cancel_history_timer(self):
        if self._history_after_id is not None:
            try:
                self.after_cancel(self._history_after_id)
            except tk.TclError:
                pass
            self._history_after_id = None

    def _schedule_history_snapshot(self, *_args):
        if self._history_restoring:
            return
        self._cancel_history_timer()
        self._history_after_id = self.after(
            HISTORY_DEBOUNCE_MS, self._commit_history)

    def _capture_history_state(self):
        map_rows = {}
        for section, _title in MAP_SECTIONS:
            rows = []
            for row, source_var, target_var, label_var in self.entries.get(section, []):
                if row.winfo_exists():
                    rows.append([
                        source_var.get(), target_var.get(), label_var.get()])
            map_rows[section] = rows

        rule_rows = {}
        for section, _title in RULE_SECTIONS:
            rows = []
            for row, lookup_state, new_var in self.entries.get(section, []):
                if row.winfo_exists():
                    rows.append([
                        copy.deepcopy(self._lookup_expr_from_state(lookup_state)),
                        new_var.get(),
                    ])
            rule_rows[section] = rows

        return {
            'scheme': copy.deepcopy(self._collect_scheme()),
            'map_rows': map_rows,
            'rule_rows': rule_rows,
        }

    def _commit_history(self):
        self._cancel_history_timer()
        if self._history_restoring:
            return
        snapshot = self._capture_history_state()
        if (self._history_index >= 0
                and snapshot == self._history[self._history_index]):
            return
        del self._history[self._history_index + 1:]
        self._history.append(snapshot)
        if len(self._history) > MAX_SCHEME_HISTORY:
            del self._history[:-MAX_SCHEME_HISTORY]
        self._history_index = len(self._history) - 1

    def _apply_scheme(self, scheme, map_rows=None, rule_rows=None):
        active_tab = self.tab_var.get() if hasattr(self, 'tab_var') else 'maps'
        was_restoring = self._history_restoring
        self._history_restoring = True
        try:
            self.scheme = copy.deepcopy(scheme)
            self.id_var.set(self.scheme.get('id', DEFAULT_SCHEME_ID))
            self.name_var.set(self.scheme.get('name', ''))
            self.desc_var.set(self.scheme.get('description', ''))
            for key, var in self.option_vars.items():
                var.set(bool(self.scheme.get('options', {}).get(key, False)))
            self._build_maps(map_rows)
            self._build_rules(rule_rows)
            self._show_tab(active_tab)
        finally:
            self._history_restoring = was_restoring

    def _restore_history(self, index):
        self._cancel_history_timer()
        self._history_index = index
        state = self._history[index]
        self._apply_scheme(
            state['scheme'], state['map_rows'], state['rule_rows'])

    def _undo(self, _event=None):
        self._commit_history()
        if self._history_index > 0:
            self._restore_history(self._history_index - 1)
        return 'break'

    def _redo(self, _event=None):
        self._commit_history()
        if self._history_index + 1 < len(self._history):
            self._restore_history(self._history_index + 1)
        return 'break'

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS['bg_card'])
        header.pack(fill=tk.X, padx=18, pady=(16, 10))
        style(header, bg='bg_card')

        title = tk.Label(header, text='替换方案编辑', font=('Microsoft YaHei', 14, 'bold'),
                         bg=COLORS['bg_card'], fg=COLORS['text_primary'])
        title.pack(side=tk.LEFT)
        style(title, bg='bg_card', fg='text_primary')

        ModernButton(header, '另存副本', command=self._clone_current,
                     primary=False, width=82, height=28).pack(side=tk.RIGHT, padx=(8, 0))
        ModernButton(header, '保存方案', command=self._save,
                     primary=True, width=82, height=28).pack(side=tk.RIGHT)

        meta = tk.Frame(self, bg=COLORS['bg_card'])
        meta.pack(fill=tk.X, padx=18, pady=(0, 10))
        style(meta, bg='bg_card')

        self.id_var = self._watch_var(tk.StringVar(
            value=self.scheme.get('id', DEFAULT_SCHEME_ID)))
        self.name_var = self._watch_var(tk.StringVar(
            value=self.scheme.get('name', '')))
        self.desc_var = self._watch_var(tk.StringVar(
            value=self.scheme.get('description', '')))
        self._field(meta, '方案 ID', self.id_var, 0, width=22)
        self._field(meta, '名称', self.name_var, 1, width=24)
        self._field(meta, '说明', self.desc_var, 2, width=40)

        opts = tk.Frame(self, bg=COLORS['bg_card'])
        opts.pack(fill=tk.X, padx=18, pady=(0, 8))
        style(opts, bg='bg_card')
        self._option(opts, 'improve_pharyngeal', '启用咽化改善')
        self._option(opts, 'improve_syllable', '启用音节改善')

        tabs = tk.Frame(self, bg=COLORS['bg_card'])
        tabs.pack(fill=tk.X, padx=18)
        style(tabs, bg='bg_card')
        self.tab_var = tk.StringVar(value='maps')
        self.map_tab = self._tab(tabs, '基础映射', 'maps')
        self.rule_tab = self._tab(tabs, '附加替换', 'rules')

        self.stack = tk.Frame(self, bg=COLORS['bg_card'])
        self.stack.pack(fill=tk.BOTH, expand=True, padx=18, pady=(8, 14))
        style(self.stack, bg='bg_card')

        self.map_page, self.map_frame = self._scroll_page(self.stack)
        self.rule_page, self.rule_frame = self._scroll_page(self.stack)
        self._build_maps()
        self._build_rules()
        self._show_tab('maps')

    def _scroll_page(self, parent):
        page = tk.Frame(parent, bg=COLORS['bg_card'])
        style(page, bg='bg_card')
        sf = ScrollableFrame(page, bg=COLORS['bg_card'])
        sb = tk.Scrollbar(page, orient=tk.VERTICAL, command=sf.canvas.yview)
        style_scrollbar(sb)
        sf.canvas.configure(yscrollcommand=sb.set)
        sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        return page, sf

    def _bind_scroll(self, sf):
        bind_mousewheel(sf.inner, sf.on_mousewheel)
        sf.canvas.bind('<MouseWheel>', sf.on_mousewheel)
        sf.inner.bind('<MouseWheel>', sf.on_mousewheel)

    def _field(self, parent, label, var, col, width=20):
        frame = tk.Frame(parent, bg=COLORS['bg_card'])
        frame.grid(row=0, column=col, sticky='ew', padx=(0, 10))
        parent.grid_columnconfigure(col, weight=1)
        style(frame, bg='bg_card')
        lbl = tk.Label(frame, text=label, font=('Microsoft YaHei', 8),
                       bg=COLORS['bg_card'], fg=COLORS['text_muted'])
        lbl.pack(anchor='w')
        style(lbl, bg='bg_card', fg='text_muted')
        ent = tk.Entry(frame, textvariable=var, width=width,
                       font=('Microsoft YaHei', 9), bg=COLORS['bg_canvas'],
                       fg=COLORS['text_primary'], insertbackground=COLORS['cursor'],
                       relief='flat', highlightthickness=1,
                       highlightbackground=COLORS['border'],
                       highlightcolor=COLORS['accent'])
        ent.pack(fill=tk.X, pady=(3, 0), ipady=4)
        self._bind_history_shortcuts(ent)

    def _option(self, parent, key, label):
        var = self._watch_var(tk.BooleanVar(
            value=bool(self.scheme.get('options', {}).get(key, False))))
        self.option_vars[key] = var

        chip = tk.Label(parent, font=('Microsoft YaHei', 9),
                        padx=10, pady=4, cursor='hand2',
                        highlightthickness=1)

        def _paint():
            if var.get():
                chip.configure(text=f'✓ {label}', bg=COLORS['accent_light'],
                               fg=COLORS['accent'],
                               highlightbackground=COLORS['accent'])
            else:
                chip.configure(text=label, bg=COLORS['bg_card'],
                               fg=COLORS['text_secondary'],
                               highlightbackground=COLORS['border'])

        def _toggle(_event=None):
            var.set(not var.get())
            _paint()

        chip.bind('<Button-1>', _toggle)
        chip.pack(side=tk.LEFT, padx=(0, 10))
        var.trace_add('write', lambda *_args: _paint())
        _paint()

    def _tab(self, parent, label, value):
        widget = tk.Label(parent, text=label, font=('Microsoft YaHei', 9),
                          padx=16, pady=5, cursor='hand2')
        widget.pack(side=tk.LEFT)
        widget.bind('<Button-1>', lambda _e, v=value: self._show_tab(v))
        return widget

    def _show_tab(self, value):
        self.tab_var.set(value)
        for page in (self.map_page, self.rule_page):
            page.pack_forget()
        if value == 'rules':
            self.rule_page.pack(fill=tk.BOTH, expand=True)
            self._bind_scroll(self.rule_frame)
        else:
            self.map_page.pack(fill=tk.BOTH, expand=True)
            self._bind_scroll(self.map_frame)
        self._paint_tabs()

    def _paint_tabs(self):
        active = self.tab_var.get()
        for value, widget in [('maps', self.map_tab), ('rules', self.rule_tab)]:
            if value == active:
                widget.configure(bg=COLORS['accent_light'], fg=COLORS['accent'])
            else:
                widget.configure(bg=COLORS['bg_card'], fg=COLORS['text_secondary'])

    def _clear(self, parent):
        for child in parent.winfo_children():
            child.destroy()

    def _section_header(self, parent, title, on_add=None):
        row = tk.Frame(parent, bg=COLORS['bg_card'])
        row.pack(fill=tk.X, pady=(12, 5))
        style(row, bg='bg_card')
        lbl = tk.Label(row, text=title, font=('Microsoft YaHei', 11, 'bold'),
                       bg=COLORS['bg_card'], fg=COLORS['text_primary'])
        lbl.pack(side=tk.LEFT)
        style(lbl, bg='bg_card', fg='text_primary')
        if on_add:
            ModernButton(row, '新增', command=on_add,
                         primary=False, width=54, height=24).pack(side=tk.RIGHT)

    def _entry(self, parent, value='', width=12):
        var = self._watch_var(tk.StringVar(value=value))
        ent = tk.Entry(parent, textvariable=var, width=width,
                       font=('Cambria', 10), bg=COLORS['bg_canvas'],
                       fg=COLORS['text_primary'], insertbackground=COLORS['cursor'],
                       relief='flat', highlightthickness=1,
                       highlightbackground=COLORS['border'],
                       highlightcolor=COLORS['accent'])
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=3)
        self._bind_history_shortcuts(ent)
        return var

    def _option_menu(self, parent, var, values, command=None, width=12):
        menu = FlatDropdown(parent, var, values, command=command, width=width)
        menu.pack(side=tk.LEFT, padx=(0, 8))
        return menu

    def _table_row(self, parent, columns):
        row = self._row_frame(parent)
        for col, minsize, weight in columns:
            row.grid_columnconfigure(col, minsize=minsize, weight=weight)
        return row

    def _table_header(self, parent, columns, labels):
        row = self._table_row(parent, columns)
        for col, text in labels:
            lbl = tk.Label(row, text=text, anchor='w',
                           font=('Microsoft YaHei', 8),
                           bg=COLORS['bg_card'], fg=COLORS['text_muted'])
            lbl.grid(row=0, column=col, sticky='ew', padx=(0, 8))
            style(lbl, bg='bg_card', fg='text_muted')
        return row

    def _grid_entry(self, parent, col, value='', padx=(0, 8)):
        var = self._watch_var(tk.StringVar(value=value))
        ent = tk.Entry(parent, textvariable=var,
                       font=('Cambria', 10), bg=COLORS['bg_canvas'],
                       fg=COLORS['text_primary'],
                       insertbackground=COLORS['cursor'],
                       relief='flat', highlightthickness=1,
                       highlightbackground=COLORS['border'],
                       highlightcolor=COLORS['accent'])
        ent.grid(row=0, column=col, sticky='ew', padx=padx, ipady=3)
        self._bind_history_shortcuts(ent)
        return var, ent

    def _grid_dropdown(self, parent, col, var, values, command=None, width=12):
        menu = FlatDropdown(parent, var, values, command=command, width=width)
        menu.grid(row=0, column=col, sticky='ew', padx=(0, 8))
        return menu

    def _grid_button(self, parent, col, text, command, primary=False, width=54):
        btn = ModernButton(parent, text, command=command, primary=primary,
                           width=width, height=24)
        btn.grid(row=0, column=col, sticky='ew', padx=(0, 8))
        return btn

    def _delete_row(self, row):
        self._commit_history()
        row.destroy()
        self._commit_history()

    def _split_rule_item(self, item):
        if isinstance(item, dict):
            old = item.get('find', item.get('old', ''))
            new = item.get('replace', item.get('new', ''))
            return old, new
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return item[0], item[1]
        return '', ''

    def _lookup_parts(self, lookup):
        if not isinstance(lookup, dict) or lookup.get('type') != 'map_concat':
            return []
        parts = []
        for part in lookup.get('parts', []):
            if isinstance(part, dict):
                section = str(part.get('section', ''))
                key = str(part.get('key', ''))
            elif isinstance(part, (list, tuple)) and len(part) >= 2:
                section = str(part[0])
                key = str(part[1])
            else:
                continue
            if section and key:
                parts.append([section, key])
        return parts

    def _current_map_sources(self, section):
        sources = []
        for item in self.entries.get(section, []):
            if len(item) < 4:
                continue
            row, source_var, _target_var, _label_var = item
            if row.winfo_exists():
                source = source_var.get().strip()
                if source:
                    sources.append(source)
        if sources:
            return sources
        maps = self.scheme.get('maps', {})
        parse_order = self.scheme.get('parse_order', {})
        order = list(parse_order.get(section, []))
        order.extend(key for key in maps.get(section, {}) if key not in order)
        return order

    def _current_map_value(self, section, key, field='target'):
        if field == 'source':
            return key
        for item in self.entries.get(section, []):
            if len(item) < 4:
                continue
            row, source_var, target_var, _label_var = item
            if row.winfo_exists() and source_var.get().strip() == key:
                return target_var.get()
        return self.scheme.get('maps', {}).get(section, {}).get(key, key)

    def _lookup_expr_from_state(self, state):
        if state['mode_var'].get() != LOOKUP_MAP_MODE:
            return state['text_var'].get()
        return {
            'type': 'map_concat',
            'field': state['field_var'].get(),
            'parts': [[section, key] for section, key in state['parts']
                      if section and key],
        }

    def _lookup_preview(self, state):
        expr = self._lookup_expr_from_state(state)
        scheme = {
            'maps': {
                section: {
                    source: self._current_map_value(section, source)
                    for source in self._current_map_sources(section)
                }
                for section, _title in MAP_SECTIONS
            }
        }
        return resolve_rule_lookup(expr, scheme)

    def _refresh_rule_lookup(self, state):
        if state['mode_var'].get() == LOOKUP_MAP_MODE:
            state['text_var'].set(self._lookup_preview(state))
            state['entry'].configure(state='readonly',
                                     readonlybackground=COLORS['bg_canvas'])
        else:
            state['entry'].configure(state='normal')

    def _edit_lookup_parts(self, state):
        dlg = tk.Toplevel(self)
        dlg.title('选择映射项')
        dlg.resizable(False, False)
        dlg.configure(bg=COLORS['bg_card'])
        dlg.transient(self)
        dlg.grab_set()

        outer = tk.Frame(dlg, bg=COLORS['bg_card'], padx=22, pady=18)
        outer.pack(fill=tk.BOTH, expand=True)
        style(outer, bg='bg_card')

        title = tk.Label(outer, text='映射项拼接', font=('Microsoft YaHei', 12, 'bold'),
                         bg=COLORS['bg_card'], fg=COLORS['text_primary'])
        title.pack(anchor='w')
        style(title, bg='bg_card', fg='text_primary')

        field_row = tk.Frame(outer, bg=COLORS['bg_card'])
        field_row.pack(fill=tk.X, pady=(10, 6))
        style(field_row, bg='bg_card')
        tk.Label(field_row, text='查找取值', font=('Microsoft YaHei', 9),
                 bg=COLORS['bg_card'], fg=COLORS['text_secondary']
                 ).pack(side=tk.LEFT, padx=(0, 8))
        field_label = LOOKUP_FIELD_LABELS.get(state['field_var'].get(), '输出')
        field_var = tk.StringVar(value=field_label)
        self._option_menu(field_row, field_var, LOOKUP_FIELD_VALUES.keys(), width=10)

        body = tk.Frame(outer, bg=COLORS['bg_card'])
        body.pack(fill=tk.X, pady=(4, 8))
        style(body, bg='bg_card')
        part_rows = []

        def _key_options(section):
            return self._current_map_sources(section) or ['']

        def _add_part(section=None, key=None):
            section = section if section in MAP_SECTION_LABELS else MAP_SECTIONS[0][0]
            keys = _key_options(section)
            key = key if key in keys else keys[0]

            row = tk.Frame(body, bg=COLORS['bg_card'])
            row.pack(fill=tk.X, pady=2)
            style(row, bg='bg_card')

            section_var = tk.StringVar(value=MAP_SECTION_LABELS[section])
            key_var = tk.StringVar(value=key)
            key_menu = None

            def _refresh_keys(_value=None):
                selected = MAP_SECTION_VALUES.get(
                    section_var.get(), MAP_SECTIONS[0][0])
                options = _key_options(selected)
                if key_var.get() not in options:
                    key_var.set(options[0])
                key_menu.set_values(options)

            self._option_menu(row, section_var, MAP_SECTION_VALUES.keys(),
                              command=_refresh_keys, width=10)
            key_menu = self._option_menu(row, key_var, keys, width=16)
            ModernButton(row, '删除', command=row.destroy,
                         primary=False, width=54, height=24).pack(side=tk.RIGHT)
            part_rows.append((row, section_var, key_var))

        if state['parts']:
            for section, key in state['parts']:
                _add_part(section, key)
        else:
            _add_part()

        preview_var = tk.StringVar()
        preview = tk.Entry(outer, textvariable=preview_var, width=52,
                           font=('Cambria', 10), bg=COLORS['bg_canvas'],
                           fg=COLORS['text_primary'], relief='flat',
                           highlightthickness=1, highlightbackground=COLORS['border'],
                           readonlybackground=COLORS['bg_canvas'])
        preview.configure(state='readonly')
        preview.pack(fill=tk.X, pady=(0, 10), ipady=3)

        def _collect_parts():
            parts = []
            for row, section_var, key_var in part_rows:
                if not row.winfo_exists():
                    continue
                section = MAP_SECTION_VALUES.get(section_var.get(), '')
                key = key_var.get()
                if section and key:
                    parts.append([section, key])
            return parts

        refresh_id = None

        def _refresh_preview():
            nonlocal refresh_id
            try:
                if not dlg.winfo_exists():
                    return
            except tk.TclError:
                return
            field = LOOKUP_FIELD_VALUES.get(field_var.get(), 'target')
            temp_state = {
                'mode_var': tk.StringVar(value=LOOKUP_MAP_MODE),
                'text_var': tk.StringVar(),
                'field_var': tk.StringVar(value=field),
                'parts': _collect_parts(),
            }
            preview_var.set(self._lookup_preview(temp_state))
            refresh_id = dlg.after(120, _refresh_preview)

        def _close():
            if refresh_id is not None:
                try:
                    dlg.after_cancel(refresh_id)
                except tk.TclError:
                    pass
            dlg.destroy()

        def _ok():
            self._commit_history()
            state['field_var'].set(LOOKUP_FIELD_VALUES.get(field_var.get(), 'target'))
            state['parts'] = _collect_parts()
            state['mode_var'].set(LOOKUP_MAP_MODE)
            self._refresh_rule_lookup(state)
            self._commit_history()
            _close()

        btns = tk.Frame(outer, bg=COLORS['bg_card'])
        btns.pack(fill=tk.X)
        style(btns, bg='bg_card')
        ModernButton(btns, '新增项', command=_add_part,
                     primary=False, width=66, height=26).pack(side=tk.LEFT)
        ModernButton(btns, '取消', command=_close,
                     primary=False, width=60, height=26).pack(side=tk.RIGHT, padx=(8, 0))
        ModernButton(btns, '确定', command=_ok,
                     primary=True, width=60, height=26).pack(side=tk.RIGHT)

        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        x = self.winfo_x() + max((self.winfo_width() - w) // 2, 0)
        y = self.winfo_y() + max((self.winfo_height() - h) // 2, 0)
        dlg.geometry(f'+{x}+{y}')
        dlg.protocol('WM_DELETE_WINDOW', _close)
        _refresh_preview()

    def _row_frame(self, parent):
        row = tk.Frame(parent, bg=COLORS['bg_card'])
        row.pack(fill=tk.X, pady=2)
        style(row, bg='bg_card')
        return row

    def _build_maps(self, history_rows=None):
        self._clear(self.map_frame.inner)
        self.entries = {key: [] for key, _label in MAP_SECTIONS}
        maps = self.scheme.setdefault('maps', {})
        labels = self.scheme.setdefault('labels', {})
        parse_order = self.scheme.setdefault('parse_order', {})
        for key, title in MAP_SECTIONS:
            self._section_header(
                self.map_frame.inner, title,
                on_add=lambda k=key: self._add_map_item(k))
            self._table_header(
                self.map_frame.inner, MAP_TABLE_COLUMNS,
                [(0, 'PBOC 项'), (1, '输出'), (2, '中文说明'), (3, '操作')])
            if history_rows is not None:
                for source, target, label in history_rows.get(key, []):
                    self._map_row(key, source, target, label)
            else:
                order = list(parse_order.get(key, []))
                order.extend(
                    item for item in maps.get(key, {}) if item not in order)
                for source in order:
                    self._map_row(
                        key, source, maps.get(key, {}).get(source, ''),
                        labels.get(key, {}).get(source, ''))
        self._bind_scroll(self.map_frame)

    def _map_row(self, section, source='', target='', label=''):
        row = self._table_row(self.map_frame.inner, MAP_TABLE_COLUMNS)
        source_var, _source_entry = self._grid_entry(row, 0, source)
        target_var, _target_entry = self._grid_entry(row, 1, target)
        label_var, _label_entry = self._grid_entry(row, 2, label)
        self._grid_button(row, 3, '删除', lambda: self._delete_row(row))
        self.entries.setdefault(section, []).append((row, source_var, target_var, label_var))

    def _add_map_item(self, section):
        self._commit_history()
        self._map_row(section)
        self._bind_scroll(self.map_frame)
        self._commit_history()

    def _build_rules(self, history_rows=None):
        self._clear(self.rule_frame.inner)
        rules = self.scheme.setdefault('rules', {})
        for key, title in RULE_SECTIONS:
            self.entries[key] = []
            self._section_header(
                self.rule_frame.inner, title,
                on_add=lambda k=key: self._add_rule_item(k))
            self._table_header(
                self.rule_frame.inner, RULE_TABLE_COLUMNS,
                [(0, '查找方式'), (1, '查找'), (2, '选择'),
                 (3, '替换为'), (4, '操作')])
            items = (history_rows.get(key, []) if history_rows is not None
                     else rules.get(key, []))
            for item in items:
                old, new = self._split_rule_item(item)
                self._rule_row(key, old, new)
        self._bind_scroll(self.rule_frame)

    def _rule_row(self, section, old='', new=''):
        row = self._table_row(self.rule_frame.inner, RULE_TABLE_COLUMNS)
        is_map_lookup = isinstance(old, dict) and old.get('type') == 'map_concat'
        mode_var = self._watch_var(tk.StringVar(
            value=LOOKUP_MAP_MODE if is_map_lookup else LOOKUP_TEXT_MODE))
        field_var = self._watch_var(tk.StringVar(
            value=old.get('field', 'target') if is_map_lookup else 'target'))
        text_var = self._watch_var(tk.StringVar(
            value='' if is_map_lookup else str(old)))
        parts = self._lookup_parts(old)

        self._grid_dropdown(
            row, 0, mode_var, [LOOKUP_TEXT_MODE, LOOKUP_MAP_MODE],
            command=lambda _v: self._refresh_rule_lookup(state),
            width=8)
        _old_var, old_entry = self._grid_entry(row, 1)
        old_entry.configure(textvariable=text_var)
        state = {
            'mode_var': mode_var,
            'text_var': text_var,
            'field_var': field_var,
            'parts': parts,
            'entry': old_entry,
        }
        self._grid_button(row, 2, '选择',
                          lambda: self._edit_lookup_parts(state))
        new_var, _new_entry = self._grid_entry(row, 3, new)
        self._grid_button(row, 4, '删除', lambda: self._delete_row(row))
        self._refresh_rule_lookup(state)
        self.entries.setdefault(section, []).append((row, state, new_var))

    def _add_rule_item(self, section):
        self._commit_history()
        self._rule_row(section)
        self._bind_scroll(self.rule_frame)
        self._commit_history()

    def _collect_scheme(self):
        scheme = copy.deepcopy(self.scheme)
        scheme['id'] = self.id_var.get().strip()
        scheme['name'] = self.name_var.get().strip() or scheme['id']
        scheme['description'] = self.desc_var.get().strip()
        scheme['options'] = dict(scheme.get('options', {}))
        for key, var in self.option_vars.items():
            scheme['options'][key] = bool(var.get())

        scheme['maps'] = {}
        scheme['labels'] = {}
        scheme['parse_order'] = {}
        for section, _title in MAP_SECTIONS:
            section_map = {}
            section_labels = {}
            order = []
            for row, source_var, target_var, label_var in self.entries.get(section, []):
                if not row.winfo_exists():
                    continue
                source = source_var.get().strip()
                if not source:
                    continue
                section_map[source] = target_var.get()
                label = label_var.get().strip()
                if label:
                    section_labels[source] = label
                order.append(source)
            scheme['maps'][section] = section_map
            if section_labels:
                scheme['labels'][section] = section_labels
            if order:
                scheme['parse_order'][section] = order

        scheme['rules'] = {}
        for section, _title in RULE_SECTIONS:
            pairs = []
            for row, lookup_state, new_var in self.entries.get(section, []):
                if not row.winfo_exists():
                    continue
                old = self._lookup_expr_from_state(lookup_state)
                if lookup_state['mode_var'].get() == LOOKUP_MAP_MODE:
                    if not old.get('parts') or self._lookup_preview(lookup_state) == '':
                        continue
                elif old == '':
                    continue
                pairs.append([old, new_var.get()])
            scheme['rules'][section] = pairs
        return scheme

    def _save(self):
        self._commit_history()
        scheme = self._collect_scheme()
        try:
            scheme_id = save_scheme(scheme, scheme.get('id'))
        except Exception as exc:
            messagebox.showerror('保存失败', str(exc), parent=self)
            return
        self.scheme = copy.deepcopy(load_scheme(scheme_id))
        self.id_var.set(scheme_id)
        self._commit_history()
        messagebox.showinfo('已保存', f'方案已保存为 {scheme_id}.json', parent=self)
        if self.on_saved:
            self.on_saved(scheme_id)

    def _clone_current(self):
        self._commit_history()
        scheme = self._collect_scheme()
        source_id = normalize_scheme_id(
            scheme.get('id') or DEFAULT_SCHEME_ID)
        base_id = normalize_scheme_id(f'{source_id}_copy')
        existing_ids = {item['id'] for item in list_schemes()}
        target_id = base_id
        suffix = 2
        while target_id in existing_ids:
            target_id = f'{base_id}_{suffix}'
            suffix += 1

        source_name = scheme.get('name') or source_id
        scheme['id'] = target_id
        scheme['name'] = f'{source_name} 副本'
        self._apply_scheme(scheme)
        self._commit_history()
