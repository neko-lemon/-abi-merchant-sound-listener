"""参考音效匹配：带通滤波后的归一化互相关。"""

from __future__ import annotations

import math

import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, resample_poly, sosfilt

from resources import BASE, catalog

SAMPLE_RATE = 24000
CAPTURE_RATE = 48000


def mono_24k(data: np.ndarray, input_rate: int) -> np.ndarray:
    """混成单声道并重采样到 24 kHz。"""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if input_rate == SAMPLE_RATE:
        return data
    if input_rate == CAPTURE_RATE:
        return resample_poly(data, 1, 2).astype(np.float32)
    factor = math.gcd(input_rate, SAMPLE_RATE)
    return resample_poly(data, SAMPLE_RATE // factor, input_rate // factor).astype(np.float32)


class Matcher:
    """加载 reference/ 下的 76 段音效，给出候选声音组与置信度线索。"""

    def __init__(self) -> None:
        self.filter = butter(3, (180, 8500), btype='bandpass', fs=SAMPLE_RATE, output='sos')
        self.music_filter = butter(3, (1600, 9500), btype='bandpass', fs=SAMPLE_RATE, output='sos')
        self.refs: list[tuple[int, str, np.ndarray, float]] = []
        self.fast_refs: list[tuple[int, str, np.ndarray, float]] = []
        self.music_refs: list[tuple[int, str, np.ndarray, float]] = []
        self.fast_music_refs: list[tuple[int, str, np.ndarray, float]] = []
        for sound in catalog()['sounds']:
            for action in ('pickup', 'drop'):
                path = BASE / 'reference' / (sound[action] + '.ogg')
                data, rate = sf.read(str(path), dtype='float32')
                mono = mono_24k(data, rate)
                for sound_filter, full_refs, fast_refs in (
                    (self.filter, self.refs, self.fast_refs),
                    (self.music_filter, self.music_refs, self.fast_music_refs),
                ):
                    waveform = sosfilt(sound_filter, mono).astype(np.float32)
                    # 尾部的安静段受游戏音量和重叠声音影响最大，先裁掉。
                    power = np.convolve(waveform * waveform, np.ones(240) / 240, mode='same')
                    active = np.flatnonzero(power > power.max() * 0.015)
                    if len(active):
                        lo = max(0, int(active[0]) - 480)
                        hi = min(len(waveform), int(active[-1]) + 480)
                        waveform = waveform[lo:hi]
                    energy = float(np.dot(waveform, waveform))
                    full_refs.append((sound['id'], action, waveform, energy))
                    prefix = waveform[:min(len(waveform), int(0.30 * SAMPLE_RATE))]
                    fast_refs.append((sound['id'], action, prefix, float(np.dot(prefix, prefix))))

    def match_with_prominence(
        self, data: np.ndarray, rate: int, fast: bool = False
    ) -> tuple[list[tuple[int, str, float]], list[tuple[int, str, float]]]:
        """返回（余弦候选、混音峰值候选），元素为 (声音组, 拾起/放下, 分数)。"""
        mono = mono_24k(data, rate)
        if len(mono) < 5000 or float(np.max(np.abs(mono))) < 0.0002:
            return [], []
        best: dict[int, tuple[str, float]] = {}
        prominent: dict[int, tuple[str, float]] = {}
        for sound_filter, refs in (
            (self.filter, self.fast_refs if fast else self.refs),
            (self.music_filter, self.fast_music_refs if fast else self.music_refs),
        ):
            signal = sosfilt(sound_filter, mono).astype(np.float32)
            cosine, peaks = self._match_signal(signal, refs)
            for sound_id, (action, score) in cosine.items():
                if sound_id not in best or score > best[sound_id][1]:
                    best[sound_id] = (action, score)
            for sound_id, (action, score) in peaks.items():
                if sound_id not in prominent or score > prominent[sound_id][1]:
                    prominent[sound_id] = (action, score)

        def ranked(scores):
            return sorted(
                ((sid, action, score) for sid, (action, score) in scores.items()),
                key=lambda entry: entry[2],
                reverse=True,
            )

        return ranked(best), ranked(prominent)

    @staticmethod
    def _match_signal(
        signal: np.ndarray, refs: list[tuple[int, str, np.ndarray, float]]
    ) -> tuple[dict[int, tuple[str, float]], dict[int, tuple[str, float]]]:
        integral = np.r_[0.0, np.cumsum(signal.astype(np.float64) ** 2)]
        best: dict[int, tuple[str, float]] = {}
        prominent: dict[int, tuple[str, float]] = {}
        for sound_id, action, reference, energy in refs:
            length = len(reference)
            if length > len(signal) or energy <= 0:
                continue
            numerator = fftconvolve(signal, reference[::-1], mode='valid')
            center = float(np.mean(numerator))
            spread = max(float(np.std(numerator)), 1e-12)
            peak = max(0.0, (float(np.max(numerator)) - center) / spread)
            if sound_id not in prominent or peak > prominent[sound_id][1]:
                prominent[sound_id] = (action, peak)
            local_energy = np.maximum(integral[length:] - integral[:-length], 0.0)
            # 近乎静音的窗口会因浮点误差让归一化越界，先剔掉再比。
            energy_floor = max(float(local_energy.max()) * 1e-6, length * 1e-10)
            valid = local_energy > energy_floor
            if not np.any(valid):
                continue
            normalized = numerator[valid] / np.sqrt(local_energy[valid] * energy)
            score = float(np.clip(np.max(normalized), 0.0, 1.0))
            if sound_id not in best or score > best[sound_id][1]:
                best[sound_id] = (action, score)
        return best, prominent
