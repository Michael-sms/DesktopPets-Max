"""Automated quality checks for packaged desktop-pet animation assets."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .manifest import ManifestError, PetManifest, load_manifest


MAIN_ANIMATIONS = {"idle", "hover", "loading", "working"}


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    code: str
    animation: str | None
    frame: int | None
    message: str


@dataclass(frozen=True)
class QualityReport:
    manifest: str
    passed: bool
    animation_count: int
    frame_count: int
    issues: tuple[QualityIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest,
            "passed": self.passed,
            "animation_count": self.animation_count,
            "frame_count": self.frame_count,
            "summary": {
                "errors": sum(item.severity == "error" for item in self.issues),
                "warnings": sum(item.severity == "warning" for item in self.issues),
            },
            "issues": [asdict(item) for item in self.issues],
        }

    def write(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output


def inspect_package(manifest_path: str | Path) -> QualityReport:
    """Inspect structural, alpha, anchor, palette, outline and loop continuity."""

    source = Path(manifest_path).resolve()
    try:
        manifest = load_manifest(source)
    except ManifestError as exc:
        issue = QualityIssue("error", "manifest", None, None, str(exc))
        return QualityReport(str(source), False, 0, 0, (issue,))

    issues: list[QualityIssue] = []
    frame_count = 0
    for name, animation in manifest.animations.items():
        images: list[Image.Image] = []
        bottoms: list[int] = []
        luminance: list[float] = []
        colors: list[tuple[float, float, float]] = []
        areas: list[int] = []
        for index, frame in enumerate(animation.frames):
            frame_count += 1
            try:
                with Image.open(frame.file) as opened:
                    bands = opened.getbands()
                    size = opened.size
                    image = opened.convert("RGBA")
            except (OSError, ValueError) as exc:
                issues.append(
                    QualityIssue("error", "unreadable", name, index, str(exc))
                )
                continue
            images.append(image)
            if size != manifest.canvas:
                issues.append(
                    QualityIssue(
                        "error", "canvas_size", name, index,
                        f"expected {manifest.canvas[0]}x{manifest.canvas[1]}, got {size[0]}x{size[1]}",
                    )
                )
            if "A" not in bands:
                issues.append(
                    QualityIssue("error", "alpha_channel", name, index, "frame has no alpha channel")
                )
            alpha = image.getchannel("A")
            extrema = alpha.getextrema()
            box = alpha.getbbox()
            if box is None:
                issues.append(
                    QualityIssue("error", "empty_frame", name, index, "frame has no visible pixels")
                )
                continue
            if extrema[0] != 0:
                issues.append(
                    QualityIssue("error", "opaque_background", name, index, "frame has no transparent pixels")
                )
            if box[0] == 0 or box[1] == 0 or box[2] == size[0] or box[3] == size[1]:
                issues.append(
                    QualityIssue("error", "canvas_edge", name, index, "visible pixels touch the canvas edge")
                )
            bottoms.append(box[3])
            areas.append((box[2] - box[0]) * (box[3] - box[1]))
            luminance.append(_visible_luminance(image))
            colors.append(_visible_color(image))

        if name in MAIN_ANIMATIONS and bottoms:
            drift = max(bottoms) - min(bottoms)
            if drift > 2:
                issues.append(
                    QualityIssue("error", "anchor_drift", name, None, f"bottom anchor drifts by {drift}px")
                )
            median_bottom = round(statistics.median(bottoms))
            if abs(median_bottom - manifest.anchor[1]) > 2:
                issues.append(
                    QualityIssue(
                        "error", "anchor_position", name, None,
                        f"bottom anchor is y={median_bottom}, expected y={manifest.anchor[1]}",
                    )
                )
        for index in range(1, min(len(luminance), len(areas))):
            if abs(luminance[index] - luminance[index - 1]) > 28:
                issues.append(
                    QualityIssue("warning", "brightness_jump", name, index, "visible brightness changes abruptly")
                )
            if math.dist(colors[index], colors[index - 1]) > 48:
                issues.append(
                    QualityIssue("warning", "palette_jump", name, index, "visible average color changes abruptly")
                )
            previous_area = max(1, areas[index - 1])
            if abs(areas[index] - previous_area) / previous_area > 0.35:
                issues.append(
                    QualityIssue("warning", "outline_jump", name, index, "visible outline area changes abruptly")
                )
        if animation.loop and len(images) > 1 and _alpha_difference(images[-1], images[0]) > 0.30:
            issues.append(
                QualityIssue("warning", "loop_jump", name, None, "last-to-first alpha silhouette differs substantially")
            )

    passed = not any(item.severity == "error" for item in issues)
    return QualityReport(
        str(source), passed, len(manifest.animations), frame_count, tuple(issues)
    )


def _visible_luminance(image: Image.Image) -> float:
    alpha = image.getchannel("A")
    grayscale = image.convert("L")
    mean = ImageStat.Stat(grayscale, mask=alpha).mean
    return mean[0] if mean else 0.0


def _visible_color(image: Image.Image) -> tuple[float, float, float]:
    mean = ImageStat.Stat(image.convert("RGB"), mask=image.getchannel("A")).mean
    return mean[0], mean[1], mean[2]


def _alpha_difference(first: Image.Image, second: Image.Image) -> float:
    difference = ImageChops.difference(first.getchannel("A"), second.getchannel("A"))
    return ImageStat.Stat(difference).mean[0] / 255.0
