import pandas as pd
from colorama import init, Fore, Back, Style
import sys
import re
import ctypes
from typing import Dict, List, Any

def _enable_vt_mode() -> bool:
    """在 Windows 上启用 VT(ANSI) 模式以支持 256 色/真彩色。
    返回是否成功启用。非 Windows 平台直接返回 True。
    """
    if sys.platform.startswith("win"):
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # 句柄常量
            STD_OUTPUT_HANDLE = -11
            STD_ERROR_HANDLE = -12
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

            def _set(handle_id: int) -> bool:
                h = kernel32.GetStdHandle(handle_id)
                if h in (0, -1):
                    return False
                mode = ctypes.c_uint()
                if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                    return False
                new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                if not kernel32.SetConsoleMode(h, new_mode):
                    return False
                # 读取回校验是否已生效
                mode2 = ctypes.c_uint()
                if not kernel32.GetConsoleMode(h, ctypes.byref(mode2)):
                    return False
                return bool(mode2.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING)

            ok_out = _set(STD_OUTPUT_HANDLE)
            ok_err = _set(STD_ERROR_HANDLE)
            return ok_out or ok_err
        except Exception:
            return False
    # 非 Windows 终端普遍支持 ANSI
    return True

# 先尝试启用 VT，再按结果决定 colorama 转换策略
_vt = _enable_vt_mode()
if _vt:
    # VT 可用时，关闭 colorama 的转换，让 ANSI 真彩色序列直通
    init(autoreset=True, convert=False, strip=False)
else:
    # 回退到默认：保留原有 16 色兼容转换
    init(autoreset=True)

def load_map_from_excel(file_path, sheet_name='字典表', note_col_index: int = 2):
    """从 Excel 读取映射，允许同一汉字出现多行，收集为列表保持顺序且不去重。
    返回: dict[char] = [ { 'phonetic': str, 'note': Optional[str] }, ... ]
    参数 note_col_index 使用 0 基索引（0=第一列）。例如注释在 Excel 第 k 列，则 note_col_index = k-1。
    """
    try:
        # 读整表，避免列数不够时报错
        df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine='openpyxl')
        # 清理：至少前两列需要有值
        df = df.dropna(how='any', subset=[0, 1])
        mapping: Dict[str, List[Dict[str, Any]]] = {}
        for row in df.itertuples(index=False, name=None):
            # row 是 tuple
            c_raw = row[0]
            p_raw = row[1]
            c = str(c_raw)
            p = str(p_raw).strip() if p_raw is not None else ''
            if not p:
                continue
            note = None
            if note_col_index is not None and isinstance(note_col_index, int) and note_col_index >= 0:
                if len(row) > note_col_index:
                    n = row[note_col_index]
                    if n is not None:
                        nt = str(n).strip()
                        if nt and nt.lower() not in ('nan', 'none'):
                            note = nt
            lst = mapping.setdefault(c, [])
            # 不去重：即便音标相同也保留（注释可能不同）
            lst.append({'phonetic': p, 'note': note})
        return mapping
    except FileNotFoundError:
        print(Fore.RED + f"错误：找不到 '{file_path}' 文件。")
        print("请确保该文件与脚本位于同一目录中。")
        return None
    except Exception as e:
        print(Fore.RED + f"读取Excel文件时出错: {e}")
        return None

EXCEL_FILE = '上古汉语音节表 25.10.21.xlsx'
# 注释所在的 Excel 列（0 基索引）。
EXCEL_NOTE_COL = 10

# 输入的原始行缓存
raw_lines: list[str] = []

mapping = load_map_from_excel(EXCEL_FILE, note_col_index=EXCEL_NOTE_COL)
if mapping is None:
    sys.exit(1)

HELP_TEXT = f"""指令：
  直接输入文本行缓存；
  输入 1 -> 开始多音字统一选择并输出结果；
  输入 /h 或 /help 查看帮助；
  输入 /q 退出。
说明：同一字的选定读音可一次性应用于所有出现位置；也可单独逐个位置指定。
"""

print(Fore.MAGENTA + "多音字批量处理模式。输入行后按 1 进入选择。/h 帮助。" + Fore.RESET)

def format_note_multiline(note_txt: str) -> str:
    """将注释中紧贴中文的编号(1,2,3,...)前面插入换行, 使每条义项独立一行。
    规则: 非行首且前面不是换行的数字, 且其后紧跟中文字符(基本汉字范围), 则在数字前加换行。
    例如: '1修飾……2掩飾……' -> '1修飾……\n2掩飾……'
    保留原有换行, 避免重复插入。"""
    if not note_txt:
        return note_txt
    # 去除首尾空白
    s = note_txt.strip()
    # 在满足条件的数字前插入换行: 不是开头且前面不是\n, 后跟汉字
    # 汉字范围 \u4e00-\u9fff (基本区) 已足够本场景
    s = re.sub(r'(?<!^)(?<!\n)(\d+)(?=[\u4e00-\u9fff])', r'\n\1', s)
    return s

def print_note_block(note_txt: str):
    """彩色打印注释块（已简化：不再单独输出“注:”标题行）。"""
    formatted = format_note_multiline(note_txt)
    # 定义 256 色灰度（需 VT 支持）：
    #  - 38;5;250 约等于浅灰，38;5;244/240 为较深的灰
    def ansi_256(n: int) -> str:
        n = max(0, min(255, int(n)))
        return f"\x1b[38;5;{n}m"

    LIGHT_GRAY = ansi_256(250)
    DARK_GRAY = ansi_256(244)

    # 使用“浅灰(真灰)”与“灰(深灰)”两色交替
    palette = [LIGHT_GRAY, DARK_GRAY]
    for idx, ln in enumerate(formatted.split('\n')):
        seg = ln.strip()
        color = palette[idx % 2]
        m = re.match(r'^(\d+)(.*)$', seg)
        if m:
            num, rest = m.groups()
            print("        " + color + num + rest + Style.RESET_ALL)
        else:
            print("        " + color + seg + Style.RESET_ALL)

def collect_polyphones(lines):
    """扫描所有行，返回需要用户选择的多音字位置列表。
    返回结构: list[dict] 每个元素包含
        index_line: 行号
        index_char: 字在该行中的位置
        char: 该汉字
        options: 其可选读音列表
    """
    tasks = []
    for li, line in enumerate(lines):
        for ci, ch in enumerate(line):
            opts = mapping.get(ch)
            if not opts:
                continue
            if len(opts) > 1:
                tasks.append({
                    'index_line': li,
                    'index_char': ci,
                    'char': ch,
                    'options': opts
                })
    return tasks

def show_new_occurrences(ch: str, lines: list[str], processed_positions: set[tuple[int,int]]):
    """显示该字尚未处理的具体位置(按字符位置)。
    规则:
      - 首次出现：打印所有包含该字的行；行内未处理位置高亮(黄底)，已处理位置(理论上首次没有)普通。
      - 后续出现：只输出仍存在未处理位置的行；并在行末标注新增/剩余计数。
      - 若所有出现位置都已处理，提示已全部处理。
    processed_positions: 已确认读音的 (line_idx,char_idx) 集合。
    """
    # 收集所有出现位置
    all_positions: list[tuple[int,int]] = []
    for li, line in enumerate(lines):
        for ci, c in enumerate(line):
            if c == ch:
                all_positions.append((li, ci))
    unprocessed = [pos for pos in all_positions if pos not in processed_positions]
    if not processed_positions:
        header = "首次出现，所有位置："
    else:
        header = "剩余未处理位置：" if unprocessed else "无未处理位置（全部已选择）"
    print(Fore.MAGENTA + f"\n『{ch}』 {header}" + Fore.RESET)
    if not unprocessed:
        return
    # 按行分组展示
    by_line: dict[int, list[int]] = {}
    for li, ci in unprocessed:
        by_line.setdefault(li, []).append(ci)
    for li in sorted(by_line.keys()):
        line = lines[li]
        # 构造高亮：未处理位置黄底，已处理位置淡灰底
        rendered_chars = []
        for ci, c in enumerate(line):
            if c != ch:
                rendered_chars.append(c)
            else:
                if (li, ci) in processed_positions:
                    # 已处理用淡灰前景
                    rendered_chars.append("\x1b[38;5;244m" + c + Style.RESET_ALL)
                else:
                    rendered_chars.append(Back.YELLOW + c + Style.RESET_ALL)
        print(Fore.WHITE + f"  行{li+1:>3}: " + Fore.RESET + ''.join(rendered_chars))
    print(Fore.CYAN + f"未处理位置数: {len(unprocessed)} / 总出现: {len(all_positions)}\n" + Fore.RESET)

def show_line_with_pointer(line, pos):
    return (line[:pos] + Back.YELLOW + line[pos] + Style.RESET_ALL + line[pos+1:])

def choose_readings(lines):
    tasks = collect_polyphones(lines)
    if not tasks:
        print(Fore.GREEN + "没有多音字，直接输出。" + Fore.RESET)
        return {}
    # 对同一字的全局选择缓存
    global_choice = {}
    per_position_choice = {}
    # 跟踪某字已处理过的具体位置 (line_idx,char_idx)
    processed_positions: dict[str, set[tuple[int,int]]] = {}
    i = 0
    total = len(tasks)
    while i < total:
        t = tasks[i]
        ch = t['char']
        line_idx = t['index_line']
        char_idx = t['index_char']
        opts = t['options']
        # 若该字已有全局选择，直接使用
        if ch in global_choice:
            per_position_choice[(line_idx, char_idx)] = global_choice[ch]
            i += 1
            continue
        # 自动预览：在未设置全局读音前，只要该字在缓存行出现次数>1，每次到该字都展示上下文
        total_count = sum(ln.count(ch) for ln in lines)
        if total_count > 1:
            pos_set = processed_positions.setdefault(ch, set())
            show_new_occurrences(ch, lines, pos_set)
        line_display = show_line_with_pointer(lines[line_idx], char_idx)
        print("\n" + Fore.CYAN + f"[{i+1}/{total}] 行{line_idx+1} 字『{ch}』: " + Fore.RESET)
        print(line_display)
        for oi, o in enumerate(opts, 1):
            phon = o.get('phonetic') if isinstance(o, dict) else str(o)
            note = o.get('note') if isinstance(o, dict) else None
            note_txt = (str(note).strip() if note is not None else '')
            print(f"  {oi}. " + Style.BRIGHT + Fore.GREEN + f"{phon}" + Style.RESET_ALL)
            if note_txt:
                print_note_block(note_txt)
        # 交互提示：自动预览已开启，无需手动 v
        print(Fore.CYAN + "选择序号:" + Style.RESET_ALL + Fore.CYAN + " (a序号 -> 全局; b -> 返回上一个) " + Style.RESET_ALL)
        user = input('> ').strip().lower()
        if user == 'b':
            if i > 0:
                # 回退到上一个，需要清除之前的选择（若是全局？保持全局不变以免混乱，简化：不回滚全局）
                i -= 1
                prev = tasks[i]
                per_position_choice.pop((prev['index_line'], prev['index_char']), None)
            else:
                print('已经是第一个。')
            continue
        if user.startswith('a'):
            num_part = user[1:]
            if num_part.isdigit():
                idx = int(num_part)
                if 1 <= idx <= len(opts):
                    chosen_item = opts[idx-1]
                    chosen = chosen_item['phonetic'] if isinstance(chosen_item, dict) else str(chosen_item)
                    global_choice[ch] = chosen
                    per_position_choice[(line_idx, char_idx)] = chosen
                    print(Fore.GREEN + f"已将『{ch}』设为全局读音: {chosen}" + Fore.RESET)
                    # 全局选择也视为处理过当前行
                    # 标记当前具体位置已处理
                    processed_positions.setdefault(ch, set()).add((line_idx, char_idx))
                    i += 1
                    continue
            print(Fore.RED + '格式 a序号 无效。' + Fore.RESET)
            continue
        if user.isdigit():
            idx = int(user)
            if 1 <= idx <= len(opts):
                chosen_item = opts[idx-1]
                chosen = chosen_item['phonetic'] if isinstance(chosen_item, dict) else str(chosen_item)
                per_position_choice[(line_idx, char_idx)] = chosen
                processed_positions.setdefault(ch, set()).add((line_idx, char_idx))
                i += 1
                continue
            else:
                print(Fore.RED + '序号超出范围。' + Fore.RESET)
                continue
        print(Fore.RED + '输入无效，请重试。' + Fore.RESET)
    # 直接返回逐位置选择；全局选择已经在遍历时写入 per_position_choice
    return per_position_choice

def translate_lines(lines, position_choices):
    out_lines = []
    for li, line in enumerate(lines):
        phonetics = []
        for ci, ch in enumerate(line):
            opts = mapping.get(ch)
            if not opts:
                phonetics.append(ch)
            elif len(opts) == 1:
                only = opts[0]
                phonetics.append(only['phonetic'] if isinstance(only, dict) else str(only))
            else:
                # 多音字: 优先位置选择，其次回退到第一个
                chosen = position_choices.get((li, ci)) if position_choices else None
                if chosen:
                    phonetics.append(chosen)
                else:
                    first = opts[0]
                    phonetics.append(first['phonetic'] if isinstance(first, dict) else str(first))
        out_lines.append(' '.join(phonetics))
    return out_lines

while True:
    try:
        s = input()
    except EOFError:
        break
    s = s.rstrip('\n')
    if s == '':
        continue
    if s == '/q':
        break
    if s in ('/h', '/help'):
        print(HELP_TEXT)
        continue
    if s == '1':
        if not raw_lines:
            print(Fore.YELLOW + '没有缓存的行。' + Fore.RESET)
            continue
        choices = choose_readings(raw_lines)
        result_lines = translate_lines(raw_lines, choices)
        # 输出结果
        for line, out in zip(raw_lines, result_lines):
            print(Fore.CYAN + out + Fore.RESET)
        raw_lines.clear()
        continue
    # 普通文本行
    raw_lines.append(s)