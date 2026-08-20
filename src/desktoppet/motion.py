"""Deterministic motion builder for approved character action anchors."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw


CANVAS_SIZE = (512, 512)
FOOT_ANCHOR_Y = 492


@dataclass(frozen=True)
class MotionProfile:
    frames: int
    duration_ms: int
    scale_amplitude: float
    x_amplitude: float
    y_amplitude: float
    rotation_amplitude: float


PROFILES = {
    "idle": MotionProfile(12, 200, 0.010, 0.0, 1.5, 0.0),
    "hover": MotionProfile(12, 100, 0.008, 1.0, 2.5, 0.8),
    "loading": MotionProfile(16, 100, 0.006, 1.5, 1.0, 1.1),
    "working": MotionProfile(12, 100, 0.006, 1.2, 1.0, 0.35),
}

TRANSITIONS = (
    ("idle", "hover"),
    ("hover", "idle"),
    ("idle", "loading"),
    ("loading", "working"),
    ("working", "idle"),
)


def build_action_pack(
    source_dir: str | Path,
    destination: str | Path,
    *,
    pet_id: str = "m3-xiaogui",
    name: str = "小轨 M3",
) -> Path:
    source_root = Path(source_dir)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    normalized_dir = target / "anchors"
    normalized_dir.mkdir(exist_ok=True)

    animations: dict[str, list[Path]] = {}
    for state, profile in PROFILES.items():
        source = source_root / f"{state}_anchor.png"
        normalized = normalized_dir / f"{state}.png"
        normalize_transparent_anchor(source, normalized)
        animations[state] = build_motion_frames(
            normalized, target / state, profile=profile
        )

    transition_frames: dict[str, list[Path]] = {}
    transition_root = target / "transitions"
    for source, destination_state in TRANSITIONS:
        name_key = f"{source}_to_{destination_state}"
        transition_frames[name_key] = build_transition_frames(
            animations[source][-1],
            animations[destination_state][0],
            transition_root / name_key,
        )

    shutil.copy2(animations["idle"][0], target / "preview.webp")
    manifest = _manifest(pet_id, name, animations, transition_frames)
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest_path


def normalize_transparent_anchor(source: str | Path, destination: str | Path) -> Path:
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    if image.getchannel("A").getextrema() == (255, 255):
        for point in (
            (0, 0),
            (image.width - 1, 0),
            (0, image.height - 1),
            (image.width - 1, image.height - 1),
        ):
            ImageDraw.floodfill(image, point, (0, 0, 0, 0), thresh=32)
    alpha_box = image.getchannel("A").getbbox()
    if alpha_box is None:
        raise ValueError(f"anchor contains no visible pixels: {source}")
    character = image.crop(alpha_box)
    character.thumbnail((420, 462), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    canvas.alpha_composite(
        character,
        ((CANVAS_SIZE[0] - character.width) // 2, FOOT_ANCHOR_Y - character.height),
    )
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return output


def build_motion_frames(
    anchor: str | Path,
    output_dir: str | Path,
    *,
    profile: MotionProfile,
) -> list[Path]:
    with Image.open(anchor) as opened:
        base = opened.convert("RGBA")
    content_box = base.getchannel("A").getbbox()
    if content_box is None:
        raise ValueError("normalized anchor is empty")
    content = base.crop(content_box)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []

    for index in range(profile.frames):
        phase = math.tau * index / profile.frames
        scale = 1.0 + profile.scale_amplitude * math.sin(phase)
        width = max(1, round(content.width * scale))
        height = max(1, round(content.height * scale))
        transformed = content.resize((width, height), Image.Resampling.LANCZOS)
        angle = profile.rotation_amplitude * math.sin(phase)
        if angle:
            transformed = transformed.rotate(
                angle, Image.Resampling.BICUBIC, expand=True
            )
        visible_box = transformed.getchannel("A").getbbox()
        if visible_box is not None:
            transformed = transformed.crop(visible_box)
        x = round((CANVAS_SIZE[0] - transformed.width) / 2 + profile.x_amplitude * math.sin(phase * 2))
        foot_lift = min(profile.y_amplitude, 1.0) * math.sin(phase)
        y = round(FOOT_ANCHOR_Y - transformed.height - foot_lift)
        canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        canvas.alpha_composite(transformed, (x, y))
        path = destination / f"{index:03d}.webp"
        canvas.save(path, "WEBP", lossless=True, method=6)
        frames.append(path)
    return frames


def build_transition_frames(
    source: str | Path,
    destination: str | Path,
    output_dir: str | Path,
    *,
    frame_count: int = 6,
) -> list[Path]:
    with Image.open(source) as opened:
        first = opened.convert("RGBA")
    with Image.open(destination) as opened:
        last = opened.convert("RGBA")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    midpoint = frame_count // 2
    for index in range(frame_count):
        if index < midpoint:
            progress = index / max(1, midpoint - 1)
            frame = _fade_pose(
                first, scale=0.98 - 0.06 * progress, opacity=0.90 - 0.60 * progress
            )
        else:
            progress = (index - midpoint) / max(1, midpoint - 1)
            frame = _fade_pose(
                last, scale=0.92 + 0.06 * progress, opacity=0.30 + 0.60 * progress
            )
        path = output / f"{index:03d}.webp"
        frame.save(path, "WEBP", lossless=True, method=6)
        frames.append(path)
    return frames


def _fade_pose(image: Image.Image, *, scale: float, opacity: float) -> Image.Image:
    box = image.getchannel("A").getbbox()
    if box is None:
        return Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    content = image.crop(box)
    content = content.resize(
        (max(1, round(content.width * scale)), max(1, round(content.height * scale))),
        Image.Resampling.LANCZOS,
    )
    alpha = content.getchannel("A").point(lambda value: round(value * opacity))
    content.putalpha(alpha)
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    canvas.alpha_composite(
        content,
        ((CANVAS_SIZE[0] - content.width) // 2, FOOT_ANCHOR_Y - content.height),
    )
    return canvas


def _manifest(
    pet_id: str,
    name: str,
    animations: dict[str, list[Path]],
    transitions: dict[str, list[Path]],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for state, frames in animations.items():
        profile = PROFILES[state]
        payload[state] = {
            "loop": True,
            "interruptible_frames": [0, len(frames) // 2],
            "frames": [
                {"file": f"{state}/{frame.name}", "duration_ms": profile.duration_ms}
                for frame in frames
            ],
        }
    for name_key, frames in transitions.items():
        payload[name_key] = {
            "loop": False,
            "interruptible_frames": [len(frames) - 1],
            "frames": [
                {
                    "file": f"transitions/{name_key}/{frame.name}",
                    "duration_ms": 60,
                }
                for frame in frames
            ],
        }
    return {
        "schema_version": 1,
        "pet_id": pet_id,
        "name": name,
        "canvas": [512, 512],
        "display_size": [280, 280],
        "anchor": [256, FOOT_ANCHOR_Y],
        "hitbox": [46, 24, 420, 468],
        "default_facing": "right",
        "animations": payload,
    }
