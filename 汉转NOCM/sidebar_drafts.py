"""侧边栏：文稿管理面板（含文件夹嵌套与拖拽移动）。"""

import tkinter as tk
from datetime import datetime

from constants import COLORS
from widgets import (ModernButton, ScrollableFrame,
                     bind_hover, bind_mousewheel)
import draft_manager


# ── 模块级拖拽状态 ────────────────────────────────────

_drag = {
    'active': False,
    'type': None,              # 'draft' | 'folder'
    'src_id': None,            # filename 或 group_id
    'src_group': None,         # 所在父文件夹 id（None=顶层）
    'src_widget': None,
    'start_y': 0,
    'folder_hdrs': {},         # {group_id: hdr_widget}
    'folder_zones': {},        # {group_id: wrapper_frame}  整块区域
    'root_zone': None,         # "未分组"区域 widget
    'hl_id': None,             # 当前高亮目标 group_id 或 '__root__'
    'hl_bar': None,            # 当前高亮指示条 widget
    'insert_line': None,       # 插入位置指示线 widget
    'insert_target': None,     # (group_id, before_filename) 或 None
    'card_widgets': [],        # [(widget, filename, group_id), ...]
    'folder_widgets': [],      # [(zone_widget, group_id, parent_gid), ...]
    'sidebar': None,
    'on_rebuild': None,
    'current_draft': None,
}


# ── 公开接口 ──────────────────────────────────────────


def build(sidebar, current_draft, on_load, on_new, on_delete, on_rename,
          on_rebuild=None):
    """构建左侧文稿列表。"""
    for w in sidebar.winfo_children():
        w.destroy()

    _drag.update({
        'active': False, 'folder_hdrs': {}, 'folder_zones': {},
        'root_zone': None, 'hl_id': None, 'hl_bar': None,
        'insert_line': None, 'insert_target': None,
        'card_widgets': [], 'folder_widgets': [],
        'sidebar': sidebar, 'on_rebuild': on_rebuild,
        'current_draft': current_draft,
    })

    # 按钮行
    btn_row = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16)
    btn_row.pack(fill=tk.X, pady=(10, 10))

    nb = tk.Label(btn_row, text='📄＋', font=('Microsoft YaHei', 9),
                  bg=COLORS['accent_light'], fg=COLORS['accent'],
                  padx=6, pady=3, cursor='hand2')
    nb.pack(side=tk.LEFT)
    nb.bind('<Button-1>', lambda e: on_new())
    nb.bind('<Enter>', lambda e: nb.configure(bg=COLORS['border']))
    nb.bind('<Leave>', lambda e: nb.configure(bg=COLORS['accent_light']))

    fb = tk.Label(btn_row, text='📁＋', font=('Microsoft YaHei', 9),
                  bg=COLORS['accent_light'], fg=COLORS['accent'],
                  padx=6, pady=3, cursor='hand2')
    fb.pack(side=tk.LEFT, padx=(6, 0))
    fb.bind('<Button-1>', lambda e: _do_create_folder(on_rebuild))
    fb.bind('<Enter>', lambda e: fb.configure(bg=COLORS['border']))
    fb.bind('<Leave>', lambda e: fb.configure(bg=COLORS['accent_light']))

    tk.Frame(sidebar, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16)

    # 滚动列表
    sf = ScrollableFrame(sidebar, bg=COLORS['bg_sidebar'])
    sf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    groups = draft_manager.get_groups()
    all_drafts = draft_manager.list_drafts()
    drafts_map = {d['filename']: d for d in all_drafts}
    grouped_fns = draft_manager.get_grouped_filenames(groups)
    ungrouped = [d for d in all_drafts if d['filename'] not in grouped_fns]

    # 递归渲染文件夹树
    _render_tree(sf.inner, groups, drafts_map, current_draft,
                 on_load, on_delete, on_rename, on_rebuild,
                 sf.on_mousewheel, depth=0, parent_gid=None)

    if not groups and not ungrouped:
        _build_empty(sf.inner)
    else:
        # "未分组" 拖放区域
        if groups:
            rz = tk.Frame(sf.inner, bg=COLORS['bg_sidebar'], pady=4)
            rz.pack(fill=tk.X, padx=8)
            tk.Label(rz, text='─  未分组  ─',
                     font=('Microsoft YaHei', 8),
                     bg=COLORS['bg_sidebar'], fg=COLORS['text_muted']
                     ).pack()
            _drag['root_zone'] = rz
            rz.bind('<MouseWheel>', sf.on_mousewheel)
            for ch in rz.winfo_children():
                ch.bind('<MouseWheel>', sf.on_mousewheel)

        for d in ungrouped:
            _build_card(sf.inner, d, current_draft, None,
                        on_load, on_delete, on_rename,
                        sf.on_mousewheel, on_rebuild, depth=0)

    sf.canvas.bind('<MouseWheel>', sf.on_mousewheel)


def show_rename_dialog(parent_win, filename, old_name, on_done):
    """显示重命名文稿对话框。"""
    _show_name_dialog(parent_win, '重命名文稿', '文稿名称：', old_name,
                      lambda n: draft_manager.rename_draft(filename, n), on_done)


def show_rename_folder_dialog(parent_win, group_id, old_name, on_done):
    """显示重命名文件夹对话框。"""
    _show_name_dialog(parent_win, '重命名文件夹', '文件夹名称：', old_name,
                      lambda n: draft_manager.rename_group(group_id, n), on_done)


# ── 对话框 ────────────────────────────────────────────


def _show_name_dialog(parent_win, title, label, old_name, do_rename, on_done):
    dlg = tk.Toplevel(parent_win)
    dlg.title(title)
    dlg.resizable(False, False)
    dlg.configure(bg=COLORS['bg_card'])
    dlg.grab_set()

    fr = tk.Frame(dlg, bg=COLORS['bg_card'], padx=24, pady=20)
    fr.pack()
    tk.Label(fr, text=label, font=('Microsoft YaHei', 10),
             bg=COLORS['bg_card'], fg=COLORS['text_primary']).pack(anchor='w')
    entry = tk.Entry(fr, font=('Microsoft YaHei', 11), width=28,
                     highlightthickness=1,
                     highlightbackground=COLORS['border'],
                     highlightcolor=COLORS['accent'])
    entry.pack(pady=(6, 12), ipady=4)
    entry.insert(0, old_name)
    entry.select_range(0, tk.END)
    entry.focus_set()

    def _ok():
        n = entry.get().strip()
        if n and n != old_name:
            do_rename(n)
        dlg.destroy()
        on_done()

    row = tk.Frame(fr, bg=COLORS['bg_card'])
    row.pack()
    ModernButton(row, '取消', command=dlg.destroy,
                 primary=False, width=72).pack(side=tk.LEFT, padx=(0, 8))
    ModernButton(row, '确定', command=_ok,
                 primary=True, width=72).pack(side=tk.LEFT)

    entry.bind('<Return>', lambda e: _ok())
    entry.bind('<Escape>', lambda e: dlg.destroy())

    dlg.update_idletasks()
    w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    x = parent_win.winfo_x() + (parent_win.winfo_width() - w) // 2
    y = parent_win.winfo_y() + (parent_win.winfo_height() - h) // 2
    dlg.geometry(f'+{x}+{y}')


# ── 内部构建 ──────────────────────────────────────────


def _do_create_folder(on_rebuild):
    draft_manager.create_group()
    if on_rebuild:
        on_rebuild()


def _build_empty(parent):
    box = tk.Frame(parent, bg=COLORS['bg_sidebar'])
    box.pack(fill=tk.BOTH, expand=True, pady=40)
    tk.Label(box, text='📭', font=('Segoe UI Emoji', 28),
             bg=COLORS['bg_sidebar']).pack()
    tk.Label(box, text='暂无文稿\n点击「保存」保存当前内容',
             font=('Microsoft YaHei', 10),
             bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
             justify='center').pack(pady=(10, 0))


def _do_delete_folder(gid, name, parent_widget, on_rebuild):
    from tkinter import messagebox
    if messagebox.askyesno('确认删除', f'确定要删除文件夹「{name}」吗？\n'
                           '（文稿和子文件夹不会被删除）'):
        draft_manager.delete_group(gid)
        if on_rebuild:
            parent_widget.after(1, on_rebuild)


def _render_tree(parent, groups, drafts_map, current_draft,
                 on_load, on_delete, on_rename, on_rebuild,
                 mw_handler, depth, parent_gid):
    """递归渲染文件夹树。"""
    for g in groups:
        _build_folder(parent, g, drafts_map, current_draft,
                      on_load, on_delete, on_rename, on_rebuild,
                      mw_handler, depth, parent_gid)


def _build_folder(parent, group, drafts_map, current_draft,
                  on_load, on_delete, on_rename, on_rebuild,
                  mw_handler, depth, parent_gid):
    """构建单个文件夹（头部 + 子内容）。"""
    gid = group['id']
    expanded = group.get('expanded', True)
    left_pad = 6 + depth * 16

    # 整块文件夹区域（用于拖放命中检测）
    zone = tk.Frame(parent, bg=COLORS['bg_sidebar'])
    zone.pack(fill=tk.X)
    _drag['folder_zones'][gid] = zone
    _drag['folder_widgets'].append((zone, gid, parent_gid))

    # ── 文件夹头部 ──
    hdr = tk.Frame(zone, bg=COLORS['bg_sidebar'], padx=left_pad, pady=6)
    hdr.pack(fill=tk.X, pady=(4, 0), padx=6)
    _drag['folder_hdrs'][gid] = hdr

    # 拖拽手柄
    handle = tk.Label(hdr, text='⣿', font=('Segoe UI Symbol', 9),
                      bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
                      cursor='fleur')
    handle.pack(side=tk.LEFT, padx=(0, 4))
    handle.bind('<Button-1>',
                lambda e, g=gid, pg=parent_gid: _start_drag(
                    'folder', g, pg, hdr, e.y_root))
    handle.bind('<B1-Motion>', _on_drag_move)
    handle.bind('<ButtonRelease-1>', _on_drag_end)

    arrow = '▼' if expanded else '▶'
    arrow_lbl = tk.Label(hdr, text=arrow, font=('Microsoft YaHei', 8),
                         bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
                         cursor='hand2')
    arrow_lbl.pack(side=tk.LEFT, padx=(0, 2))

    icon_lbl = tk.Label(hdr, text='📁', font=('Segoe UI Emoji', 11),
                        bg=COLORS['bg_sidebar'], cursor='hand2')
    icon_lbl.pack(side=tk.LEFT, padx=(0, 4))

    name_lbl = tk.Label(hdr, text=group['name'],
                        font=('Microsoft YaHei', 10, 'bold'),
                        bg=COLORS['bg_sidebar'], fg=COLORS['text_primary'],
                        anchor='w', cursor='hand2')
    name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # 递归计数
    def _count(g):
        n = len([f for f in g['files'] if f in drafts_map])
        for ch in g.get('children', []):
            n += _count(ch)
        return n

    tk.Label(hdr, text=str(_count(group)), font=('Microsoft YaHei', 8),
             bg=COLORS['bg_sidebar'], fg=COLORS['text_muted']
             ).pack(side=tk.RIGHT, padx=(0, 4))

    del_lbl = tk.Label(hdr, text='✕', font=('Microsoft YaHei', 9),
                       bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
                       cursor='hand2')
    del_lbl.pack(side=tk.RIGHT, padx=(4, 0))
    del_lbl.bind('<Button-1>', lambda e: _do_delete_folder(
        gid, group['name'], hdr, on_rebuild))
    del_lbl.bind('<Enter>', lambda e: del_lbl.configure(fg='#EF4444'))
    del_lbl.bind('<Leave>', lambda e: del_lbl.configure(
        fg=COLORS['text_muted']))

    # 箭头/图标：单击立即切换；名称：单击切换，双击重命名
    def _toggle(e=None):
        draft_manager.toggle_group(gid)
        if on_rebuild:
            on_rebuild()

    for w in (arrow_lbl, icon_lbl):
        w.bind('<Button-1>', _toggle)

    _timer = [None]

    def _name_single(e):
        if _timer[0]:
            e.widget.after_cancel(_timer[0])
        _timer[0] = e.widget.after(250, _toggle)

    def _name_double(e):
        if _timer[0]:
            e.widget.after_cancel(_timer[0])
            _timer[0] = None
        top = hdr.winfo_toplevel()
        show_rename_folder_dialog(top, gid, group['name'],
                                  on_rebuild or (lambda: None))

    name_lbl.bind('<Button-1>', _name_single)
    name_lbl.bind('<Double-Button-1>', _name_double)

    # Hover（非拖拽时）
    def _hdr_enter(e):
        if not _drag['active']:
            _set_hdr_bg(hdr, COLORS['border_light'])

    def _hdr_leave(e):
        if not _drag['active'] or _drag.get('hl_id') != gid:
            _set_hdr_bg(hdr, COLORS['bg_sidebar'])

    hdr.bind('<Enter>', _hdr_enter)
    hdr.bind('<Leave>', _hdr_leave)
    hdr.bind('<MouseWheel>', mw_handler)
    for ch in hdr.winfo_children():
        ch.bind('<MouseWheel>', mw_handler)

    tk.Frame(zone, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16)

    if not expanded:
        return

    # ── 文件夹内容 ──
    container = tk.Frame(zone, bg=COLORS['bg_sidebar'])
    container.pack(fill=tk.X)

    # 子文件夹（递归）
    _render_tree(container, group.get('children', []), drafts_map,
                 current_draft, on_load, on_delete, on_rename,
                 on_rebuild, mw_handler, depth + 1, parent_gid=gid)

    # 文件
    has_content = bool(group.get('children'))
    for fn in group['files']:
        if fn in drafts_map:
            has_content = True
            _build_card(container, drafts_map[fn], current_draft, gid,
                        on_load, on_delete, on_rename,
                        mw_handler, on_rebuild, depth + 1)

    if not has_content:
        tip = tk.Label(container, text='（空文件夹）',
                       font=('Microsoft YaHei', 9),
                       bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'])
        tip.pack(pady=6, padx=(6 + (depth + 1) * 16, 6))
        tip.bind('<MouseWheel>', mw_handler)


def _build_card(parent, draft, current_draft, group_id,
                on_load, on_delete, on_rename,
                mw_handler, on_rebuild, depth):
    """构建单个文稿卡片。"""
    fn = draft['filename']
    active = fn == current_draft
    bg = COLORS['accent_light'] if active else COLORS['bg_card']
    bdr = COLORS['accent'] if active else COLORS['border']
    left_pad = 6 + depth * 16

    card = tk.Frame(parent, bg=bg, highlightbackground=bdr,
                    highlightthickness=1, padx=8, pady=10)
    card.pack(fill=tk.X, pady=3, padx=(left_pad, 6))

    top = tk.Frame(card, bg=bg)
    top.pack(fill=tk.X)

    # 拖拽手柄
    handle = tk.Label(top, text='⣿', font=('Segoe UI Symbol', 10),
                      bg=bg, fg=COLORS['text_muted'], cursor='fleur')
    handle.pack(side=tk.LEFT, padx=(0, 6))
    handle.bind('<Button-1>',
                lambda e, f=fn, g=group_id: _start_drag(
                    'draft', f, g, card, e.y_root))
    handle.bind('<B1-Motion>', _on_drag_move)
    handle.bind('<ButtonRelease-1>', _on_drag_end)

    name_lbl = tk.Label(top, text=draft['name'],
                        font=('Microsoft YaHei', 11, 'bold'),
                        bg=bg, fg=COLORS['text_primary'],
                        anchor='w', cursor='hand2')
    name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

    bot = tk.Frame(card, bg=bg)
    bot.pack(fill=tk.X, pady=(4, 0))

    mod = ''
    if draft['modified']:
        try:
            mod = datetime.fromisoformat(
                draft['modified']).strftime('%m/%d %H:%M')
        except (ValueError, TypeError):
            pass
    tk.Label(bot, text=mod, font=('Microsoft YaHei', 8),
             bg=bg, fg=COLORS['text_muted']).pack(side=tk.LEFT)

    db = tk.Label(bot, text='删除', font=('Microsoft YaHei', 8),
                  bg=bg, fg='#EF4444', cursor='hand2')
    db.pack(side=tk.RIGHT, padx=(6, 0))
    db.bind('<Button-1>', lambda e: on_delete(fn, draft['name']))
    db.bind('<Enter>', lambda e: db.configure(fg='#DC2626'))
    db.bind('<Leave>', lambda e: db.configure(fg='#EF4444'))

    # 单击加载 / 双击重命名
    _timer = [None]

    def _single(e):
        if _timer[0]:
            e.widget.after_cancel(_timer[0])
        _timer[0] = e.widget.after(300, lambda: on_load(fn))

    def _double(e):
        if _timer[0]:
            e.widget.after_cancel(_timer[0])
            _timer[0] = None
        on_rename(fn, draft['name'])

    name_lbl.bind('<Button-1>', _single)
    name_lbl.bind('<Double-Button-1>', _double)

    lh = lambda e: on_load(fn)
    card.bind('<Button-1>', lh)
    bot.bind('<Button-1>', lh)
    top.bind('<Button-1>', lh)
    for ch in bot.winfo_children():
        if ch != db:
            ch.bind('<Button-1>', lh)

    if not active:
        bind_hover(card, bg)
    bind_mousewheel(card, mw_handler)

    # 注册卡片供拖拽排序使用
    _drag['card_widgets'].append((card, fn, group_id))


# ── 拖拽系统 ─────────────────────────────────────────


def _set_hdr_bg(widget, bg):
    """设置文件夹头部及其子控件的背景色。"""
    try:
        widget.configure(bg=bg)
        for ch in widget.winfo_children():
            try:
                ch.configure(bg=bg)
            except tk.TclError:
                pass
    except tk.TclError:
        pass


def _start_drag(dtype, src_id, src_group, widget, y_root):
    """开始拖拽。"""
    _drag['active'] = True
    _drag['type'] = dtype
    _drag['src_id'] = src_id
    _drag['src_group'] = src_group
    _drag['src_widget'] = widget
    _drag['start_y'] = y_root
    _drag['hl_id'] = None
    _drag['hl_bar'] = None
    try:
        if dtype == 'draft':
            widget.configure(highlightbackground=COLORS['accent'])
            # 半透明效果：降低子控件前景色
            for ch in widget.winfo_children():
                _dim_widget(ch, True)
        else:
            _set_hdr_bg(widget, COLORS['accent_light'])
            for ch in widget.winfo_children():
                _dim_widget(ch, True)
    except tk.TclError:
        pass


def _on_drag_move(event):
    """拖拽移动 — 检测卡片插入位置或文件夹目标。"""
    if not _drag['active']:
        return
    y = event.y_root

    # ── 1. 优先检测同级插入位置 ──
    if _drag['type'] == 'draft':
        best_insert = _find_insert_position(y)
    elif _drag['type'] == 'folder':
        best_insert = _find_folder_insert_position(y)
    else:
        best_insert = None

    if best_insert is not None:
        _show_insert_at(best_insert)
        if _drag['hl_id'] is not None:
            _clear_folder_highlight()
        return

    # 清除插入线
    _remove_insert_line()
    _drag['insert_target'] = None

    # ── 2. 检测文件夹目标（仅限拖入文件夹） ──
    target = None
    best_h = float('inf')
    for gid, zone in _drag['folder_zones'].items():
        if _drag['type'] == 'folder' and gid == _drag['src_id']:
            continue
        try:
            zy = zone.winfo_rooty()
            zh = zone.winfo_height()
            if zy <= y <= zy + zh and zh < best_h:
                target = gid
                best_h = zh
        except tk.TclError:
            continue

    # 检查"未分组"区域
    if target is None and _drag['src_group'] is not None:
        rz = _drag.get('root_zone')
        if rz:
            try:
                ry = rz.winfo_rooty()
                rh = rz.winfo_height()
                if ry - 10 <= y <= ry + rh + 10:
                    target = '__root__'
            except tk.TclError:
                pass

    # 更新文件夹高亮
    old = _drag['hl_id']
    if target == old:
        return

    # 清除旧高亮
    _remove_hl_bar()
    if old and old != '__root__' and old in _drag['folder_hdrs']:
        _set_hdr_bg(_drag['folder_hdrs'][old], COLORS['bg_sidebar'])
    elif old == '__root__':
        rz = _drag.get('root_zone')
        if rz:
            _set_hdr_bg(rz, COLORS['bg_sidebar'])

    # 设置新高亮
    if target and target != '__root__' and target in _drag['folder_hdrs']:
        hdr = _drag['folder_hdrs'][target]
        _set_hdr_bg(hdr, COLORS['accent_light'])
        _show_hl_bar(hdr)
    elif target == '__root__':
        rz = _drag.get('root_zone')
        if rz:
            _set_hdr_bg(rz, COLORS['accent_light'])
            _show_hl_bar(rz)

    _drag['hl_id'] = target


def _on_drag_end(event):
    """拖拽结束 — 执行移动操作。"""
    if not _drag['active']:
        return
    _drag['active'] = False

    src_type = _drag['type']
    src_id = _drag['src_id']
    src_group = _drag['src_group']
    target = _drag['hl_id']
    rebuild = _drag['on_rebuild']
    src_w = _drag.get('src_widget')

    # 还原外观
    _clear_all_highlights()
    if src_w:
        try:
            if src_type == 'draft':
                bdr = (COLORS['accent'] if src_id == _drag['current_draft']
                       else COLORS['border'])
                src_w.configure(highlightbackground=bdr)
                for ch in src_w.winfo_children():
                    _dim_widget(ch, False)
            else:
                _set_hdr_bg(src_w, COLORS['bg_sidebar'])
                for ch in src_w.winfo_children():
                    _dim_widget(ch, False)
        except tk.TclError:
            pass

    # 最小拖拽距离检查（防止误触）
    if abs(event.y_root - _drag.get('start_y', event.y_root)) < 8:
        return

    # 优先检查插入位置排序
    insert = _drag.get('insert_target')
    if insert is not None:
        ins_gid, ins_before = insert
        if src_type == 'draft':
            # 文稿排序
            if ins_gid == src_group:
                draft_manager.reorder_file_in_group(src_id, ins_gid, ins_before)
            else:
                if ins_gid is None:
                    draft_manager.remove_from_group(src_id)
                else:
                    draft_manager.move_to_group(src_id, ins_gid)
                draft_manager.reorder_file_in_group(src_id, ins_gid, ins_before)
        elif src_type == 'folder':
            # 文件夹排序 — ins_gid 是父级, ins_before 是 before_group_id
            if ins_gid == src_group:
                draft_manager.reorder_group(src_id, ins_gid, ins_before)
            else:
                draft_manager.move_group_into(src_id, ins_gid)
                draft_manager.reorder_group(src_id, ins_gid, ins_before)
        if rebuild:
            try:
                _drag['sidebar'].after(1, rebuild)
            except (tk.TclError, AttributeError):
                rebuild()
        return

    if target is None:
        return

    # 执行拖放
    if target == '__root__':
        if src_type == 'draft' and src_group is not None:
            draft_manager.remove_from_group(src_id)
        elif src_type == 'folder' and src_group is not None:
            draft_manager.move_group_into(src_id, None)
        else:
            return
    else:
        if src_type == 'draft':
            if target == src_group:
                return
            draft_manager.move_to_group(src_id, target)
        elif src_type == 'folder':
            if target == src_group:
                return
            draft_manager.move_group_into(src_id, target)

    # 延迟刷新（避免在回调中销毁控件）
    if rebuild:
        try:
            _drag['sidebar'].after(1, rebuild)
        except (tk.TclError, AttributeError):
            rebuild()


def _dim_widget(widget, dim):
    """降低/恢复控件前景色以模拟半透明。"""
    try:
        if dim:
            widget.configure(fg=COLORS['text_muted'])
        else:
            # 恢复时重建整个侧边栏，这里只做最佳努力
            widget.configure(fg=COLORS['text_primary'])
    except tk.TclError:
        pass
    for ch in widget.winfo_children():
        _dim_widget(ch, dim)


def _show_hl_bar(target_widget):
    """在目标 widget 左侧放置一条醒目的彩色指示条。"""
    _remove_hl_bar()
    try:
        bar = tk.Frame(target_widget, bg=COLORS['accent'], width=4)
        bar.place(x=0, y=0, relheight=1.0)
        _drag['hl_bar'] = bar
    except tk.TclError:
        pass


def _remove_hl_bar():
    """移除指示条。"""
    bar = _drag.get('hl_bar')
    if bar:
        try:
            bar.destroy()
        except tk.TclError:
            pass
        _drag['hl_bar'] = None


def _clear_all_highlights():
    """清除所有拖拽高亮。"""
    _remove_hl_bar()
    _remove_insert_line()
    _drag['insert_target'] = None
    for gid, hdr in _drag['folder_hdrs'].items():
        _set_hdr_bg(hdr, COLORS['bg_sidebar'])
    rz = _drag.get('root_zone')
    if rz:
        _set_hdr_bg(rz, COLORS['bg_sidebar'])
    _drag['hl_id'] = None


def _clear_folder_highlight():
    """仅清除文件夹高亮（保留插入线）。"""
    _remove_hl_bar()
    old = _drag['hl_id']
    if old and old != '__root__' and old in _drag['folder_hdrs']:
        _set_hdr_bg(_drag['folder_hdrs'][old], COLORS['bg_sidebar'])
    elif old == '__root__':
        rz = _drag.get('root_zone')
        if rz:
            _set_hdr_bg(rz, COLORS['bg_sidebar'])
    _drag['hl_id'] = None


def _find_insert_position(y):
    """查找光标y位置最近的卡片间插入点。
    返回 (card_widget, group_id, before_filename) 或 None。"""
    cards = _drag['card_widgets']
    src_fn = _drag['src_id']
    if not cards:
        return None

    best = None
    best_dist = 20  # 最大吹入距离（20px）

    for i, (w, fn, gid) in enumerate(cards):
        if fn == src_fn:
            continue
        try:
            wy = w.winfo_rooty()
            wh = w.winfo_height()
        except tk.TclError:
            continue

        # 检查卡片上边缘（插入到此卡片之前）
        dist_top = abs(y - wy)
        if dist_top < best_dist:
            best_dist = dist_top
            best = (w, gid, fn)  # 插入到 fn 之前

        # 检查卡片下边缘（插入到此卡片之后）
        dist_bot = abs(y - (wy + wh))
        if dist_bot < best_dist:
            best_dist = dist_bot
            # 下一张同组卡片的 filename，或 None 表示末尾
            next_fn = None
            for j in range(i + 1, len(cards)):
                nw, nfn, ngid = cards[j]
                if nfn != src_fn and ngid == gid:
                    next_fn = nfn
                    break
            best = (w, gid, next_fn)

    return best


def _find_folder_insert_position(y):
    """查找光标y位置最近的文件夹间插入点。
    返回 (zone_widget, parent_gid, before_group_id) 或 None。"""
    folders = _drag['folder_widgets']
    src_id = _drag['src_id']
    if not folders:
        return None

    best = None
    best_dist = 20

    for i, (zone, gid, pgid) in enumerate(folders):
        if gid == src_id:
            continue
        try:
            zy = zone.winfo_rooty()
            zh = zone.winfo_height()
        except tk.TclError:
            continue

        # 文件夹上边缘（插入到此文件夹之前）
        dist_top = abs(y - zy)
        if dist_top < best_dist:
            best_dist = dist_top
            best = (zone, pgid, gid)

        # 文件夹下边缘（插入到此文件夹之后）
        dist_bot = abs(y - (zy + zh))
        if dist_bot < best_dist:
            best_dist = dist_bot
            next_gid = None
            for j in range(i + 1, len(folders)):
                _, ngid, npgid = folders[j]
                if ngid != src_id and npgid == pgid:
                    next_gid = ngid
                    break
            best = (zone, pgid, next_gid)

    return best


def _show_insert_at(insert_info):
    """显示插入位置指示线。"""
    ref_w, gid, before_id = insert_info
    new_target = (gid, before_id)

    if _drag['insert_target'] == new_target:
        return

    _remove_insert_line()
    _drag['insert_target'] = new_target

    try:
        # 找到目标 widget 以计算线的屏幕位置
        target_w = None
        anchor_top = True  # True=放在目标上方, False=放在 ref_w 下方
        if _drag['type'] == 'draft':
            if before_id:
                for cw, cfn, cgid in _drag['card_widgets']:
                    if cfn == before_id and cgid == gid:
                        target_w = cw
                        break
            else:
                target_w = ref_w
                anchor_top = False
        else:
            if before_id:
                for zw, zgid, zpgid in _drag['folder_widgets']:
                    if zgid == before_id and zpgid == gid:
                        target_w = zw
                        break
            else:
                target_w = ref_w
                anchor_top = False

        if target_w is None:
            target_w = ref_w
            anchor_top = False

        # 用 place 在 sidebar 上绝对定位，不影响布局
        sidebar = _drag['sidebar']
        sy = sidebar.winfo_rooty()
        tw_y = target_w.winfo_rooty()
        if anchor_top:
            line_y = tw_y - sy - 2
        else:
            line_y = tw_y + target_w.winfo_height() - sy
        line = tk.Frame(sidebar, bg=COLORS['accent'], height=3)
        line.place(x=12, y=line_y, relwidth=1.0, width=-24)
        line.lift()
        _drag['insert_line'] = line
    except tk.TclError:
        pass


def _remove_insert_line():
    """移除插入位置指示线。"""
    line = _drag.get('insert_line')
    if line:
        try:
            line.destroy()
        except tk.TclError:
            pass
        _drag['insert_line'] = None
