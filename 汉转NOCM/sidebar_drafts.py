"""侧边栏：文稿管理面板（含文件夹嵌套与拖拽移动）。"""

import tkinter as tk
from datetime import datetime

from constants import COLORS
from widgets import (ModernButton, ScrollableFrame,
                     bind_hover, bind_mousewheel, bind_single_double,
                     set_widget_bg, freeze_redraw, thaw_redraw)
from draft_io import list_drafts, rename_draft
from folder_manager import (get_groups, get_grouped_filenames, create_group,
                            rename_group, delete_group, toggle_group)
import drag_drop


# ── 公开接口 ──────────────────────────────────────────


def build(sidebar, current_draft, on_load, on_new, on_delete, on_rename,
          on_rebuild=None):
    """构建左侧文稿列表。使用 WM_SETREDRAW 冻结窗口重绘以消除闪烁。"""
    # 记录滚动位置（在冻结之前捕获）
    scroll_pos = None
    old_sf = _find_scrollable(sidebar)
    if old_sf:
        try:
            scroll_pos = old_sf.canvas.yview()[0]
        except tk.TclError:
            pass

    freeze_redraw(sidebar)
    try:
        # 销毁旧内容
        for w in sidebar.winfo_children():
            w.destroy()

        drag_drop.init(sidebar, current_draft, on_rebuild)

        # 按钮行
        btn_row = tk.Frame(sidebar, bg=COLORS['bg_sidebar'], padx=16)
        btn_row.pack(fill=tk.X, pady=(10, 10))

        for i, (text, cmd) in enumerate([
            ('📄＋', lambda: on_new()),
            ('📁＋', lambda: _do_create_folder(on_rebuild)),
        ]):
            b = tk.Label(btn_row, text=text, font=('Microsoft YaHei', 9),
                         bg=COLORS['accent_light'], fg=COLORS['accent'],
                         padx=6, pady=3, cursor='hand2')
            b.pack(side=tk.LEFT, padx=(6 if i else 0, 0))
            b.bind('<Button-1>', lambda e, c=cmd: c())
            b.bind('<Enter>', lambda e, w=b: w.configure(bg=COLORS['border']))
            b.bind('<Leave>',
                   lambda e, w=b: w.configure(bg=COLORS['accent_light']))

        tk.Frame(sidebar, bg=COLORS['border'], height=1).pack(fill=tk.X,
                                                               padx=16)

        # 滚动列表
        sf = ScrollableFrame(sidebar, bg=COLORS['bg_sidebar'])
        sf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        groups = get_groups()
        all_drafts = list_drafts()
        drafts_map = {d['filename']: d for d in all_drafts}
        grouped_fns = get_grouped_filenames(groups)
        ungrouped = [d for d in all_drafts
                     if d['filename'] not in grouped_fns]

        # 递归渲染文件夹树
        _render_tree(sf.inner, groups, drafts_map, current_draft,
                     on_load, on_delete, on_rename, on_rebuild,
                     sf.on_mousewheel, depth=0, parent_gid=None)

        if not groups and not ungrouped:
            _build_empty(sf.inner)
        else:
            if groups:
                rz = tk.Frame(sf.inner, bg=COLORS['bg_sidebar'], pady=4)
                rz.pack(fill=tk.X, padx=8)
                tk.Label(rz, text='─  未分组  ─',
                         font=('Microsoft YaHei', 8),
                         bg=COLORS['bg_sidebar'], fg=COLORS['text_muted']
                         ).pack()
                drag_drop.set_root_zone(rz)
                rz.bind('<MouseWheel>', sf.on_mousewheel)
                for ch in rz.winfo_children():
                    ch.bind('<MouseWheel>', sf.on_mousewheel)

            for d in ungrouped:
                _build_card(sf.inner, d, current_draft, None,
                            on_load, on_delete, on_rename,
                            sf.on_mousewheel, on_rebuild, depth=0)

        sf.canvas.bind('<MouseWheel>', sf.on_mousewheel)

        if scroll_pos is not None:
            sf.set_pending_yview(scroll_pos)

        # 在冻结状态下完成全部布局计算
        sidebar.update_idletasks()
    finally:
        thaw_redraw(sidebar)


def _find_scrollable(widget):
    """递归查找子树中的 ScrollableFrame。"""
    for w in widget.winfo_children():
        if isinstance(w, ScrollableFrame):
            return w
        found = _find_scrollable(w)
        if found:
            return found
    return None


def show_rename_dialog(parent_win, filename, old_name, on_done):
    """显示重命名文稿对话框。"""
    _show_name_dialog(parent_win, '重命名文稿', '文稿名称：', old_name,
                      lambda n: rename_draft(filename, n), on_done)


def show_rename_folder_dialog(parent_win, group_id, old_name, on_done):
    """显示重命名文件夹对话框。"""
    _show_name_dialog(parent_win, '重命名文件夹', '文件夹名称：', old_name,
                      lambda n: rename_group(group_id, n), on_done)


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
    create_group()
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
        delete_group(gid)
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
    drag_drop.register_folder(zone, gid, parent_gid)

    # ── 文件夹头部 ──
    hdr = tk.Frame(zone, bg=COLORS['bg_sidebar'], padx=left_pad, pady=6)
    hdr.pack(fill=tk.X, pady=(4, 0), padx=6)
    drag_drop.register_folder_hdr(gid, hdr)

    # 拖拽手柄
    handle = tk.Label(hdr, text='⣿', font=('Segoe UI Symbol', 9),
                      bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
                      cursor='fleur')
    handle.pack(side=tk.LEFT, padx=(0, 4))
    drag_drop.bind_drag_handle(handle, 'folder', gid, parent_gid, hdr)

    arrow = '▼' if expanded else '▶'
    arrow_lbl = tk.Label(hdr, text=arrow, font=('Microsoft YaHei', 8),
                         bg=COLORS['bg_sidebar'], fg=COLORS['text_muted'],
                         cursor='hand2', width=2, anchor='center')
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
        toggle_group(gid)
        # 就地展开/收起，不触发全量重建
        currently_visible = container.winfo_manager() != ''
        if currently_visible:
            container.pack_forget()
            arrow_lbl.configure(text='▶')
        else:
            container.pack(fill=tk.X)
            arrow_lbl.configure(text='▼')

    for w in (arrow_lbl, icon_lbl):
        w.bind('<Button-1>', _toggle)

    bind_single_double(
        name_lbl,
        on_single=_toggle,
        on_double=lambda: show_rename_folder_dialog(
            hdr.winfo_toplevel(), gid, group['name'],
            on_rebuild or (lambda: None)),
        delay=250,
    )

    # Hover（非拖拽时）
    def _hdr_enter(e):
        if not drag_drop.state.active:
            set_widget_bg(hdr, COLORS['border_light'])

    def _hdr_leave(e):
        if not drag_drop.state.active or drag_drop.state.hl_id != gid:
            set_widget_bg(hdr, COLORS['bg_sidebar'])

    hdr.bind('<Enter>', _hdr_enter)
    hdr.bind('<Leave>', _hdr_leave)
    hdr.bind('<MouseWheel>', mw_handler)
    for ch in hdr.winfo_children():
        ch.bind('<MouseWheel>', mw_handler)

    tk.Frame(zone, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16)

    # ── 文件夹内容（始终创建，通过 pack/pack_forget 控制可见性）──
    container = tk.Frame(zone, bg=COLORS['bg_sidebar'])

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

    if expanded:
        container.pack(fill=tk.X)


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
    drag_drop.bind_drag_handle(handle, 'draft', fn, group_id, card)

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
    bind_single_double(
        name_lbl,
        on_single=lambda: on_load(fn),
        on_double=lambda: on_rename(fn, draft['name']),
        delay=300,
    )

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
    drag_drop.register_card(card, fn, group_id)


# ── UI 工具 ──────────────────────────────────────────



