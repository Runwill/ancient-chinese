"""打包脚本：使用 PyInstaller 将汉转PBOC 打包为单文件 exe。"""

import subprocess
import sys

from app_version import APP_NAME, __version__, version_tuple


def _write_version_file(path='build_version_info.txt'):
    major, minor, patch = version_tuple(__version__)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
      StringStruct('CompanyName', 'Runwill'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'HanToPBOC'),
      StringStruct('OriginalFilename', '汉转PBOC-{__version__}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')
    ])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)"""
    with open(path, 'w', encoding='utf-8') as file:
        file.write(content)


def build():
    version_file = 'build_version_info.txt'
    executable_name = f'汉转PBOC-{__version__}'
    _write_version_file(version_file)
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--windowed',
        '--name', executable_name,
        '--version-file', version_file,
        '--hidden-import', 'email.utils',
        '--collect-all', 'webview',
        '--hidden-import', 'clr_loader',
        '--add-data', 'web;web',
        'main.py',
    ]
    print('执行打包命令:')
    print(' '.join(cmd))
    subprocess.run(cmd, check=True)
    print('\n打包完成！exe 位于 dist/ 目录。')
    print('运行时 base.json.gz 和 extra.json.gz 需放在 exe 同目录下（首次运行会自动下载）。')


if __name__ == '__main__':
    build()
