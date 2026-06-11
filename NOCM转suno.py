"""NOCM 转 Suno 命令行兼容入口。"""

import os
import sys
import importlib.util


PROJECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '汉转NOCM')
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def load_transcriber_module():
    module_path = os.path.join(PROJECT_DIR, 'nocm_transcriber.py')
    spec = importlib.util.spec_from_file_location('nocm_transcriber', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TRANSCRIBER = load_transcriber_module()
DEFAULT_SCHEME_ID = _TRANSCRIBER.DEFAULT_SCHEME_ID
NocmTranscriber = _TRANSCRIBER.NocmTranscriber
load_scheme = _TRANSCRIBER.load_scheme


def convert_tokens(tokens, transcriber):
    """转换一行 token；方括号标签原样保留。"""
    out = []
    for token in tokens:
        if token.startswith('[') and token.endswith(']'):
            out.append(token)
        else:
            out.append(transcriber.convert_token(token))
    return out


def main():
    scheme_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SCHEME_ID
    transcriber = NocmTranscriber(load_scheme(scheme_id))
    pending = []
    while True:
        try:
            tokens = input().split()
        except EOFError:
            break
        if tokens == ['1']:
            for item in pending:
                print(item, end='' if item == '\n' else ' ')
            pending.clear()
            print('')
            continue
        pending.extend(convert_tokens(tokens, transcriber))
        pending.append('\n')


if __name__ == '__main__':
    main()
