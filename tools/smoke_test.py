# -*- coding: utf-8 -*-
"""打包自检：启动 exe，确认窗口出现、进程存活、没有新的错误日志。

用法：python tools/smoke_test.py dist/商人听金.exe [--timeout 40]
退出码 0 表示通过。
"""

from __future__ import annotations

import ctypes
import os
import pathlib
import subprocess
import sys
import time
from ctypes import wintypes

TITLE_KEYWORD = '听声识物'
LOG_NAME = '商人听金.log'


def log_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get('TEMP') or os.environ.get('TMP') or '.') / LOG_NAME


def snapshot_log() -> int:
    path = log_path()
    return path.stat().st_size if path.exists() else 0


def new_errors(since: int) -> list[str]:
    path = log_path()
    if not path.exists():
        return []
    with path.open('rb') as handle:
        handle.seek(since)
        text = handle.read().decode('utf-8', 'replace')
    return [line for line in text.splitlines() if '启动失败' in line or '加载参考音效失败' in line]


def find_window() -> tuple[int, str] | None:
    user32 = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    found: list[tuple[int, str]] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if TITLE_KEYWORD in buffer.value:
                    found.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(proto(callback), 0)
    return found[0] if found else None


def main(argv: list[str]) -> int:
    if not argv:
        print('用法: smoke_test.py <exe> [--timeout 秒]')
        return 2
    exe = pathlib.Path(argv[0])
    timeout = 40.0
    if '--timeout' in argv:
        timeout = float(argv[argv.index('--timeout') + 1])
    if not exe.exists():
        print(f'FAIL 找不到 {exe}')
        return 1

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass

    baseline = snapshot_log()
    print(f'启动 {exe.name} ({exe.stat().st_size / 1048576:.1f} MB)')
    process = subprocess.Popen([str(exe)])
    try:
        deadline = time.time() + 60
        hit = None
        while time.time() < deadline:
            hit = find_window()
            if hit or process.poll() is not None:
                break
            time.sleep(1.0)
        if hit is None:
            print(f'FAIL 窗口没有出现（进程退出码 {process.poll()}）')
            return 1
        print(f'PASS 窗口已出现：{hit[1]}')
        remain = max(0.0, timeout - (time.time() - (deadline - 60)))
        time.sleep(remain)
        if process.poll() is not None:
            print(f'FAIL 进程提前退出（退出码 {process.poll()}）')
            return 1
        errors = new_errors(baseline)
        if errors:
            print('FAIL 启动期间写入了错误日志：')
            for line in errors:
                print('  ' + line)
            return 1
        print(f'PASS 存活 {timeout:.0f}s，无新增错误日志')
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
