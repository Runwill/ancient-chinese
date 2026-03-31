"""常量定义：配色方案、布局参数及通用工具函数。"""


# ── 括号范围（共用逻辑）──────────────────────────────


def find_bracket_ranges(line_chars):
    """查找行中 [] 括号的范围列表：[(start, end), ...]。"""
    ranges = []
    stk = []
    for i, ch in enumerate(line_chars):
        if ch == '[':
            stk.append(i)
        elif ch == ']' and stk:
            ranges.append((stk.pop(), i))
    return ranges


def in_bracket(pos, ranges):
    """判断 pos 是否在任何括号范围内。"""
    return any(s <= pos <= e for s, e in ranges)


# ── 主题配色方案 ──────────────────────────────────

_LIGHT_THEME = {
    'bg_main': '#F0F4F8',
    'bg_card': '#FFFFFF',
    'bg_sidebar': '#FFFFFF',
    'bg_canvas': '#FAFCFE',
    'accent': '#6366F1',
    'accent_light': '#EEF2FF',
    'accent_hover': '#4F46E5',
    'text_primary': '#1E293B',
    'text_secondary': '#64748B',
    'text_muted': '#94A3B8',
    'border': '#E2E8F0',
    'border_light': '#F1F5F9',
    'poly_orange': '#F59E0B',
    'poly_orange_bg': '#FFFBEB',
    'poly_green': '#10B981',
    'poly_green_bg': '#ECFDF5',
    'poly_blue': '#3B82F6',
    'poly_blue_bg': '#EFF6FF',
    'poly_purple': '#8B5CF6',
    'poly_purple_bg': '#F5F3FF',
    'unknown_char': '#EF4444',
    'unknown_char_bg': '#FEF2F2',
    'cursor': '#6366F1',
    'btn_primary': '#6366F1',
    'btn_primary_hover': '#4F46E5',
    'btn_secondary': '#E2E8F0',
    'btn_secondary_hover': '#CBD5E1',
    'shadow': '#00000008',
}

_DARK_THEME = {
    'bg_main': '#1E1E2E',
    'bg_card': '#2A2A3C',
    'bg_sidebar': '#252536',
    'bg_canvas': '#1E1E2E',
    'accent': '#6366F1',
    'accent_light': '#2E2B5F',
    'accent_hover': '#818CF8',
    'text_primary': '#E2E8F0',
    'text_secondary': '#94A3B8',
    'text_muted': '#64748B',
    'border': '#3F3F5C',
    'border_light': '#333348',
    'poly_orange': '#FBBF24',
    'poly_orange_bg': '#422006',
    'poly_green': '#34D399',
    'poly_green_bg': '#064E3B',
    'poly_blue': '#4B8BD4',
    'poly_blue_bg': '#1A2F4A',
    'poly_purple': '#A78BFA',
    'poly_purple_bg': '#3B2670',
    'unknown_char': '#F87171',
    'unknown_char_bg': '#450A0A',
    'cursor': '#6366F1',
    'btn_primary': '#6366F1',
    'btn_primary_hover': '#818CF8',
    'btn_secondary': '#3F3F5C',
    'btn_secondary_hover': '#4C4C6D',
    'shadow': '#00000020',
}

# 当前主题名称
_current_theme = 'dark'

# 活动配色字典 —— 所有模块通过 from constants import COLORS 引用同一对象
COLORS = dict(_DARK_THEME)


def set_theme(name):
    """切换主题（'light' 或 'dark'），就地更新 COLORS 字典。"""
    global _current_theme
    _current_theme = name
    COLORS.update(_LIGHT_THEME if name == 'light' else _DARK_THEME)


def get_theme():
    """返回当前主题名称。"""
    return _current_theme

_CELL_PAD = 6
_CELL_GAP = 3
_LINE_GAP = 12
_CANVAS_MARGIN = 12

MAX_UNDO = 200
