"""Build a drift-free idle animation from one approved transparent anchor."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image


def normalize_anchor(source: str | Path, destination: str | Path) -> Path:
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    alpha_box = image.getchannel("A").getbbox()
    if alpha_box:
        image = image.crop(alpha_box)
    image.thumbnail((390, 450), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    x = (512 - image.width) // 2
    y = 492 - image.height
    canvas.alpha_composite(image, (x, y))
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return output


def build_idle_frames(
    anchor: str | Path, output_dir: str | Path, *, frame_count: int = 12
) -> list[Path]:
    with Image.open(anchor) as opened:
        base = opened.convert("RGBA")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []

    for index in range(frame_count):
        phase = math.tau * index / frame_count
        scale_y = 1.0 + 0.010 * math.sin(phase)
        offset_y = round(-1.5 * math.sin(phase))
        height = max(1, round(base.height * scale_y))
        transformed = base.resize((base.width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
        y = base.height - transformed.height + offset_y
        canvas.alpha_composite(transformed, (0, y))
        path = destination / f"idle_{index:03d}.png"
        canvas.save(path, optimize=True)
        frames.append(path)
    return frames
