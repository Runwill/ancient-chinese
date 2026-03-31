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
    'bg_main':           '#F7F8FA',
    'bg_card':           '#FFFFFF',
    'bg_sidebar':        '#FBFBFC',
    'bg_canvas':         '#FFFFFF',
    'accent':            '#4361EE',
    'accent_light':      '#EDF0FD',
    'accent_hover':      '#3A56D4',
    'text_primary':      '#1A1D26',
    'text_secondary':    '#5F6B7A',
    'text_muted':        '#9AA5B4',
    'border':            '#E8ECF1',
    'border_light':      '#F0F2F5',
    'poly_orange':       '#E8850C',
    'poly_orange_bg':    '#FFF7ED',
    'poly_green':        '#059669',
    'poly_green_bg':     '#ECFDF5',
    'poly_blue':         '#2563EB',
    'poly_blue_bg':      '#EFF6FF',
    'poly_purple':       '#7C3AED',
    'poly_purple_bg':    '#F5F3FF',
    'unknown_char':      '#DC2626',
    'unknown_char_bg':   '#FEF2F2',
    'cursor':            '#4361EE',
    'btn_primary':       '#4361EE',
    'btn_primary_hover': '#3A56D4',
    'btn_secondary':     '#EDF0F5',
    'btn_secondary_hover': '#DDE2EA',
    'btn_text_secondary': '#3D4654',
    'shadow':            '#0000000A',
    'divider':           '#EDF0F5',
    'hover_overlay':     '#F3F5F8',
    'tag_bg':            '#EDF0FD',
    'tag_fg':            '#4361EE',
    'danger':            '#DC2626',
    'danger_hover':      '#B91C1C',
    'warning':           '#E8850C',
    'stale':             '#D97706',
    'stale_bg':          '#FFFBEB',
}

_DARK_THEME = {
    'bg_main':           '#131620',
    'bg_card':           '#1C1F2E',
    'bg_sidebar':        '#171A27',
    'bg_canvas':         '#1C1F2E',
    'accent':            '#6C8AFF',
    'accent_light':      '#1E2340',
    'accent_hover':      '#8DA4FF',
    'text_primary':      '#E8ECF4',
    'text_secondary':    '#8B95A8',
    'text_muted':        '#545E72',
    'border':            '#2A2E3F',
    'border_light':      '#212533',
    'poly_orange':       '#F5A623',
    'poly_orange_bg':    '#2A2010',
    'poly_green':        '#34D399',
    'poly_green_bg':     '#0C2E21',
    'poly_blue':         '#60A5FA',
    'poly_blue_bg':      '#132040',
    'poly_purple':       '#A78BFA',
    'poly_purple_bg':    '#22183E',
    'unknown_char':      '#FB7185',
    'unknown_char_bg':   '#2D1017',
    'cursor':            '#6C8AFF',
    'btn_primary':       '#6C8AFF',
    'btn_primary_hover': '#8DA4FF',
    'btn_secondary':     '#252838',
    'btn_secondary_hover': '#2E3245',
    'btn_text_secondary': '#C0C8D8',
    'shadow':            '#00000030',
    'divider':           '#232636',
    'hover_overlay':     '#222538',
    'tag_bg':            '#1E2340',
    'tag_fg':            '#6C8AFF',
    'danger':            '#FB7185',
    'danger_hover':      '#F43F5E',
    'warning':           '#F5A623',
    'stale':             '#FBBF24',
    'stale_bg':          '#2A2410',
}

def _detect_system_theme():
    """检测 Windows 系统主题，返回 'light' 或 'dark'。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        val, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        winreg.CloseKey(key)
        return 'light' if val == 1 else 'dark'
    except Exception:
        return 'dark'

# 当前主题名称
_current_theme = _detect_system_theme()

# 活动配色字典 —— 所有模块通过 from constants import COLORS 引用同一对象
COLORS = dict(_LIGHT_THEME if _current_theme == 'light' else _DARK_THEME)


def set_theme(name):
    """切换主题（'light' 或 'dark'），就地更新 COLORS 字典。"""
    global _current_theme
    _current_theme = name
    COLORS.update(_LIGHT_THEME if name == 'light' else _DARK_THEME)


def get_theme():
    """返回当前主题名称。"""
    return _current_theme

_CELL_PAD = 6
_CELL_GAP = 4
_LINE_GAP = 14
_CANVAS_MARGIN = 16

MAX_UNDO = 200
