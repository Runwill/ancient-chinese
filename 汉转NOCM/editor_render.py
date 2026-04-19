"""编辑器渲染：Canvas 显示重建与光标绘制。"""

import re

from constants import (COLORS, _CELL_PAD, _CELL_GAP, _LINE_GAP, _CANVAS_MARGIN,
                       find_bracket_ranges, in_bracket)
from widgets import freeze_redraw, thaw_redraw

# 正常字符：中英文标点、段落符号（圆圈菱形等）、空格、数字、字母
_NORMAL_NON_HAN = re.compile(
    r'[\s'
    r'a-zA-Z0-9'
    r'，。！？；：、「」『』【】（）《》〈〉〔〕\u201c\u201d\u2018\u2019'
    r',\.!\?;:\(\)\[\]\{\}"\'`~@#\$%\^&\*\-_=\+\\|/<>'
    r'…—―─·•◆◇○●◎■□▲△▼▽★☆※→←↑↓↔§¶†‡°℃'
    r'\u3000-\u303F'  # CJK 符号和标点
    r']'
)


class EditorRenderer:
    """负责在 Canvas 上渲染缓冲区内容和光标。
    
    采用虚拟渲染：布局阶段计算所有单元格坐标（纯 Python，极快），
    但只为当前可视区域内的行创建 Canvas items，滚动时增量补绘。
    """

    def __init__(self, canvas, char_font, phon_font):
        self.canvas = canvas
        self._char_font = char_font
        self._phon_font = phon_font
        self._char_h = char_font.metrics('linespace')
        self._phon_h = phon_font.metrics('linespace')
        self._cell_h = self._char_h + self._phon_h + _CELL_PAD * 2
        self._cell_rects = [[]]
        self._line_y = [_CANVAS_MARGIN]
        self._cursor_id = None
        self._last_canvas_w = 0
        self._width_cache = {}   # (ch, phon) -> cell_width
        self._configure_timer = None
        # 虚拟渲染状态
        self._layout_lines = []  # [(y_min, y_max, [(x,y,cw,ch,phon,fg_ch,fg_ph,bg,outline), ...])]
        self._drawn_lines = set()
        self._total_h = 1

    @property
    def cell_h(self):
        return self._cell_h

    @property
    def cell_rects(self):
        return self._cell_rects

    @property
    def line_y(self):
        return self._line_y

    # ── 显示重建 ──────────────────────────────────

    def _measure_cell(self, ch, phon):
        """带缓存的单元格宽度测量。"""
        key = (ch, phon)
        cw = self._width_cache.get(key)
        if cw is None:
            cw = (max(self._char_font.measure(ch),
                      self._phon_font.measure(phon)) + _CELL_PAD * 2)
            self._width_cache[key] = cw
        return cw

    def rebuild(self, buffer, cell_info):
        """布局全部单元格，仅绘制可见区域（冻结窗口重绘）。"""
        canvas = self.canvas
        freeze_redraw(canvas)
        try:
            canvas.delete('all')
            self._cell_rects = []
            self._line_y = []
            self._cursor_id = None
            self._drawn_lines = set()
            self._layout_lines = []
            self._layout(buffer, cell_info)
            self._render_visible()
        finally:
            thaw_redraw(canvas)

    # ── 布局（纯计算，不创建 Canvas item） ────────

    def _layout(self, buffer, cell_info):
        canvas_w = max(self.canvas.winfo_width(), 200)
        cell_h = self._cell_h
        y = _CANVAS_MARGIN

        c_text_muted = COLORS['text_muted']
        c_text_primary = COLORS['text_primary']
        c_accent = COLORS['accent']
        c_border = COLORS['border']
        c_poly_green_bg = COLORS['poly_green_bg']
        c_poly_green = COLORS['poly_green']
        c_poly_purple_bg = COLORS['poly_purple_bg']
        c_poly_purple = COLORS['poly_purple']
        c_poly_blue_bg = COLORS['poly_blue_bg']
        c_poly_blue = COLORS['poly_blue']
        c_poly_orange_bg = COLORS['poly_orange_bg']
        c_poly_orange = COLORS['poly_orange']
        c_unknown = COLORS['unknown_char']
        c_unknown_bg = COLORS['unknown_char_bg']
        c_stale = COLORS['stale']
        c_stale_bg = COLORS['stale_bg']
        margin = _CANVAS_MARGIN
        gap = _CELL_GAP
        measure = self._measure_cell
        fullmatch = _NORMAL_NON_HAN.fullmatch

        for line_chars, line_info in zip(buffer, cell_info):
            br = find_bracket_ranges(line_chars)
            line_rects = []
            line_cells = []
            x = margin
            y_start = y
            self._line_y.append(y)

            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                in_brk = in_bracket(ci, br)
                phon = ch if in_brk else info['phonetic']
                cw = measure(ch, phon)
                if x + cw > canvas_w - margin and x > margin:
                    x = margin
                    y += cell_h + gap

                if in_brk:
                    fg_ch = fg_ph = c_text_muted
                    bg = outline = ''
                elif info.get('stale'):
                    # 数据源变化标记：琥珀色警告
                    if info['is_poly']:
                        sel = info.get('selected', 'none')
                        if sel == 'manual':
                            bg, fg_ch = c_poly_green_bg, c_poly_green
                        elif sel == 'global_recent':
                            bg, fg_ch = c_poly_purple_bg, c_poly_purple
                        elif sel == 'global':
                            bg, fg_ch = c_poly_blue_bg, c_poly_blue
                        else:
                            bg, fg_ch = c_poly_orange_bg, c_poly_orange
                        fg_ph, outline = c_accent, c_stale
                    else:
                        fg_ch, fg_ph = c_text_primary, c_text_muted
                        bg, outline = c_stale_bg, c_stale
                elif info['is_poly']:
                    sel = info.get('selected', 'none')
                    if sel == 'manual':
                        bg, fg_ch = c_poly_green_bg, c_poly_green
                    elif sel == 'global_recent':
                        bg, fg_ch = c_poly_purple_bg, c_poly_purple
                    elif sel == 'global':
                        bg, fg_ch = c_poly_blue_bg, c_poly_blue
                    else:
                        bg, fg_ch = c_poly_orange_bg, c_poly_orange
                    fg_ph, outline = c_accent, c_border
                else:
                    if info['phonetic'] == ch and not fullmatch(ch):
                        fg_ch = fg_ph = c_unknown
                        bg, outline = c_unknown_bg, c_border
                    else:
                        fg_ch, fg_ph = c_text_primary, c_text_muted
                        bg = outline = ''

                line_cells.append((x, y, cw, ch, phon, fg_ch, fg_ph, bg, outline))
                line_rects.append((x, y, x + cw, y + cell_h))
                x += cw + gap

            self._cell_rects.append(line_rects)
            self._layout_lines.append((y_start, y + cell_h, line_cells))
            y += cell_h + _LINE_GAP

        self._total_h = max(y + margin, 1)
        self.canvas.configure(scrollregion=(0, 0, canvas_w, self._total_h))

    # ── 可见区域绘制 ──────────────────────────────

    def _render_visible(self):
        """只为可视范围内（含上下 400px 缓冲）的行创建 Canvas item。"""
        canvas = self.canvas
        total_h = self._total_h
        vis = canvas.yview()
        y_top = vis[0] * total_h - 400
        y_bot = vis[1] * total_h + 400

        create_rect = canvas.create_rectangle
        create_text = canvas.create_text
        ch_font = self._char_font
        ph_font = self._phon_font
        ch_h = self._char_h
        pad = _CELL_PAD
        cell_h = self._cell_h
        drawn = self._drawn_lines

        for li, (y_min, y_max, cells) in enumerate(self._layout_lines):
            if li in drawn:
                continue
            if y_max < y_top or y_min > y_bot:
                continue
            for (x, y, cw, ch, phon, fg_ch, fg_ph, bg, outline) in cells:
                if bg:
                    create_rect(x, y, x + cw, y + cell_h,
                                fill=bg, outline=outline, width=1)
                mid = x + cw / 2
                create_text(mid, y + pad, text=ch,
                            font=ch_font, fill=fg_ch, anchor='n')
                create_text(mid, y + pad + ch_h, text=phon,
                            font=ph_font, fill=fg_ph, anchor='n')
            drawn.add(li)

    def render_on_scroll(self):
        """滚动后调用，增量绘制新进入可视区域的行。"""
        self._render_visible()

    # ── 光标 ─────────────────────────────────────

    def update_cursor(self, cur_line, cur_col):
        """更新光标位置。"""
        canvas = self.canvas
        if self._cursor_id:
            canvas.delete(self._cursor_id)
            self._cursor_id = None
        li, ci = cur_line, cur_col
        rects = self._cell_rects[li] if li < len(self._cell_rects) else []
        if ci < len(rects):
            x, y1, y2 = rects[ci][0], rects[ci][1], rects[ci][3]
        elif rects:
            x, y1, y2 = rects[-1][2] + 1, rects[-1][1], rects[-1][3]
        else:
            ly = self._line_y[li] if li < len(self._line_y) else _CANVAS_MARGIN
            x, y1, y2 = _CANVAS_MARGIN, ly, ly + self._cell_h
        self._cursor_id = canvas.create_line(
            x, y1, x, y2, width=3, fill=COLORS['cursor'])
        sr = canvas.cget('scrollregion')
        if sr:
            parts = sr.split()
            if len(parts) == 4:
                total_h = float(parts[3])
                canvas_h = canvas.winfo_height()
                if total_h > canvas_h > 0:
                    vis = canvas.yview()
                    ft, fb = y1 / total_h, y2 / total_h
                    if ft < vis[0]:
                        canvas.yview_moveto(max(0, ft - 0.02))
                        self._render_visible()
                    elif fb > vis[1]:
                        canvas.yview_moveto(
                            fb - (vis[1] - vis[0]) + 0.02)
                        self._render_visible()

    # ── 视觉行导航 ─────────────────────────────────

    def visual_nav(self, cur_line, cur_col, direction):
        """按视觉行（含自动换行）上下导航，返回 (new_line, new_col)。"""
        cell_rects = self._cell_rects

        # 1. 当前光标的视觉坐标
        rects = cell_rects[cur_line] if cur_line < len(cell_rects) else []
        if cur_col < len(rects):
            cursor_x = rects[cur_col][0]
            cursor_y = rects[cur_col][1]
        elif rects:
            cursor_x = rects[-1][2]
            cursor_y = rects[-1][1]
        else:
            cursor_x = _CANVAS_MARGIN
            cursor_y = (self._line_y[cur_line]
                        if cur_line < len(self._line_y) else _CANVAS_MARGIN)

        # 2. 收集所有视觉行 y -> [(li, ci, x1, x2)]
        row_map = {}
        for li, lr in enumerate(cell_rects):
            if not lr:
                y = (self._line_y[li]
                     if li < len(self._line_y) else _CANVAS_MARGIN)
                row_map.setdefault(y, [])
            for ci, (x1, y1, x2, y2) in enumerate(lr):
                row_map.setdefault(y1, []).append((li, ci, x1, x2))

        y_sorted = sorted(row_map.keys())
        if not y_sorted:
            return cur_line, cur_col

        # 3. 定位当前视觉行
        curr_idx = 0
        for i, y in enumerate(y_sorted):
            if y <= cursor_y:
                curr_idx = i

        target_idx = curr_idx + (-1 if direction == 'Up' else 1)
        if target_idx < 0 or target_idx >= len(y_sorted):
            return cur_line, cur_col

        cells = row_map[y_sorted[target_idx]]
        if not cells:
            # 空行
            for li in range(len(cell_rects)):
                y = (self._line_y[li]
                     if li < len(self._line_y) else _CANVAS_MARGIN)
                if y == y_sorted[target_idx] and not cell_rects[li]:
                    return li, 0
            return cur_line, cur_col

        # 4. 找 x 最近的单元格
        best_li, best_ci = cells[0][0], cells[0][1]
        best_dist = abs(cursor_x - cells[0][2])
        for li, ci, x1, x2 in cells[1:]:
            d = abs(cursor_x - x1)
            if d < best_dist:
                best_dist = d
                best_li, best_ci = li, ci

        # 光标超过该行最右单元格右边缘时，定位到行尾
        rightmost = max(cells, key=lambda c: c[3])
        if cursor_x > rightmost[3]:
            return rightmost[0], rightmost[1] + 1

        return best_li, best_ci

    def on_configure(self, event, buffer, cell_info, cur_line, cur_col):
        """Canvas 大小变化时重绘（带 debounce 减少拖拽窗口时的调用）。"""
        if event.width == self._last_canvas_w:
            return
        self._last_canvas_w = event.width
        if self._configure_timer is not None:
            self.canvas.after_cancel(self._configure_timer)
        self._configure_timer = self.canvas.after(
            60, lambda: self._do_configure(buffer, cell_info,
                                           cur_line, cur_col))

    def _do_configure(self, buffer, cell_info, cur_line, cur_col):
        self._configure_timer = None
        self.rebuild(buffer, cell_info)
        self.update_cursor(cur_line, cur_col)
