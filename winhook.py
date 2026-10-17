"""Win32 胶水层：按需安装的鼠标钩子、DPI 系数、全局热键、错误日志。"""

from __future__ import annotations

import ctypes
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
WM_LBUTTONDOWN = 0x0201
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001


class HookPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


class MouseHookStruct(ctypes.Structure):
    """MSLLHOOKSTRUCT：低级鼠标钩子事件的载荷。"""

    _fields_ = [
        ('pt', HookPoint),
        ('mouseData', ctypes.c_uint32),
        ('flags', ctypes.c_uint32),
        ('time', ctypes.c_uint32),
        ('extra', ctypes.c_void_p),
    ]


def log_path() -> Path:
    return Path(tempfile.gettempdir()) / '商人听金.log'


def log_error(context: str, exc: BaseException | None = None) -> None:
    """往 %TEMP%\\商人听金.log 追加一行；任何情况下都不抛异常。"""
    try:
        with log_path().open('a', encoding='utf-8') as handle:
            handle.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {context}: {exc!r}\n')
    except OSError:
        pass


def detect_dpi_scale(screen_width: int) -> float:
    """Tk 报的是逻辑像素，鼠标钩子报的是物理像素，算一下倍率。"""
    try:
        gdi32 = ctypes.windll.gdi32
        desktop = gdi32.CreateDCW('DISPLAY', None, None, None)
        physical = int(gdi32.GetDeviceCaps(desktop, 118))  # DESKTOPHORZRES
        gdi32.DeleteDC(desktop)
        if screen_width and physical > screen_width:
            return physical / screen_width
    except Exception as exc:
        log_error('读取 DPI 失败', exc)
    return 1.0


class MouseHook:
    """低级鼠标钩子：只在鼠标进入窗口矩形时安装，离开就卸载。"""

    def __init__(self, handler) -> None:
        """handler(wparam, info) -> bool：返回 True 表示吞掉这个事件。"""
        self._handler = handler
        self._handle = None
        self._callback = None

    @property
    def installed(self) -> bool:
        return bool(self._handle)

    def install(self) -> bool:
        if self._handle:
            return True
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            user32.WindowFromPoint.restype = ctypes.c_void_p
            user32.GetAncestor.restype = ctypes.c_void_p
            user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc, ctypes.c_void_p, ctypes.c_uint32]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t

            def callback(code, wparam, lparam):
                if code == 0:
                    try:
                        info = ctypes.cast(lparam, ctypes.POINTER(MouseHookStruct)).contents
                        if self._handler(wparam, info):
                            return 1
                    except Exception as exc:
                        log_error('鼠标钩子回调异常', exc)
                return user32.CallNextHookEx(None, code, wparam, lparam)

            self._callback = proc(callback)
            self._handle = user32.SetWindowsHookExW(WH_MOUSE_LL, self._callback, kernel32.GetModuleHandleW(None), 0)
            if not self._handle:
                log_error('安装鼠标钩子失败', ctypes.WinError())
        except Exception as exc:
            log_error('安装鼠标钩子失败', exc)
            self._handle = None
        return bool(self._handle)

    def uninstall(self) -> None:
        if not self._handle:
            return
        try:
            ctypes.windll.user32.UnhookWindowsHookEx(self._handle)
        except Exception as exc:
            log_error('卸载鼠标钩子失败', exc)
        self._handle = None


class Hotkeys:
    """全局热键：RegisterHotKey + 自己的消息泵线程（不碰键盘钩子）。"""

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
