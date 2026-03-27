"""常量定义：配色方案、布局参数及通用工具函数。"""

import re


def format_note(note_txt):
    if not note_txt:
        return note_txt
    s = note_txt.strip()
    s = re.sub(r'(?<!^)(?<!\n)(\d+)(?=[\u4e00-\u9fff])', r'\n\1', s)
    return s


# ── 现代化配色方案 ──────────────────────────────────
COLORS = {
    'bg_main': '#F0F4F8',        # 主背景 - 柔和蓝灰
    'bg_card': '#FFFFFF',        # 卡片背景
    'bg_sidebar': '#FFFFFF',     # 侧边栏背景
    'bg_canvas': '#FAFCFE',      # 编辑区背景
    'accent': '#6366F1',         # 主强调色 - 现代靛蓝
    'accent_light': '#EEF2FF',   # 强调色浅色
    'accent_hover': '#4F46E5',   # 强调色悬停
    'text_primary': '#1E293B',   # 主文字
    'text_secondary': '#64748B', # 次要文字
    'text_muted': '#94A3B8',     # 淡化文字
    'border': '#E2E8F0',         # 边框
    'border_light': '#F1F5F9',   # 浅边框
    'poly_orange': '#F59E0B',    # 多音字 - 橙色
    'poly_orange_bg': '#FFFBEB',
    'poly_green': '#10B981',     # 已选择 - 绿色
    'poly_green_bg': '#ECFDF5',
    'poly_blue': '#3B82F6',      # 全局选择 - 蓝色
    'poly_blue_bg': '#EFF6FF',
    'cursor': '#6366F1',         # 光标
    'btn_primary': '#6366F1',
    'btn_primary_hover': '#4F46E5',
    'btn_secondary': '#E2E8F0',
    'btn_secondary_hover': '#CBD5E1',
    'shadow': '#00000008',       # 阴影
}

_CELL_PAD = 6
_CELL_GAP = 3
_LINE_GAP = 12
_CANVAS_MARGIN = 12

MAX_UNDO = 200
