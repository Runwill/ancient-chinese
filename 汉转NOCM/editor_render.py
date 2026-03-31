"""编辑器渲染：Canvas 显示重建与光标绘制。"""

import re

from constants import (COLORS, _CELL_PAD, _CELL_GAP, _LINE_GAP, _CANVAS_MARGIN,
                       find_bracket_ranges, in_bracket)

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
    """负责在 Canvas 上渲染缓冲区内容和光标。"""

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
        self._width_cache = {}  # (ch, phon) -> cell_width
        self._configure_timer = None  # debounce on_configure

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
        """完整重建 Canvas 显示。"""
        canvas = self.canvas
        canvas.delete('all')
        self._cell_rects = []
        self._line_y = []
        self._cursor_id = None
        canvas_w = max(canvas.winfo_width(), 200)
        ch_font, ph_font = self._char_font, self._phon_font
        ch_h, ph_h = self._char_h, self._phon_h
        cell_h = self._cell_h
        y = _CANVAS_MARGIN

        for li, (line_chars, line_info) in enumerate(
                zip(buffer, cell_info)):
            br = find_bracket_ranges(line_chars)
            line_rects = []
            x = _CANVAS_MARGIN
            self._line_y.append(y)

            for ci, (ch, info) in enumerate(zip(line_chars, line_info)):
                in_brk = in_bracket(ci, br)
                phon = ch if in_brk else info['phonetic']
                cw = self._measure_cell(ch, phon)
                if x + cw > canvas_w - _CANVAS_MARGIN and x > _CANVAS_MARGIN:
                    x = _CANVAS_MARGIN
                    y += cell_h + _CELL_GAP

                if in_brk:
                    fg_ch, fg_ph, bg, outline = (
                        COLORS['text_muted'], COLORS['text_muted'], '', '')
                elif info['is_poly']:
                    sel = info.get('selected', 'none')
                    if sel == 'manual':
                        bg, fg_ch = COLORS['poly_green_bg'], COLORS['poly_green']
                    elif sel == 'global_recent':
                        bg, fg_ch = COLORS['poly_purple_bg'], COLORS['poly_purple']
                    elif sel == 'global':
                        bg, fg_ch = COLORS['poly_blue_bg'], COLORS['poly_blue']
                    else:
                        bg, fg_ch = COLORS['poly_orange_bg'], COLORS['poly_orange']
                    fg_ph, outline = COLORS['accent'], COLORS['border']
                else:
                    if info['phonetic'] == ch and not _NORMAL_NON_HAN.fullmatch(ch):
                        # 不在字典中且非普通标点/符号/空格 → 红色标记
                        fg_ch, fg_ph, bg, outline = (
                            COLORS['unknown_char'], COLORS['unknown_char'],
                            COLORS['unknown_char_bg'], COLORS['border'])
                    else:
                        fg_ch, fg_ph, bg, outline = (
                            COLORS['text_primary'], COLORS['text_muted'], '', '')

                if bg:
                    canvas.create_rectangle(
                        x, y, x + cw, y + cell_h,
                        fill=bg, outline=outline, width=1)
                mid = x + cw / 2
                canvas.create_text(
                    mid, y + _CELL_PAD, text=ch,
                    font=ch_font, fill=fg_ch, anchor='n')
                canvas.create_text(
                    mid, y + _CELL_PAD + ch_h, text=phon,
                    font=ph_font, fill=fg_ph, anchor='n')

                line_rects.append((x, y, x + cw, y + cell_h))
                x += cw + _CELL_GAP

            self._cell_rects.append(line_rects)
            y += cell_h + _LINE_GAP

        canvas.configure(
            scrollregion=(0, 0, canvas_w, max(y + _CANVAS_MARGIN, 1)))

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
                    elif fb > vis[1]:
                        canvas.yview_moveto(
                            fb - (vis[1] - vis[0]) + 0.02)

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
