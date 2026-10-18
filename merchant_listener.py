"""商人听金 —— 程序入口。

打包成 windowed exe 后没有控制台，启动期的任何异常都要落日志并弹窗，
否则用户只会看到"双击没反应"。
"""

from __future__ import annotations

import ctypes
import sys

TITLE = '商人听金'


def _report(exc: BaseException) -> None:
    message = f'启动失败：{exc!r}'
    try:
        from winutil import log_error, log_path

        log_error('启动失败', exc)
        message += f'\n\n日志：{log_path()}'
    except Exception:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)
    except Exception:
        pass


def main() -> int:
    try:
        from app import run
    except BaseException as exc:
        _report(exc)
        return 1
    try:
        run()
    except BaseException as exc:
        _report(exc)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
