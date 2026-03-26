"""打包脚本：使用 PyInstaller 将汉转NOCM 打包为单文件 exe。"""

import subprocess
import sys


def build():
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--windowed',
        '--name', '汉转NOCM',
        '--hidden-import', 'email.utils',
        'main.py',
    ]
    print('执行打包命令:')
    print(' '.join(cmd))
    subprocess.run(cmd, check=True)
    print('\n打包完成！exe 位于 dist/ 目录。')
    print('运行时 base.json.gz 和 extra.json.gz 需放在 exe 同目录下（首次运行会自动下载）。')


if __name__ == '__main__':
    build()
