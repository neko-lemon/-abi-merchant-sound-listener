"""Win32 胶水层：全局热键与错误日志（不含任何输入钩子）。"""

from __future__ import annotations

import ctypes
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001


def log_path() -> Path:
    return Path(tempfile.gettempdir()) / '商人听金.log'


def log_error(context: str, exc: BaseException | None = None) -> None:
    """往 %TEMP%\\商人听金.log 追加一行；任何情况下都不抛异常。"""
    try:
        with log_path().open('a', encoding='utf-8') as handle:
            handle.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {context}: {exc!r}\n')
    except OSError:
        pass


class Hotkeys:
    """全局热键：RegisterHotKey + 自己的消息泵线程，不碰任何鼠标/键盘钩子。"""

    def __init__(self, bindings: dict[tuple[int, int], int]) -> None:
        self._bindings = bindings  # {(修饰键, 虚拟键): 热键编号}
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self.failed: list[str] = []

    def start(self, handler) -> None:
        """handler(编号) 在泵线程里调用，调用方自己丢回 UI 队列。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._pump, args=(handler,), daemon=True, name='hotkeys')
        self._thread.start()

    def _pump(self, handler) -> None:
        user32 = ctypes.windll.user32
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        user32.GetMessageW.restype = ctypes.c_int
        user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = ctypes.c_bool
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        for (modifiers, key), hotkey_id in self._bindings.items():
            if not user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                label = f'{modifiers:#x}/{key:#x}'
                self.failed.append(label)
                log_error(f'注册热键失败 {label}', ctypes.WinError())

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                try:
                    handler(int(message.wParam))
                except Exception as exc:
                    log_error('热键回调异常', exc)

        for hotkey_id in self._bindings.values():
            user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
