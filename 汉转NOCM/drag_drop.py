"""拖放系统：文稿卡片和文件夹的拖拽排序与移入移出。

文件夹拖拽采用「头部三区」检测模型——所有操作仅由光标
在最近文件夹头部内的相对位置决定：
  - 头部上 28% → 排在此文件夹之前
  - 头部中 44% → 移入此文件夹
  - 头部下 28% → 排在此文件夹之后
文稿卡片拖拽采用边缘接近检测 + 文件夹区域包含检测。
"""

import tkinter as tk

from constants import COLORS
from widgets import set_widget_bg
from folder_manager import (move_to_group, remove_from_group,
                            move_group_into, reorder_group,
                            reorder_file_in_group)


# ── 拖拽状态 ─────────────────────────────────────────

class DragState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.type = None            # 'draft' | 'folder'
        self.src_id = None          # filename 或 group_id
        self.src_group = None       # 所在父文件夹 id（None=顶层）
        self.src_widget = None
        self.start_y = 0

        # 注册表（每次 sidebar rebuild 时重建）
        self.folder_hdrs = {}       # {gid: hdr_widget}
        self.folder_zones = {}      # {gid: zone_widget}
        self.root_zone = None
        self.card_widgets = []      # [(widget, filename, group_id)]
        self.folder_widgets = []    # [(zone, gid, parent_gid)]

        # 拖拽期间的视觉/目标状态
        self.hl_id = None           # 移入目标 gid | '__root__'
        self.hl_bar = None
        self.insert_line = None
        self.insert_target = None   # (parent_gid, before_id)

        # 上下文
        self.sidebar = None
        self.on_rebuild = None
        self.current_draft = None


state = DragState()


# ── 公开接口 ─────────────────────────────────────────

def init(sidebar, current_draft, on_rebuild):
    state.reset()
    state.sidebar = sidebar
    state.on_rebuild = on_rebuild
    state.current_draft = current_draft


def register_card(widget, filename, group_id):
    state.card_widgets.append((widget, filename, group_id))


def register_folder(zone, gid, parent_gid):
    state.folder_zones[gid] = zone
    state.folder_widgets.append((zone, gid, parent_gid))


def register_folder_hdr(gid, hdr):
    state.folder_hdrs[gid] = hdr


def set_root_zone(rz):
    state.root_zone = rz


def bind_drag_handle(handle, dtype, src_id, src_group, src_widget):
    handle.bind('<Button-1>',
                lambda e: _start_drag(dtype, src_id, src_group,
                                      src_widget, e.y_root))
    handle.bind('<B1-Motion>', _on_drag_move)
    handle.bind('<ButtonRelease-1>', _on_drag_end)


# ── 内部：视觉工具 ──────────────────────────────────

def _dim_widget(widget, dim):
    try:
        widget.configure(fg=COLORS['text_muted'] if dim
                         else COLORS['text_primary'])
    except tk.TclError:
        pass
    for ch in widget.winfo_children():
        _dim_widget(ch, dim)


def _show_hl_bar(target_widget):
    _remove_hl_bar()
    try:
        bar = tk.Frame(target_widget, bg=COLORS['accent'], width=4)
        bar.place(x=0, y=0, relheight=1.0)
        state.hl_bar = bar
    except tk.TclError:
        pass


def _remove_hl_bar():
    if state.hl_bar:
        try:
            state.hl_bar.destroy()
        except tk.TclError:
            pass
        state.hl_bar = None


def _show_insert_line(target_w, anchor_top):
    _remove_insert_line()
    try:
        sidebar = state.sidebar
        sy = sidebar.winfo_rooty()
        wy = target_w.winfo_rooty()
        line_y = (wy - sy - 2) if anchor_top else (wy + target_w.winfo_height() - sy)
        line = tk.Frame(sidebar, bg=COLORS['accent'], height=3)
        line.place(x=12, y=line_y, relwidth=1.0, width=-24)
        line.lift()
        state.insert_line = line
    except tk.TclError:
        pass


def _remove_insert_line():
    if state.insert_line:
        try:
            state.insert_line.destroy()
        except tk.TclError:
            pass
        state.insert_line = None


def _clear_visuals():
    """清除所有拖拽视觉效果，不触碰逻辑目标状态。"""
    _remove_hl_bar()
    _remove_insert_line()
    for hdr in state.folder_hdrs.values():
        set_widget_bg(hdr, COLORS['bg_sidebar'])
    if state.root_zone:
        set_widget_bg(state.root_zone, COLORS['bg_sidebar'])


def _set_folder_highlight(new_gid):
    """更新文件夹移入高亮（new_gid=None 清除）。"""
    old = state.hl_id
    if old == new_gid:
        return
    if old and old != '__root__' and old in state.folder_hdrs:
        set_widget_bg(state.folder_hdrs[old], COLORS['bg_sidebar'])
    elif old == '__root__' and state.root_zone:
        set_widget_bg(state.root_zone, COLORS['bg_sidebar'])
    _remove_hl_bar()

    if new_gid and new_gid != '__root__' and new_gid in state.folder_hdrs:
        hdr = state.folder_hdrs[new_gid]
        set_widget_bg(hdr, COLORS['accent_light'])
        _show_hl_bar(hdr)
    elif new_gid == '__root__' and state.root_zone:
        set_widget_bg(state.root_zone, COLORS['accent_light'])
        _show_hl_bar(state.root_zone)

    state.hl_id = new_gid


# ── 内部：检测算法 ──────────────────────────────────

_CARD_EDGE_THRESHOLD = 24   # 卡片边缘接近检测阈值
_FOLDER_HDR_MARGIN = 12     # 头部上下扩展的检测距离
_EDGE_ZONE_RATIO = 0.28     # 头部上/下区域占比（排序区）


def _detect_folder_action(y):
    """文件夹拖拽：头部三区检测。

    仅在光标位于某个文件夹头部 ± MARGIN 范围内时触发。
    返回 ('insert', parent_gid, before_gid, matched_idx)
        | ('move_into', target_gid, None, matched_idx)
        | ('root', None, None, -1)
        | None
    """
    src_id = state.src_id
    best = None
    best_dist = float('inf')

    for i, (zone, gid, pgid) in enumerate(state.folder_widgets):
        if gid == src_id:
            continue
        hdr = state.folder_hdrs.get(gid)
        if not hdr:
            continue
        try:
            hy = hdr.winfo_rooty()
            hh = hdr.winfo_height()
        except tk.TclError:
            continue

        if not (hy - _FOLDER_HDR_MARGIN <= y <= hy + hh + _FOLDER_HDR_MARGIN):
            continue

        center_dist = abs(y - (hy + hh / 2))
        if center_dist >= best_dist:
            continue
        best_dist = center_dist

        edge = max(hh * _EDGE_ZONE_RATIO, 8)

        if y < hy + edge:
            # 上区 → 排在此文件夹之前
            best = ('insert', pgid, gid, i)
        elif y > hy + hh - edge:
            # 下区 → 排在此文件夹之后
            next_gid = None
            for j in range(i + 1, len(state.folder_widgets)):
                _, ngid, npgid = state.folder_widgets[j]
                if ngid != src_id and npgid == pgid:
                    next_gid = ngid
                    break
            best = ('insert', pgid, next_gid, i)
        else:
            # 中区 → 移入此文件夹
            best = ('move_into', gid, None, i)

    if best:
        return best

    # 根区域检测（仅当来源在某个文件夹内时才有意义）
    if state.src_group is not None and state.root_zone:
        try:
            rz = state.root_zone
            ry, rh = rz.winfo_rooty(), rz.winfo_height()
            if ry - 10 <= y <= ry + rh + 10:
                return ('root', None, None, -1)
        except tk.TclError:
            pass

    return None


def _find_card_insert(y):
    """在卡片之间查找最近的插入点（边缘接近检测）。
    返回 (parent_gid, before_filename, ref_widget, anchor_top) 或 None。"""
    src_fn = state.src_id
    best, best_dist = None, _CARD_EDGE_THRESHOLD

    for i, (w, fn, gid) in enumerate(state.card_widgets):
        if fn == src_fn:
            continue
        try:
            wy = w.winfo_rooty()
            wh = w.winfo_height()
        except tk.TclError:
            continue

        d = abs(y - wy)
        if d < best_dist:
            best_dist = d
            best = (gid, fn, w, True)

        d = abs(y - (wy + wh))
        if d < best_dist:
            best_dist = d
            next_fn = None
            for j in range(i + 1, len(state.card_widgets)):
                _, nfn, ngid = state.card_widgets[j]
                if nfn != src_fn and ngid == gid:
                    next_fn = nfn
                    break
            best = (gid, next_fn, w, False)

    return best


def _find_card_folder_target(y):
    """查找光标所在最深层文件夹 zone（仅用于文稿拖入文件夹）。
    返回 gid 或 '__root__' 或 None。"""
    target, best_h = None, float('inf')
    for gid, zone in state.folder_zones.items():
        try:
            zy = zone.winfo_rooty()
            zh = zone.winfo_height()
            if zy <= y <= zy + zh and zh < best_h:
                target, best_h = gid, zh
        except tk.TclError:
            continue

    if target is None and state.src_group is not None and state.root_zone:
        try:
            rz = state.root_zone
            ry, rh = rz.winfo_rooty(), rz.winfo_height()
            if ry - 10 <= y <= ry + rh + 10:
                target = '__root__'
        except tk.TclError:
            pass

    return target


# ── 内部：拖拽事件 ──────────────────────────────────

def _start_drag(dtype, src_id, src_group, widget, y_root):
    state.active = True
    state.type = dtype
    state.src_id = src_id
    state.src_group = src_group
    state.src_widget = widget
    state.start_y = y_root
    state.hl_id = None
    state.insert_target = None
    try:
        if dtype == 'draft':
            widget.configure(highlightbackground=COLORS['accent'])
        else:
            set_widget_bg(widget, COLORS['accent_light'])
        for ch in widget.winfo_children():
            _dim_widget(ch, True)
    except tk.TclError:
        pass


def _on_drag_move(event):
    if not state.active:
        return
    if state.type == 'draft':
        _handle_card_drag(event.y_root)
    else:
        _handle_folder_drag(event.y_root)


def _handle_card_drag(y):
    """文稿卡片拖拽：边缘接近 → 排序，区域包含 → 移入文件夹。"""
    ins = _find_card_insert(y)
    if ins is not None:
        gid, before_fn, ref_w, anchor_top = ins
        new_target = (gid, before_fn)
        if state.insert_target != new_target:
            state.insert_target = new_target
            line_w, line_top = ref_w, anchor_top
            if before_fn:
                for cw, cfn, cgid in state.card_widgets:
                    if cfn == before_fn and cgid == gid:
                        line_w, line_top = cw, True
                        break
            _show_insert_line(line_w, line_top)
        _set_folder_highlight(None)
        return

    _remove_insert_line()
    state.insert_target = None

    target = _find_card_folder_target(y)
    if target != state.hl_id:
        _set_folder_highlight(target)


def _handle_folder_drag(y):
    """文件夹拖拽：头部三区模型统一处理排序与移入。"""
    action = _detect_folder_action(y)

    if action is None:
        _remove_insert_line()
        state.insert_target = None
        _set_folder_highlight(None)
        return

    atype = action[0]

    if atype == 'insert':
        _, pgid, before_gid, idx = action
        new_target = (pgid, before_gid)
        if state.insert_target != new_target:
            state.insert_target = new_target
            if before_gid is not None:
                zw = state.folder_zones.get(before_gid)
                if zw:
                    _show_insert_line(zw, True)
            else:
                _show_insert_line(state.folder_widgets[idx][0], False)
        _set_folder_highlight(None)

    elif atype == 'move_into':
        _remove_insert_line()
        state.insert_target = None
        _set_folder_highlight(action[1])

    elif atype == 'root':
        _remove_insert_line()
        state.insert_target = None
        _set_folder_highlight('__root__')


def _on_drag_end(event):
    if not state.active:
        return
    state.active = False

    # ★ 先保存所有决策状态，再清除视觉
    src_type = state.type
    src_id = state.src_id
    src_group = state.src_group
    insert = state.insert_target
    target = state.hl_id
    rebuild = state.on_rebuild
    src_w = state.src_widget

    _clear_visuals()
    state.hl_id = None
    state.insert_target = None
    if src_w:
        try:
            if src_type == 'draft':
                bdr = (COLORS['accent'] if src_id == state.current_draft
                       else COLORS['border'])
                src_w.configure(highlightbackground=bdr)
            else:
                set_widget_bg(src_w, COLORS['bg_sidebar'])
            for ch in src_w.winfo_children():
                _dim_widget(ch, False)
        except tk.TclError:
            pass

    if abs(event.y_root - state.start_y) < 8:
        return

    changed = False
    if insert is not None:
        changed = _exec_insert(src_type, src_id, src_group, *insert)
    elif target is not None:
        changed = _exec_move_into(src_type, src_id, src_group, target)

    if changed and rebuild:
        try:
            state.sidebar.after(1, rebuild)
        except (tk.TclError, AttributeError):
            rebuild()


def _exec_insert(src_type, src_id, src_group, ins_parent, ins_before):
    """执行排序插入。"""
    if src_type == 'draft':
        if ins_parent != src_group:
            if ins_parent is None:
                remove_from_group(src_id)
            else:
                move_to_group(src_id, ins_parent)
        reorder_file_in_group(src_id, ins_parent, ins_before)
    elif src_type == 'folder':
        if ins_parent != src_group:
            move_group_into(src_id, ins_parent)
        reorder_group(src_id, ins_parent, ins_before)
    return True


def _exec_move_into(src_type, src_id, src_group, target):
    """执行拖入/拖出文件夹。"""
    if target == '__root__':
        if src_group is None:
            return False
        if src_type == 'draft':
            remove_from_group(src_id)
        else:
            move_group_into(src_id, None)
    else:
        if target == src_group:
            return False
        if src_type == 'draft':
            move_to_group(src_id, target)
        else:
            move_group_into(src_id, target)
    return True
