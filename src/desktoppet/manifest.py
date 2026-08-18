"""Loading and validation for desktop-pet asset manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state_machine import PetState


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    file: Path
    duration_ms: int


@dataclass(frozen=True)
class Animation:
    name: str
    loop: bool
    interruptible_frames: tuple[int, ...]
    frames: tuple[Frame, ...]


@dataclass(frozen=True)
class PetManifest:
    pet_id: str
    name: str
    canvas: tuple[int, int]
    display_size: tuple[int, int]
    anchor: tuple[int, int]
    hitbox: tuple[int, int, int, int]
    animations: dict[str, Animation]
    root: Path

    def animation_for(self, state: PetState) -> Animation:
        return self.animations[state.value]


def _pair(value: Any, field: str, *, positive: bool = False) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(
        isinstance(item, int) for item in value
    ):
        raise ManifestError(f"{field} must contain two integers")
    result = (value[0], value[1])
    if positive and any(item <= 0 for item in result):
        raise ManifestError(f"{field} values must be positive")
    return result


def load_manifest(path: str | Path, *, check_files: bool = True) -> PetManifest:
    manifest_path = Path(path).resolve()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc

    if data.get("schema_version") != 1:
        raise ManifestError("schema_version must be 1")

    root = manifest_path.parent
    animations: dict[str, Animation] = {}
    raw_animations = data.get("animations")
    if not isinstance(raw_animations, dict):
        raise ManifestError("animations must be an object")

    for name, raw in raw_animations.items():
        if not isinstance(raw, dict) or not isinstance(raw.get("frames"), list):
            raise ManifestError(f"animation {name!r} must contain a frames list")
        frames: list[Frame] = []
        for index, item in enumerate(raw["frames"]):
            if not isinstance(item, dict) or not isinstance(item.get("file"), str):
                raise ManifestError(f"animation {name!r} frame {index} has no file")
            duration = item.get("duration_ms")
            if not isinstance(duration, int) or duration <= 0:
                raise ManifestError(
                    f"animation {name!r} frame {index} has invalid duration_ms"
                )
            frame_path = (root / item["file"]).resolve()
            if root not in frame_path.parents:
                raise ManifestError(f"animation {name!r} frame escapes pet directory")
            if check_files and not frame_path.is_file():
                raise ManifestError(f"missing frame: {frame_path}")
            frames.append(Frame(frame_path, duration))
        if not frames:
            raise ManifestError(f"animation {name!r} cannot be empty")
        interruptible = tuple(raw.get("interruptible_frames", []))
        if not all(isinstance(item, int) and 0 <= item < len(frames) for item in interruptible):
            raise ManifestError(f"animation {name!r} has invalid interruptible_frames")
        animations[name] = Animation(
            name=name,
            loop=bool(raw.get("loop", True)),
            interruptible_frames=interruptible,
            frames=tuple(frames),
        )

    required = {state.value for state in PetState}
    missing = required - animations.keys()
    if missing:
        raise ManifestError(f"missing required animations: {', '.join(sorted(missing))}")

    hitbox_raw = data.get("hitbox")
    if not isinstance(hitbox_raw, list) or len(hitbox_raw) != 4 or not all(
        isinstance(item, int) for item in hitbox_raw
    ):
        raise ManifestError("hitbox must contain four integers")

    pet_id = str(data.get("pet_id", "")).strip()
    name = str(data.get("name", "")).strip()
    if not pet_id or not name:
        raise ManifestError("pet_id and name cannot be empty")
    canvas = _pair(data.get("canvas"), "canvas", positive=True)
    display_size = _pair(data.get("display_size"), "display_size", positive=True)
    hitbox = (hitbox_raw[0], hitbox_raw[1], hitbox_raw[2], hitbox_raw[3])
    if hitbox[2] <= 0 or hitbox[3] <= 0:
        raise ManifestError("hitbox width and height must be positive")
    if hitbox[0] < 0 or hitbox[1] < 0 or hitbox[0] + hitbox[2] > canvas[0] or hitbox[1] + hitbox[3] > canvas[1]:
        raise ManifestError("hitbox must fit inside canvas")

    return PetManifest(
        pet_id=pet_id,
        name=name,
        canvas=canvas,
        display_size=display_size,
        anchor=_pair(data.get("anchor"), "anchor"),
        hitbox=hitbox,
        animations=animations,
        root=root,
    )
