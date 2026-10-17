"""叠在游戏画面上的识别面板。"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk

import numpy as np
import soundcard as sc
from PIL import ImageTk

from matcher import CAPTURE_RATE, Matcher
from resources import CATEGORY_ZH, catalog
from textimg import stroked_line
from winhook import (
    MOD_ALT,
    WM_LBUTTONDOWN,
    WM_MOUSEWHEEL,
    HookPoint,
    Hotkeys,
    MouseHook,
    detect_dpi_scale,
    log_error,
    log_path,
)

WINDOW_BG = '#101824'
WINDOW_SECONDS = 2.3
HIGH_VALUE_PRICE = 1_000_000
WHEEL_LINE = 120
HOTKEY_LISTEN = 1
HOTKEY_HIDE = 2
HOTKEY_KEYS = {(MOD_ALT, 0x34): HOTKEY_LISTEN, (MOD_ALT, 0x35): HOTKEY_HIDE}  # Alt+4 / Alt+5


def _inside(rects: tuple, x: int, y: int) -> bool:
    return any(rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3] for rect in rects)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title('暗区战地商人 · 听声识物')
        root.geometry('860x640')
        root.minsize(720, 520)

        self.matcher: Matcher | None = None
        self.devices = [mic for mic in sc.all_microphones(include_loopback=True) if mic.isloopback]
        default = sc.default_speaker()
        self.device_name = tk.StringVar(
            value=next((mic.name for mic in self.devices if mic.name == default.name),
                       self.devices[0].name if self.devices else '')
        )
        self.size = tk.StringVar(value='不限')
        self.auto = tk.BooleanVar(value=True)
        self.pin_window = tk.BooleanVar(value=True)
        self.bg_transparent = tk.BooleanVar(value=True)
        self.enhance = tk.BooleanVar(value=True)
        self.panel_opacity = tk.IntVar(value=100)
        self.status = tk.StringVar(value='正在加载参考音效…')
        self.last_confidence = ''
        self.listening = False
        self.busy = False
        self.audio_lock = threading.Lock()
        self.chunks: deque[np.ndarray] = deque(maxlen=35)
        self.messages: queue.Queue = queue.Queue()
        self.last_auto = 0.0
        self.last_match = (None, 0.0)
        self.tentative: tuple[int, float, int] | None = None
        self.last_ranked: list[tuple[int, str, float]] = []
        self.last_metric = 'cos'
        self.photos: list[ImageTk.PhotoImage] = []
        self._wheel_pending = 0
        self._wheel_rects: tuple = ()
        self._click_rects: tuple = ()
        self.dpi_scale = detect_dpi_scale(root.winfo_screenwidth())
        self.hook = MouseHook(self._on_mouse)
        self.hotkeys = Hotkeys(HOTKEY_KEYS)

        self._build()
        self.status.trace_add('write', self._sync_status_label)
        for sequence in ('<Configure>', '<Map>', '<Unmap>'):
            self.root.bind(sequence, self._update_rects)
        self._apply_transparency()
        self._apply_opacity()
        self._toggle_pin()

        self.hotkeys.start(lambda hotkey_id: self.messages.put(('hotkey', hotkey_id)))
        threading.Thread(target=self._load_matcher, daemon=True, name='matcher').start()

        root.after(75, self._drain_messages)
        root.after(120, self._sync_hook)
        root.after(250, self._auto_tick)
        root.after(800, self._keep_popups_usable)
        root.after(1200, self._report_hotkey_failures)
        root.protocol('WM_DELETE_WINDOW', self._close)

    # ---------- 界面 ----------

    def _build(self) -> None:
        self.root.configure(bg=WINDOW_BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=WINDOW_BG)
        style.configure('TLabel', background=WINDOW_BG, foreground='#d7e4ee', font=('Microsoft YaHei UI', 10))
        style.configure('TButton', padding=8, font=('Microsoft YaHei UI', 10))
        style.configure('TCombobox', padding=5)
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill='both', expand=True)

        row = ttk.Frame(frame)
        row.pack(fill='x')
        self.device_combo = ttk.Combobox(row, textvariable=self.device_name,
                                         values=[mic.name for mic in self.devices], width=18, state='readonly')
        self.device_combo.pack(side='left')

        size_row = ttk.Frame(frame)
        size_row.pack(fill='x', pady=(8, 0))
        size_combo = ttk.Combobox(size_row, textvariable=self.size,
                                  values=['不限', '1×1', '1×2', '2×1', '2×2', '2×3', '3×2'], width=7, state='readonly')
        self.size_combo = size_combo
        size_combo.pack(side='left', padx=8)
        size_combo.bind('<<ComboboxSelected>>',
                        lambda _event: self._render(self.last_ranked, self.last_metric) if self.last_ranked else None)

        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=15)
        self.listen_button = ttk.Button(controls, text='开始监听', command=self._toggle)
        self.listen_button.pack(side='left')
        ttk.Checkbutton(controls, text='自动尝试识别', variable=self.auto).pack(side='left', padx=10)
        ttk.Checkbutton(controls, text='窗口置顶', variable=self.pin_window,
                        command=self._toggle_pin).pack(side='left', padx=10)

        overlay = ttk.Frame(frame)
        overlay.pack(fill='x', pady=(0, 8))
        ttk.Checkbutton(overlay, text='背景透明（鼠标可穿透）', variable=self.bg_transparent,
                        command=self._apply_transparency).pack(side='left')
        self.enhance_check = ttk.Checkbutton(overlay, text='滚轮/点击增强', variable=self.enhance,
                                             command=self._sync_hook)
        self.enhance_check.pack(side='left', padx=(14, 0))
        self.opacity_scale = tk.Scale(overlay, from_=30, to=100, orient='horizontal', variable=self.panel_opacity,
                                      command=lambda _value: self._apply_opacity(), length=160, showvalue=True,
                                      bg=WINDOW_BG, fg='#d7e4ee', troughcolor='#142231', activebackground='#2a4763',
                                      highlightthickness=0, bd=0, relief='flat', sliderrelief='flat',
                                      font=('Microsoft YaHei UI', 9))
        self.opacity_scale.pack(side='left', padx=(18, 0))

        # 状态行只在有话说的时候才出现。
        self.status_label = ttk.Label(frame, textvariable=self.status, foreground='#85bce9')

        result_frame = ttk.Frame(frame)
        self.result_frame = result_frame
        result_frame.pack(fill='both', expand=True, pady=(0, 8))
        self.results = tk.Text(result_frame, height=18, wrap='word', bg=WINDOW_BG, fg='#d7e4ee',
                               insertbackground='white', font=('Microsoft YaHei UI', 10), relief='flat',
                               padx=15, pady=12, state='disabled')
        self.results.pack(side='left', fill='both', expand=True)
        self.results.bind('<MouseWheel>', self._on_native_wheel)

    def _alert(self, title: str, message: str) -> None:
        """置顶对话框：Tk 的 messagebox 会被置顶主窗挡住。"""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=WINDOW_BG)
        dialog.attributes('-topmost', True)
        dialog.transient(self.root)
        tk.Label(dialog, text=message, bg=WINDOW_BG, fg='#d7e4ee', justify='left', wraplength=340,
                 font=('Microsoft YaHei UI', 10)).pack(padx=18, pady=15)
        ttk.Button(dialog, text='好', command=dialog.destroy).pack(pady=(0, 14))
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 3)
        dialog.geometry(f'+{x}+{y}')
        dialog.grab_set()

    # ---------- 监听开关 ----------

    def _toggle(self) -> None:
        if self.listening:
            self.listening = False
            self.listen_button.configure(text='开始监听')
            self.status.set('已停止监听。')
            return
        if self.matcher is None:
            self.status.set('参考音效还在加载，请稍等。')
            return
        device = next((mic for mic in self.devices if mic.name == self.device_name.get()), None)
        if device is None:
            self._alert('找不到设备', '没有可用的系统播放设备。请检查 Windows 音频设置。')
            return
        self.chunks.clear()
        self.listening = True
        self.listen_button.configure(text='停止监听')
        self.status.set(f'正在监听：{device.name}')
        threading.Thread(target=self._capture, args=(device,), daemon=True).start()

    def _toggle_window(self) -> None:
        """Alt+5：隐藏到后台，再按一次回来。"""
        if self.root.state() == 'withdrawn':
            self.root.deiconify()
            self._toggle_pin()
            self.root.lift()
            self._update_rects()
        else:
            self.root.withdraw()

    def _toggle_pin(self) -> None:
        self.root.attributes('-topmost', self.pin_window.get())

    def _on_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == HOTKEY_LISTEN:
            self._toggle()
        elif hotkey_id == HOTKEY_HIDE:
            self._toggle_window()

    def _report_hotkey_failures(self) -> None:
        if self.hotkeys.failed:
            self.status.set('全局热键注册失败（可能被其他程序占用），Alt+4 / Alt+5 不可用。')

    # ---------- 透明 / 不透明度 ----------

    def _apply_transparency(self) -> None:
        """把整窗底色抠掉，只留文字和控件浮在游戏画面上。"""
        try:
            self.root.attributes('-transparentcolor', WINDOW_BG if self.bg_transparent.get() else '')
        except tk.TclError:
            self.bg_transparent.set(False)
            self.status.set('当前系统不支持背景透明，已关闭该选项。')
        self.enhance_check.configure(state='normal' if self.bg_transparent.get() else 'disabled')
        self._update_rects()
        self._sync_hook()

    def _apply_opacity(self) -> None:
        """整窗淡出，让游戏画面透过来。"""
        try:
            self.root.attributes('-alpha', max(0.3, min(1.0, self.panel_opacity.get() / 100)))
        except tk.TclError as exc:
            log_error('设置不透明度失败', exc)

    def _sync_status_label(self, *_args) -> None:
        text = self.status.get().strip()
        if text and not self.status_label.winfo_manager():
            self.status_label.pack(anchor='w', pady=(0, 8), before=self.result_frame)
        elif not text and self.status_label.winfo_manager():
            self.status_label.pack_forget()

    # ---------- 鼠标钩子（按需） ----------

    def _pointer_inside(self) -> bool:
        try:
            if self.root.state() != 'normal':
                return False
            x, y = self.root.winfo_pointerxy()
            left, top = self.root.winfo_rootx(), self.root.winfo_rooty()
            return left <= x <= left + self.root.winfo_width() and top <= y <= top + self.root.winfo_height()
        except tk.TclError:
            return False

    def _sync_hook(self) -> None:
        """只在需要且鼠标位于窗口内时挂着钩子，其余时间一律卸掉。"""
        try:
            needed = self.enhance.get() and self.bg_transparent.get() and self._pointer_inside()
            if needed and not self.hook.installed:
                self._update_rects()
                self.hook.install()
            elif not needed and self.hook.installed:
                self.hook.uninstall()
        except Exception as exc:
            log_error('同步鼠标钩子失败', exc)
        self.root.after(120, self._sync_hook)

    def _on_mouse(self, wparam: int, info) -> bool:
        """钩子回调：滚轮交给列表；会被系统丢掉的控件点击补发一次。"""
        x, y = info.pt.x, info.pt.y
        if wparam == WM_MOUSEWHEEL and _inside(self._wheel_rects, x, y):
            self.messages.put(('wheel', ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value))
            return True
        if wparam == WM_LBUTTONDOWN and _inside(self._click_rects, x, y) and self._click_would_get_lost(x, y):
            self.messages.put(('click', x, y))
            return True
        return False

    def _interactive_widgets(self) -> list:
        """不能被漏掉点击的控件：按钮、下拉、勾选框、滑块。"""
        found = []

        def walk(widget) -> None:
            for child in widget.winfo_children():
                if child.winfo_class() in ('TButton', 'TCombobox', 'TCheckbutton', 'Scale'):
                    found.append(child)
                walk(child)

        walk(self.root)
        return found

    def _rects(self, rects: list[tuple]) -> tuple:
        """同一批矩形，分别用 Tk 的逻辑像素和钩子的物理像素表示。"""
        logical = [tuple(rect) for rect in rects]
        if self.dpi_scale == 1.0:
            return tuple(logical)
        return tuple(logical) + tuple(tuple(value * self.dpi_scale for value in rect) for rect in logical)

    def _update_rects(self, _event=None) -> None:
        try:
            if self.root.state() in ('iconic', 'withdrawn') or not self.results.winfo_ismapped():
                self._wheel_rects = ()
                self._click_rects = ()
                return
            left, top = self.results.winfo_rootx(), self.results.winfo_rooty()
            results_rect = (left, top, left + self.results.winfo_width(), top + self.results.winfo_height())
            controls = []
            for widget in self._interactive_widgets():
                if not widget.winfo_ismapped():
                    continue
                x, y = widget.winfo_rootx(), widget.winfo_rooty()
                controls.append((x, y, x + widget.winfo_width(), y + widget.winfo_height()))
            self._wheel_rects = self._rects([results_rect])
            self._click_rects = self._rects(controls) if controls else ()
        except tk.TclError:
            self._wheel_rects = ()
            self._click_rects = ()

    def _click_would_get_lost(self, x: int, y: int) -> bool:
        """Windows 会把这次按下派给别的进程（抠色区或被别的窗口压着）时为真。"""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.WindowFromPoint(HookPoint(x, y))
            if not hwnd:
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value != ctypes.windll.kernel32.GetCurrentProcessId()
        except Exception as exc:
            log_error('判断点击归属失败', exc)
            return False

    def _replay_click(self, x: int, y: int) -> None:
        """把系统送错地方的按下补发给光标下的控件。"""
        try:
            logical_x, logical_y = int(x / self.dpi_scale), int(y / self.dpi_scale)
            widget = self.root.winfo_containing(logical_x, logical_y)
            if widget is None:
                return
            local_x = logical_x - widget.winfo_rootx()
            local_y = logical_y - widget.winfo_rooty()
            self.root.focus_force()
            widget.event_generate('<ButtonPress-1>', x=local_x, y=local_y, when='now')
            widget.event_generate('<ButtonRelease-1>', x=local_x, y=local_y, when='now')
        except tk.TclError as exc:
            log_error('补发点击失败', exc)

    def _keep_popups_usable(self) -> None:
        """下拉列表也是独立窗口，保持在置顶面板之上，否则看起来像点了没反应。"""
        try:
            for combo in (self.device_combo, self.size_combo):
                popdown = str(self.root.tk.call('ttk::combobox::PopdownWindow', combo._w))
                if popdown and self.root.tk.call('winfo', 'ismapped', popdown):
                    if int(self.root.tk.call('wm', 'attributes', popdown, '-topmost')) != 1:
                        self.root.tk.call('wm', 'attributes', popdown, '-topmost', 1)
                    self.root.tk.call('raise', popdown)
        except tk.TclError as exc:
            log_error('保持下拉弹层失败', exc)
        self.root.after(800, self._keep_popups_usable)

    def _on_native_wheel(self, event) -> str:
        """不透明时 Tk 默认一格滚两行，统一成一格一行。"""
        self._wheel_pending += event.delta
        steps, self._wheel_pending = divmod(self._wheel_pending, WHEEL_LINE)
        if steps:
            self.results.yview_scroll(-steps, 'units')
        return 'break'

    # ---------- 录音与识别 ----------

    def _load_matcher(self) -> None:
        try:
            matcher = Matcher()
        except Exception as exc:
            log_error('加载参考音效失败', exc)
            self.messages.put(('load_failed', str(exc)))
            return
        self.messages.put(('matcher_ready', matcher))

    def _capture(self, device) -> None:
        try:
            with device.recorder(samplerate=CAPTURE_RATE, channels=2, blocksize=4800) as recorder:
                while self.listening:
                    chunk = recorder.record(numframes=4800).astype(np.float32)
                    with self.audio_lock:
                        self.chunks.append(chunk)
        except Exception as exc:
            log_error('录音失败', exc)
            self.messages.put(('error', f'无法监听此设备：{exc}'))

    def _snapshot(self) -> np.ndarray | None:
        with self.audio_lock:
            chunks = list(self.chunks)
        if not chunks:
            return None
        return np.concatenate(chunks)[-int(CAPTURE_RATE * WINDOW_SECONDS):]

    def _submit(self) -> None:
        if self.busy or self.matcher is None:
            return
        snapshot = self._snapshot()
        if snapshot is None or len(snapshot) < CAPTURE_RATE // 2:
            return
        self.busy = True
        threading.Thread(target=self._recognize, args=(snapshot[-int(CAPTURE_RATE * 1.2):],), daemon=True).start()

    def _recognize(self, snapshot: np.ndarray) -> None:
        try:
            ranked, prominent = self.matcher.match_with_prominence(snapshot, CAPTURE_RATE, fast=True)
            self.messages.put(('match', ranked, prominent))
        except Exception as exc:
            log_error('识别失败', exc)
            self.messages.put(('error', f'识别失败：{exc}'))

    def _auto_tick(self) -> None:
        now = time.monotonic()
        if self.listening and self.auto.get() and now - self.last_auto > 0.25:
            self.last_auto = now
            self._submit()
        self.root.after(250, self._auto_tick)

    def _drain_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            kind = message[0]
            if kind == 'wheel':
                self._wheel_pending += message[1]
                steps, self._wheel_pending = divmod(self._wheel_pending, WHEEL_LINE)
                if steps:
                    self.results.yview_scroll(-steps, 'units')
                continue
            if kind == 'click':
                self._replay_click(message[1], message[2])
                continue
            if kind == 'hotkey':
                self._on_hotkey(message[1])
                continue
            if kind == 'matcher_ready':
                self.matcher = message[1]
                self.status.set('参考音效已加载，可以开始监听。')
                continue
            if kind == 'load_failed':
                self.status.set('参考音效加载失败，请查看日志。')
                self._alert('加载失败', f'参考音效加载失败：{message[1]}\n\n日志：{log_path()}')
                continue
            self.busy = False
            if kind == 'error':
                self.status.set(message[1])
                self.listening = False
                self.listen_button.configure(text='开始监听')
            elif kind == 'match':
                self._show(message[1], message[2])
        self.root.after(75, self._drain_messages)

    def _show(self, ranked: list[tuple[int, str, float]], prominent: list[tuple[int, str, float]]) -> None:
        if not ranked and not prominent:
            return
        cos_score = ranked[0][2] if ranked else 0.0
        cos_gap = cos_score - (ranked[1][2] if len(ranked) > 1 else 0.0)
        peak_score = prominent[0][2] if prominent else 0.0
        peak_gap = peak_score - (prominent[1][2] if len(prominent) > 1 else 0.0)
        if cos_score >= 0.24 and cos_gap >= 0.12:
            metric = 'cos'
        elif peak_score >= 7.0 and peak_gap >= 2.0:
            metric = 'peak'
            ranked = prominent
        else:
            self.tentative = None
            return
        sound_id, action, score = ranked[0]
        gap = score - (ranked[1][2] if len(ranked) > 1 else 0.0)
        if metric == 'peak':
            confidence = '音乐抗干扰匹配，建议复核'
        elif score >= 0.40 and gap >= 0.15:
            confidence = '快速匹配'
        else:
            confidence = '低音量匹配，建议复核'
        now = time.monotonic()
        previous = self.tentative
        count = previous[2] + 1 if previous and previous[0] == sound_id and now - previous[1] <= 1.0 else 1
        self.tentative = (sound_id, now, count)
        # 连续两次同一候选才算数；分数特别高时一次就认。
        if count < 2 and not (metric == 'cos' and score >= 0.75 and gap >= 0.30):
            return
        if self.last_match[0] != sound_id and now - self.last_match[1] < 0.75 and (metric == 'peak' or score < 0.75):
            return
        if self.last_match[0] == sound_id and now - self.last_match[1] < 3:
            return
        self.last_match = (sound_id, now)
        score_label = f'匹配分 {score*100:.0f}/100' if metric == 'cos' else f'音效峰值强度 {score:.1f}'
        self.last_confidence = confidence
        self.status.set('已识别。可用货物占格进一步筛选候选物品。')
        self._render(ranked[:3], metric)

    # ---------- 结果列表 ----------

    def _insert_row(self, segments: list[tuple[str, str, int, bool]], pady: int = 3) -> None:
        photo = ImageTk.PhotoImage(stroked_line(segments))
        self.photos.append(photo)
        self.results.image_create('end', image=photo, pady=pady)
        self.results.insert('end', '\n')

    def _render(self, ranked: list[tuple[int, str, float]], metric: str = 'cos') -> None:
        self.last_ranked = ranked
        self.last_metric = metric
        size = self.size.get()
        self.results.configure(state='normal')
        self.results.delete('1.0', 'end')
        self.photos.clear()
        for index, (sound_id, action, score) in enumerate(ranked, 1):
            items = [item for item in catalog()['items'] if item['soundId'] == sound_id]
            if size != '不限':
                a, b = map(int, size.split('×'))
                items = [item for item in items if sorted(item['size']) == sorted([a, b])]
            score_label = f'匹配分 {score*100:.0f}/100' if metric == 'cos' else f'音效峰值强度 {score:.1f}'
            action_label = '拾起' if action == 'pickup' else '放下'
            extra = f' · {self.last_confidence}' if self.last_confidence else ''
            header = f'{index}. 音效组 {sound_id} · {action_label}音效 · {score_label}{extra} · {len(items)} 件符合占格'
            self._insert_row([(header, '#9ad8f5', 12, True)], pady=9 if index > 1 else 3)
            if items:
                for item in sorted(items, key=lambda entry: entry.get('contactPrice') or 0, reverse=True):
                    price = item.get('contactPrice') or 0
                    category = item.get('category', '')
                    high = price > HIGH_VALUE_PRICE
                    self._insert_row([
                        (item['nameZh'], '#f4f9fd', 12, False),
                        (f"{item['size'][0]}×{item['size'][1]}", '#7fd4f5', 10, False),
                        (f'{price:,}', '#ff4d4f' if high else '#ffffff', 11, high),
                        (CATEGORY_ZH.get(category, category or '未分类'), '#ffd979', 10, False),
                    ])
            else:
                self._insert_row([('当前占格没有候选物品；请核对占格或再录一次。', '#7fd4f5', 10, False)])
        self.results.configure(state='disabled')
        self.results.yview_moveto(0)

    def _close(self) -> None:
        self.listening = False
        self.hotkeys.stop()
        self.hook.uninstall()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
