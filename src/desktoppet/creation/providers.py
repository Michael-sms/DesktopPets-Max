"""Replaceable candidate/pose generation providers."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageEnhance

from .models import CharacterSpec


class GenerationProvider(Protocol):
    name: str

    def generate_candidates(
        self, source: Path, spec: CharacterSpec, output_dir: Path
    ) -> list[Path]: ...

    def generate_pose_sheet(
        self, anchor: Path, spec: CharacterSpec, destination: Path
    ) -> Path: ...


class BundledSampleProvider:
    """Deterministic provider for review and offline tests, never for user identity."""

    name = "bundled-sample"

    def __init__(self, anchor: Path, pose_sheet: Path) -> None:
        self.anchor = anchor
        self.pose_sheet = pose_sheet

    def generate_candidates(
        self, source: Path, spec: CharacterSpec, output_dir: Path
    ) -> list[Path]:
        del source, spec
        output_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(self.anchor) as opened:
            base = opened.convert("RGBA")
        results: list[Path] = []
        for index, color_factor in enumerate((0.88, 1.0, 1.14), start=1):
            candidate = ImageEnhance.Color(base).enhance(color_factor)
            path = output_dir / f"candidate_{index}.png"
            candidate.save(path)
            results.append(path)
        return results

    def generate_pose_sheet(
        self, anchor: Path, spec: CharacterSpec, destination: Path
    ) -> Path:
        del anchor, spec
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.pose_sheet, destination)
        return destination


class OpenAIImageProvider:
    """Optional real image provider; imported only when explicitly configured."""

    name = "openai-gpt-image-2"

    def __init__(self, model: str = "gpt-image-2") -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "未安装 AI 可选依赖，请运行：uv sync --extra ai"
            ) from exc
        self._client = OpenAI()
        self.model = model

    def generate_candidates(
        self, source: Path, spec: CharacterSpec, output_dir: Path
    ) -> list[Path]:
        prompt = _candidate_prompt(spec)
        output_dir.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as image_file:
            result = self._client.images.edit(
                model=self.model,
                image=image_file,
                prompt=prompt,
                n=3,
                size="1024x1024",
                quality="medium",
            )
        paths: list[Path] = []
        for index, item in enumerate(result.data, start=1):
            path = output_dir / f"candidate_{index}.png"
            path.write_bytes(base64.b64decode(item.b64_json))
            _make_border_transparent(path)
            paths.append(path)
        return paths

    def generate_pose_sheet(
        self, anchor: Path, spec: CharacterSpec, destination: Path
    ) -> Path:
        with anchor.open("rb") as image_file:
            result = self._client.images.edit(
                model=self.model,
                image=image_file,
                prompt=_pose_prompt(spec),
                size="1024x1024",
                quality="medium",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.b64decode(result.data[0].b64_json))
        return destination


def _candidate_prompt(spec: CharacterSpec) -> str:
    payload = json.dumps(spec.__dict__, ensure_ascii=False)
    return (
        "Use case: identity-preserve. Convert the person or pet in the input photo "
        "into one polished anime chibi desktop-pet character. Preserve recognizable "
        "facial features, hair, key clothing colors and accessories. Full body, 2.7-head "
        "proportions, neutral three-quarter standing pose, centered, solid pure white "
        "background, crisp outline, restrained cel shading. Exactly one character; no "
        "text, watermark, shadow, extra props or cropped body parts. Character spec: "
        + payload
    )


def _pose_prompt(spec: CharacterSpec) -> str:
    return (
        "Use case: identity-preserve. Create a square 2x2 production pose sheet of the "
        "exact same character: front, three-quarter facing right, side profile facing "
        "right, and gentle idle-breath peak. Keep face, proportions, hair, outfit and "
        "palette unchanged. Light neutral grid background, four aligned full-body figures, "
        "no labels, text, props, watermark or cropping. Locked traits: "
        + ", ".join(spec.locked_traits)
    )


def _make_border_transparent(path: Path) -> None:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    for point in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
        ImageDraw.floodfill(image, point, (0, 0, 0, 0), thresh=28)
    image.save(path)
