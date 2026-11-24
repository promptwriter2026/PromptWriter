"""Render the PromptWriter app icon (.ico multi-size + PNG preview).

Run from the repository root:  python tools/generate_app_icon.py
"""

import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ASSET_DIR = Path(__file__).resolve().parent.parent / "promptwriter" / "assets"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER_SIZE = 1024
SUPERSAMPLE = 4

BACKGROUND_TOP = (35, 42, 58, 255)
BACKGROUND_BOTTOM = (18, 22, 32, 255)
BORDER = (60, 72, 96, 255)
FOREGROUND = (247, 250, 255, 255)
ACCENT = (255, 200, 87, 255)
SECONDARY = (79, 209, 197, 255)


def _gradient(size, top, bottom):
    image = Image.new("RGBA", (1, size))
    for y in range(size):
        ratio = y / max(1, size - 1)
        color = tuple(
            round(top[index] + (bottom[index] - top[index]) * ratio)
            for index in range(3)
        )
        image.putpixel((0, y), (*color, 255))
    return image.resize((size, size), Image.Resampling.NEAREST)


def _thick_line(draw, points, width, fill):
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = width / 2
    for x, y in points:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def _spark_polygon(cx, cy, outer, inner):
    points = []
    for index in range(8):
        angle = math.radians(index * 45)
        radius = outer if index % 2 == 0 else inner
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def render(size):
    scale = (size * SUPERSAMPLE) / MASTER_SIZE
    canvas = size * SUPERSAMPLE

    def px(value):
        return value * scale

    icon = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    inset = px(36)
    radius = px(224)
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, canvas - inset - 1, canvas - inset - 1),
        radius=radius,
        fill=255,
    )

    background = _gradient(canvas, BACKGROUND_TOP, BACKGROUND_BOTTOM)
    icon.paste(background, (0, 0), mask)
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle(
        (inset, inset, canvas - inset - 1, canvas - inset - 1),
        radius=radius,
        outline=BORDER,
        width=max(2, round(px(10))),
    )

    chevron = [
        (px(0.315 * MASTER_SIZE), px(0.300 * MASTER_SIZE)),
        (px(0.545 * MASTER_SIZE), px(0.500 * MASTER_SIZE)),
        (px(0.315 * MASTER_SIZE), px(0.700 * MASTER_SIZE)),
    ]
    _thick_line(draw, chevron, max(2, round(px(116))), FOREGROUND)

    draw.rounded_rectangle(
        (
            px(0.610 * MASTER_SIZE),
            px(0.438 * MASTER_SIZE),
            px(0.830 * MASTER_SIZE),
            px(0.562 * MASTER_SIZE),
        ),
        radius=px(62),
        fill=FOREGROUND,
    )
    draw.rounded_rectangle(
        (
            px(0.610 * MASTER_SIZE),
            px(0.630 * MASTER_SIZE),
            px(0.762 * MASTER_SIZE),
            px(0.718 * MASTER_SIZE),
        ),
        radius=px(44),
        fill=SECONDARY,
    )

    draw.polygon(
        _spark_polygon(
            px(0.786 * MASTER_SIZE),
            px(0.240 * MASTER_SIZE),
            px(0.108 * MASTER_SIZE),
            px(0.030 * MASTER_SIZE),
        ),
        fill=ACCENT,
    )

    return icon.resize((size, size), Image.Resampling.LANCZOS)


def write_ico(path, sizes):
    frames = []
    for size in sizes:
        buffer = io.BytesIO()
        render(size).save(buffer, format="PNG")
        frames.append((size, buffer.getvalue()))

    header = struct.pack("<HHH", 0, 1, len(frames))
    entries = b""
    data = b""
    offset = 6 + 16 * len(frames)
    for size, payload in frames:
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            dimension,
            dimension,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)
        data += payload
    path.write_bytes(header + entries + data)


def main():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    render(MASTER_SIZE).save(ASSET_DIR / "promptwriter_preview.png")
    write_ico(ASSET_DIR / "promptwriter.ico", ICO_SIZES)
    print(f"Wrote {ASSET_DIR / 'promptwriter.ico'}")
    print(f"Wrote {ASSET_DIR / 'promptwriter_preview.png'}")


if __name__ == "__main__":
    main()
