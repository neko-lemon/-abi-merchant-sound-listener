"""把结果行画成图片：Tk 字体没有描边，PIL 可以画真正的黑边。"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

STROKE_WIDTH = 2
YAHEI_FILES = {False: r'C:\Windows\Fonts\msyh.ttc', True: r'C:\Windows\Fonts\msyhbd.ttc'}
_FONTS: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def yahei(point_size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """按 Tk 的点数换算成像素，取微软雅黑。"""
    key = (point_size, bold)
    font = _FONTS.get(key)
    if font is None:
        pixels = max(8, round(point_size * 96 / 72))
        for path in (YAHEI_FILES[bold], YAHEI_FILES[False]):
            try:
                font = ImageFont.truetype(path, pixels)
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default()
        _FONTS[key] = font
    return font


def stroked_line(segments: list[tuple[str, str, int, bool]], gap: float = 8.0, indent: float = 12.0) -> Image.Image:
    """把一行分段的彩色文字画成一张带黑色描边的透明底图。"""
    parts = []
    for text, color, point_size, bold in segments:
        font = yahei(point_size, bold)
        ascent, descent = font.getmetrics()
        parts.append((text, color, font, float(font.getlength(text)), ascent, descent))
    width = indent + sum(part[3] for part in parts) + gap * max(0, len(parts) - 1) + STROKE_WIDTH * 2 + 2
    baseline = max(part[4] for part in parts) + STROKE_WIDTH + 1
    height = baseline + max(part[5] for part in parts) + STROKE_WIDTH + 1
    image = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    x = indent + STROKE_WIDTH
    for text, color, font, length, ascent, _descent in parts:
        draw.text((x, baseline - ascent), text, font=font, fill=color, stroke_width=STROKE_WIDTH, stroke_fill='black')
        x += length + gap
    return image
