"""叠在游戏画面上的识别面板。"""

from __future__ import annotations

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
from winutil import Hotkeys, log_error, log_path

WINDOW_BG = '#101824'
WINDOW_SECONDS = 2.3
HIGH_VALUE_PRICE = 1_000_000
MOD_ALT = 0x0001
HOTKEY_LISTEN = 1
HOTKEY_HIDE = 2
HOTKEY_KEYS = {(MOD_ALT, 0x34): HOTKEY_LISTEN, (MOD_ALT, 0x35): HOTKEY_HIDE}  # Alt+4 / Alt+5


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
        self.hotkeys = Hotkeys(HOTKEY_KEYS)

        self._build()
        self.status.trace_add('write', self._sync_status_label)
        self._apply_transparency()
        self._apply_opacity()
        self._toggle_pin()

        self.hotkeys.start(lambda hotkey_id: self.messages.put(('hotkey', hotkey_id)))
        threading.Thread(target=self._load_matcher, daemon=True, name='matcher').start()

        root.after(75, self._drain_messages)
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
        self.opacity_scale = tk.Scale(overlay, from_=30, to=100, orient='horizontal', variable=self.panel_opacity,
                                      command=lambda _value: self._apply_opacity(), length=160, showvalue=True,
                                      bg=WINDOW_BG, fg='#d7e4ee', troughcolor='#142231', activebackground='#2a4763',
                                      highlightthickness=0, bd=0, relief='flat', sliderrelief='flat',
                                      font=('Microsoft YaHei UI', 9))
        self.opacity_scale.pack(side='left', padx=(18, 0))

        # 高价规格提示：有超过 100 万的规格时才出现。
        self.hint = ttk.Label(frame, text='', foreground='#ffd979', font=('Microsoft YaHei UI', 10))
        # 状态行只在有话说的时候才出现。
        self.status_label = ttk.Label(frame, textvariable=self.status, foreground='#85bce9')

        result_frame = ttk.Frame(frame)
        self.result_frame = result_frame
        result_frame.pack(fill='both', expand=True, pady=(0, 8))
        self.results = tk.Frame(result_frame, bg=WINDOW_BG)
        self.results.pack(fill='both', expand=True)
        self.results.columnconfigure(0, weight=1, uniform='column')
        self.results.columnconfigure(1, weight=1, uniform='column')

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
        self._render(ranked[:1], metric)

    # ---------- 结果区（两列） ----------

    def _row_photo(self, segments: list[tuple[str, str, int, bool]]) -> ImageTk.PhotoImage:
        photo = ImageTk.PhotoImage(stroked_line(segments))
        self.photos.append(photo)
        return photo

    def _update_buy_hint(self, ranked: list[tuple[int, str, float]]) -> None:
        """某个音效组的某个规格里有超过 100 万的物品，就提示该买哪个规格。"""
        best: dict[tuple[int, int], int] = {}
        for sound_id, _action, _score in ranked:
            for item in catalog()['items']:
                if item['soundId'] != sound_id:
                    continue
                price = item.get('contactPrice') or 0
                if price > HIGH_VALUE_PRICE:
                    key = tuple(item['size'])
                    best[key] = max(best.get(key, 0), price)
        if not best:
            self.hint.pack_forget()
            return
        text = '、'.join(f'买{a}×{b}' for a, b in sorted(best, key=lambda size: -best[size]))
        self.hint.configure(text=text)
        if not self.hint.winfo_manager():
            self.hint.pack(anchor='w', pady=(0, 6), before=self.result_frame)

    def _render(self, ranked: list[tuple[int, str, float]], metric: str = 'cos') -> None:
        self.last_ranked = ranked
        self.last_metric = metric
        size = self.size.get()
        for child in self.results.winfo_children():
            child.destroy()
        self.photos.clear()
        self._update_buy_hint(ranked)
        row = 0
        for sound_id, action, score in ranked:
            items = [item for item in catalog()['items'] if item['soundId'] == sound_id]
            if size != '不限':
                a, b = map(int, size.split('×'))
                items = [item for item in items if sorted(item['size']) == sorted([a, b])]
            score_label = f'匹配分 {score*100:.0f}/100' if metric == 'cos' else f'音效峰值强度 {score:.1f}'
            action_label = '拾起' if action == 'pickup' else '放下'
            extra = f' · {self.last_confidence}' if self.last_confidence else ''
            header = f'音效组 {sound_id} · {action_label}音效 · {score_label}{extra} · {len(items)} 件符合占格'
            tk.Label(self.results, image=self._row_photo([(header, '#9ad8f5', 12, True)]),
                     bg=WINDOW_BG, bd=0, anchor='w').grid(
                row=row, column=0, columnspan=2, sticky='w', pady=(8 if row else 2, 3))
            row += 1
            if not items:
                tk.Label(self.results,
                         image=self._row_photo([('当前占格没有候选物品；请核对占格或再录一次。', '#7fd4f5', 10, False)]),
                         bg=WINDOW_BG, bd=0, anchor='w').grid(row=row, column=0, columnspan=2, sticky='w', pady=2)
                row += 1
                continue
            ordered = sorted(items, key=lambda entry: entry.get('contactPrice') or 0, reverse=True)
            for index, item in enumerate(ordered):
                price = item.get('contactPrice') or 0
                category = item.get('category', '')
                high = price > HIGH_VALUE_PRICE
                photo = self._row_photo([
                    (item['nameZh'], '#f4f9fd', 12, False),
                    (f"{item['size'][0]}×{item['size'][1]}", '#7fd4f5', 10, False),
                    (f'{price:,}', '#ff4d4f' if high else '#ffffff', 11, high),
                    (CATEGORY_ZH.get(category, category or '未分类'), '#ffd979', 10, False),
                ])
                tk.Label(self.results, image=photo, bg=WINDOW_BG, bd=0, anchor='w').grid(
                    row=row + index // 2, column=index % 2, sticky='w', padx=(0, 10), pady=1)
            row += (len(ordered) + 1) // 2

    def _close(self) -> None:
        self.listening = False
        self.hotkeys.stop()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
