"""M6 builder for genuine pose-changing transparent frame animations."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from .motion import CANVAS_SIZE, FOOT_ANCHOR_Y


STATE_DURATIONS = {
    "idle": 180,
    "hover": 90,
    "loading": 100,
    "working": 83,
}
POSE_ORDER = (0, 1, 2, 3, 2, 1)
TRANSITION_SOURCES = {
    "idle_to_hover": (("idle", 0), ("idle", 1), ("hover", 0), ("hover", 1), ("hover", 2), ("hover", 3)),
    "hover_to_idle": (("hover", 8), ("hover", 9), ("hover", 10), ("idle", 0), ("idle", 1), ("idle", 2)),
    "idle_to_loading": (("idle", 0), ("idle", 1), ("loading", 0), ("loading", 1), ("loading", 2), ("loading", 3)),
    "loading_to_working": (
        ("loading", 8),
        ("loading", 9),
        ("loading", 10),
        ("working", 0),
        ("working", 1),
        ("working", 2),
    ),
    "working_to_idle": (("working", 8), ("working", 9), ("working", 10), ("idle", 0), ("idle", 1), ("idle", 2)),
}


def build_frame_animation_pack(
    source_dir: str | Path,
    destination: str | Path,
    *,
    pet_id: str = "m6-xiaogui",
    name: str = "小轨 M6 动态版",
) -> Path:
    source_root = Path(source_dir)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    keypose_root = target / "keyposes"
    keypose_root.mkdir(exist_ok=True)

    keyposes: dict[str, list[Path]] = {}
    animations: dict[str, list[Path]] = {}
    for state in STATE_DURATIONS:
        keyposes[state] = split_pose_sheet(
            source_root / f"{state}_sheet.png", keypose_root / state
        )
        animations[state] = build_pose_loop(keyposes[state], target / state)

    look_keyposes = split_pose_sheet(
        source_root / "idle_look_sheet.png", keypose_root / "idle_variant_look"
    )
    idle_variant = build_pose_loop(
        look_keyposes,
        target / "idle_variant_look",
        order=(0, 1, 2, 3, 0),
        variants_per_pose=2,
    )

    transitions: dict[str, list[Path]] = {}
    for transition, sources in TRANSITION_SOURCES.items():
        output = target / "transitions" / transition
        output.mkdir(parents=True, exist_ok=True)
        transitions[transition] = []
        for index, (state, frame_index) in enumerate(sources):
            path = output / f"{index:03d}.png"
            shutil.copy2(animations[state][frame_index], path)
            transitions[transition].append(path)

    shutil.copy2(animations["idle"][0], target / "preview.png")
    manifest = _manifest(pet_id, name, animations, transitions, idle_variant)
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "generation_metadata.json").write_text(
        json.dumps(
            {
                "milestone": "M6",
                "animation_route": "transparent_pose_keyframes",
                "source": "identity-preserving generated 2x2 key-pose sheets",
                "main_loops": 4,
                "transition_clips": 5,
                "random_idle_clips": 1,
                "generated_frame_count": sum(len(item) for item in animations.values())
                + sum(len(item) for item in transitions.values())
                + len(idle_variant),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def split_pose_sheet(sheet_path: str | Path, output_dir: str | Path) -> list[Path]:
    sheet_source = Path(sheet_path)
    with Image.open(sheet_source) as opened:
        sheet = opened.convert("RGBA")
    cell_width = sheet.width // 2
    cell_height = sheet.height // 2
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError(f"invalid pose sheet: {sheet_path}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    poses: list[Path] = []
    for index in range(4):
        column, row = index % 2, index // 2
        cell = sheet.crop(
            (
                column * cell_width,
                row * cell_height,
                (column + 1) * cell_width,
                (row + 1) * cell_height,
            )
        )
        cleaned = _remove_connected_background(cell)
        if row == 1 and sheet_source.stem == "working_sheet":
            # The generated lower cells overlap the preceding row by a thin shoe strip.
            ImageDraw.Draw(cleaned).rectangle(
                (0, 0, cleaned.width, round(cleaned.height * 0.045)),
                fill=(0, 0, 0, 0),
            )
            _remove_background_islands(cleaned)
        normalized = _normalize_pose(cleaned)
        path = output / f"{index:03d}.png"
        normalized.save(path, optimize=True)
        poses.append(path)
    return poses


def build_pose_loop(
    keyposes: list[Path],
    output_dir: str | Path,
    *,
    order: tuple[int, ...] = POSE_ORDER,
    variants_per_pose: int = 2,
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for pose_index in order:
        with Image.open(keyposes[pose_index]) as opened:
            pose = opened.convert("RGBA")
        for variant in range(variants_per_pose):
            frame = _micro_motion(pose, variant)
            path = output / f"{len(frames):03d}.png"
            frame.save(path, "PNG", optimize=True)
            frames.append(path)
    return frames


def _remove_connected_background(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    if image.getchannel("A").getextrema()[0] < 255:
        return image
    _remove_bright_checkerboard(image)
    for point in (
        (0, 0),
        (image.width - 1, 0),
    ):
        ImageDraw.floodfill(image, point, (0, 0, 0, 0), thresh=38)
    _remove_straight_background_guides(image)
    _remove_background_islands(image)
    return image


def _remove_bright_checkerboard(image: Image.Image) -> None:
    """Erase generated faux-transparency even when it touches the character.

    Image generators sometimes paint a light checkerboard instead of emitting an
    alpha channel.  Flood fill alone cannot remove a checker cell that is joined
    to a shoe or prop.  Large locally neutral areas are safe to erase here; small
    white highlights remain because their neighbourhood contains coloured line
    art rather than more checker pixels.
    """

    pixels = image.load()
    width, height = image.size
    border = (
        [pixels[x, 0][:3] for x in range(width)]
        + [pixels[x, height - 1][:3] for x in range(width)]
        + [pixels[0, y][:3] for y in range(height)]
        + [pixels[width - 1, y][:3] for y in range(height)]
    )
    palette = [
        colour
        for colour, count in Counter(border).most_common(32)
        if count >= 8
        and min(colour) >= 232
        and max(colour) - min(colour) <= 10
    ]
    if not palette:
        return
    candidate = bytearray(width * height)
    for y in range(height):
        offset = y * width
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            candidate[offset + x] = int(
                alpha > 0
                and any(
                    max(abs(red - pr), abs(green - pg), abs(blue - pb)) <= 2
                    for pr, pg, pb in palette
                )
            )

    # Summed-area table keeps the neighbourhood test linear in pixel count.
    stride = width + 1
    integral = [0] * ((height + 1) * stride)
    for y in range(height):
        row_sum = 0
        source_offset = y * width
        target_offset = (y + 1) * stride
        previous_offset = y * stride
        for x in range(width):
            row_sum += candidate[source_offset + x]
            integral[target_offset + x + 1] = integral[previous_offset + x + 1] + row_sum

    radius = 6
    to_clear: list[tuple[int, int]] = []
    for y in range(height):
        y0, y1 = max(0, y - radius), min(height, y + radius + 1)
        for x in range(width):
            if not candidate[y * width + x]:
                continue
            x0, x1 = max(0, x - radius), min(width, x + radius + 1)
            neutral_count = (
                integral[y1 * stride + x1]
                - integral[y0 * stride + x1]
                - integral[y1 * stride + x0]
                + integral[y0 * stride + x0]
            )
            area = (x1 - x0) * (y1 - y0)
            if neutral_count / area >= 0.82:
                to_clear.append((x, y))
    for x, y in to_clear:
        pixels[x, y] = (0, 0, 0, 0)


def _remove_straight_background_guides(image: Image.Image) -> None:
    """Remove thin neutral grid/guideline strokes painted into generated sheets."""

    pixels = image.load()
    width, height = image.size

    def neutral(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        return (
            alpha > 0
            and min(red, green, blue) >= 195
            and max(red, green, blue) - min(red, green, blue) <= 24
        )

    marked: set[tuple[int, int]] = set()
    minimum_run = max(18, min(width, height) // 28)
    for y in range(height):
        start = None
        for x in range(width + 1):
            if x < width and neutral(x, y):
                start = x if start is None else start
            elif start is not None:
                if x - start >= minimum_run:
                    for run_x in range(start, x):
                        thickness = sum(
                            neutral(run_x, near_y)
                            for near_y in range(max(0, y - 4), min(height, y + 5))
                        )
                        if thickness <= 3:
                            marked.add((run_x, y))
                start = None
    for x in range(width):
        start = None
        for y in range(height + 1):
            if y < height and neutral(x, y):
                start = y if start is None else start
            elif start is not None:
                if y - start >= minimum_run:
                    for run_y in range(start, y):
                        thickness = sum(
                            neutral(near_x, run_y)
                            for near_x in range(max(0, x - 4), min(width, x + 5))
                        )
                        if thickness <= 3:
                            marked.add((x, run_y))
                start = None

    # Preserve white costume/highlight pixels close to coloured line art. Grid
    # strokes extend through otherwise empty space and have no such neighbours.
    safe_to_clear: list[tuple[int, int]] = []
    for x, y in marked:
        near_coloured_subject = False
        for near_y in range(max(0, y - 4), min(height, y + 5)):
            for near_x in range(max(0, x - 4), min(width, x + 5)):
                red, green, blue, alpha = pixels[near_x, near_y]
                if alpha and (
                    min(red, green, blue) < 195
                    or max(red, green, blue) - min(red, green, blue) > 24
                ):
                    near_coloured_subject = True
                    break
            if near_coloured_subject:
                break
        if not near_coloured_subject:
            safe_to_clear.append((x, y))
    for x, y in safe_to_clear:
        pixels[x, y] = (0, 0, 0, 0)


def _remove_background_islands(image: Image.Image) -> None:
    """Remove checkerboard cells and adjacent-panel fragments after flood fill."""

    pixels = image.load()
    width, height = image.size
    visited = bytearray(width * height)
    components: list[tuple[list[tuple[int, int]], bool, int, int, int]] = []
    for start_y in range(height):
        for start_x in range(width):
            flat = start_y * width + start_x
            if visited[flat] or pixels[start_x, start_y][3] == 0:
                continue
            stack = [(start_x, start_y)]
            visited[flat] = 1
            points: list[tuple[int, int]] = []
            touches_edge = False
            saturation_total = 0
            cyan_pixels = 0
            while stack:
                x, y = stack.pop()
                points.append((x, y))
                red, green, blue, _ = pixels[x, y]
                saturation_total += max(red, green, blue) - min(red, green, blue)
                cyan_pixels += (
                    blue > 180
                    and green > 155
                    and red < 150
                    and blue > red * 1.35
                )
                touches_edge |= x == 0 or y == 0 or x == width - 1 or y == height - 1
                for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if not 0 <= next_x < width or not 0 <= next_y < height:
                        continue
                    next_flat = next_y * width + next_x
                    if visited[next_flat] or pixels[next_x, next_y][3] == 0:
                        continue
                    visited[next_flat] = 1
                    stack.append((next_x, next_y))
            components.append(
                (points, touches_edge, len(points), saturation_total, cyan_pixels)
            )
    if not components:
        return
    largest = max(components, key=lambda item: item[2])
    for component in components:
        points, touches_edge, size, saturation_total, cyan_pixels = component
        average_saturation = saturation_total / max(1, size)
        cyan_ratio = cyan_pixels / max(1, size)
        keep = component is largest or (
            not touches_edge
            and size >= 8
            and average_saturation >= 35
            and cyan_ratio >= 0.45
        )
        if not keep:
            for x, y in points:
                pixels[x, y] = (0, 0, 0, 0)


def _normalize_pose(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").getbbox()
    if box is None:
        raise ValueError("pose contains no visible pixels after background removal")
    content = _sanitize_transparent_rgb(image.crop(box))
    content.thumbnail((430, 468), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    canvas.alpha_composite(
        content,
        ((CANVAS_SIZE[0] - content.width) // 2, FOOT_ANCHOR_Y - content.height),
    )
    return canvas


def _micro_motion(image: Image.Image, variant: int) -> Image.Image:
    box = image.getchannel("A").getbbox()
    if box is None:
        return image.copy()
    content = _sanitize_transparent_rgb(image.crop(box))
    scale = 1.0 if variant == 0 else 1.004
    content = content.resize(
        (max(1, round(content.width * scale)), max(1, round(content.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    x = round((CANVAS_SIZE[0] - content.width) / 2 + (1 if variant else 0))
    y = FOOT_ANCHOR_Y - content.height - (1 if variant else 0)
    canvas.alpha_composite(content, (x, y))
    return canvas


def _sanitize_transparent_rgb(image: Image.Image) -> Image.Image:
    clean = Image.new("RGBA", image.size, (0, 0, 0, 0))
    clean.alpha_composite(image)
    return clean


def _manifest(
    pet_id: str,
    name: str,
    animations: dict[str, list[Path]],
    transitions: dict[str, list[Path]],
    idle_variant: list[Path],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for state, frames in animations.items():
        payload[state] = {
            "loop": True,
            "interruptible_frames": list(range(len(frames))),
            "frames": [
                {"file": f"{state}/{frame.name}", "duration_ms": STATE_DURATIONS[state]}
                for frame in frames
            ],
        }
    for transition, frames in transitions.items():
        payload[transition] = {
            "loop": False,
            "interruptible_frames": [len(frames) - 1],
            "frames": [
                {
                    "file": f"transitions/{transition}/{frame.name}",
                    "duration_ms": 83,
                }
                for frame in frames
            ],
        }
    payload["idle_variant_look"] = {
        "loop": False,
        "interruptible_frames": [len(idle_variant) - 1],
        "frames": [
            {"file": f"idle_variant_look/{frame.name}", "duration_ms": 140}
            for frame in idle_variant
        ],
    }
    return {
        "schema_version": 1,
        "pet_id": pet_id,
        "name": name,
        "canvas": [512, 512],
        "display_size": [280, 280],
        "anchor": [256, FOOT_ANCHOR_Y],
        "hitbox": [41, 20, 430, 472],
        "default_facing": "right",
        "asset_version": "2.0.0",
        "m6_features": [
            "pose-changing frame loops",
            "blink and breathing",
            "animated hands, gaze and props",
            "random idle look-around",
        ],
        "animations": payload,
    }
