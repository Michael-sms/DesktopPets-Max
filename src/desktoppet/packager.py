"""Build, archive and install importable desktop-pet asset packages."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from .quality import QualityReport, inspect_package


SUPPORTED_FRAMES = {".png", ".webp"}


class PackageError(ValueError):
    pass


def build_package(
    recipe_path: str | Path,
    destination: str | Path,
    *,
    archive_path: str | Path | None = None,
) -> tuple[Path, QualityReport]:
    """Build an import-ready directory transactionally from a JSON recipe."""

    recipe_file = Path(recipe_path).resolve()
    recipe = _read_recipe(recipe_file)
    source_root = recipe_file.parent
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(f"目标目录已存在：{target}")
    archive = Path(archive_path).resolve() if archive_path is not None else None
    if archive is not None:
        if archive.suffix.lower() != ".petpack":
            raise PackageError("安装包扩展名必须为 .petpack")
        if archive.exists():
            raise FileExistsError(f"安装包已存在：{archive}")
        if target == archive.parent or target in archive.parents:
            raise PackageError("安装包不能写在尚未完成的目标目录内")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="desktoppet-pack-", dir=target.parent) as temporary:
        staging = Path(temporary) / target.name
        staging.mkdir()
        animations: dict[str, object] = {}
        canvas = _pair(recipe.get("canvas", [512, 512]), "canvas", positive=True)
        anchor = _pair(recipe.get("anchor", [canvas[0] // 2, canvas[1] - 20]), "anchor")
        raw_animations = recipe.get("animations")
        if not isinstance(raw_animations, dict):
            raise PackageError("animations 必须是对象")
        required = {"idle", "hover", "loading", "working"}
        missing = required - raw_animations.keys()
        if missing:
            raise PackageError(f"缺少主状态：{', '.join(sorted(missing))}")

        for name, raw in raw_animations.items():
            if not isinstance(raw, dict):
                raise PackageError(f"动画 {name} 配置无效")
            frames = _source_frames(source_root, raw)
            if not frames:
                raise PackageError(f"动画 {name} 没有可用帧")
            output_dir = staging / (f"transitions/{name}" if "_to_" in name else name)
            output_dir.mkdir(parents=True)
            output_frames: list[Path] = []
            for index, frame in enumerate(frames):
                cleaned = _clean_frame(frame, canvas, anchor)
                output = output_dir / f"{index:03d}.webp"
                cleaned.save(output, "WEBP", lossless=True, method=6)
                output_frames.append(output)
            durations = _durations(raw, len(output_frames))
            relative_dir = output_dir.relative_to(staging).as_posix()
            loop = bool(raw.get("loop", "_to_" not in name))
            animations[name] = {
                "loop": loop,
                "interruptible_frames": _interruptible(raw, len(output_frames), loop),
                "frames": [
                    {"file": f"{relative_dir}/{frame.name}", "duration_ms": durations[index]}
                    for index, frame in enumerate(output_frames)
                ],
            }

        manifest = {
            "schema_version": 1,
            "pet_id": _pet_id(recipe),
            "name": _required_text(recipe, "name"),
            "canvas": list(canvas),
            "display_size": list(_pair(recipe.get("display_size", [280, 280]), "display_size", positive=True)),
            "anchor": list(anchor),
            "hitbox": list(_quad(recipe.get("hitbox", [24, 24, canvas[0] - 48, canvas[1] - 44]), "hitbox")),
            "default_facing": recipe.get("default_facing", "right"),
            "asset_version": str(recipe.get("asset_version", "1.0.0")),
            "animations": animations,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _copy_character_spec(source_root, recipe, staging)
        shutil.copy2(staging / "idle" / "000.webp", staging / "preview.webp")

        report = inspect_package(manifest_path)
        report.write(staging / "quality_report.json")
        if not report.passed:
            messages = "; ".join(item.message for item in report.issues if item.severity == "error")
            raise PackageError(f"自动质检未通过：{messages}")
        staging.replace(target)

    manifest_path = target / "manifest.json"
    final_report = inspect_package(manifest_path)
    final_report.write(target / "quality_report.json")
    if archive is not None:
        _write_archive(target, archive)
    return manifest_path, final_report


def install_package(archive_path: str | Path, pets_root: str | Path) -> tuple[Path, QualityReport]:
    """Safely validate and install one .petpack archive into a pets directory."""

    archive = Path(archive_path).resolve()
    destination_root = Path(pets_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="desktoppet-install-", dir=destination_root) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise PackageError("安装包包含不安全路径")
            package.extractall(staging)
        manifest_path = staging / "manifest.json"
        report = inspect_package(manifest_path)
        if not report.passed:
            raise PackageError("安装包自动质检未通过")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pet_id = _pet_id(manifest)
        target = destination_root / pet_id
        if target.exists():
            raise FileExistsError(f"角色已存在：{target}")
        staging.replace(target)
    return target / "manifest.json", inspect_package(target / "manifest.json")


def _read_recipe(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"无法读取打包配置：{exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise PackageError("打包配置 schema_version 必须为 1")
    return data


def _source_frames(root: Path, raw: dict[str, Any]) -> list[Image.Image]:
    source_value = raw.get("source")
    if not isinstance(source_value, str):
        raise PackageError("动画 source 必须是相对路径")
    source = (root / source_value).resolve()
    if root != source and root not in source.parents:
        raise PackageError("动画 source 不能离开配置目录")
    if source.is_dir():
        paths = sorted(path for path in source.iterdir() if path.suffix.lower() in SUPPORTED_FRAMES)
        return [_open_rgba(path) for path in paths]
    if not source.is_file():
        raise PackageError(f"找不到动画源：{source_value}")
    grid = raw.get("grid")
    if grid is None:
        return [_open_rgba(source)]
    columns, rows = _pair(grid, "grid", positive=True)
    sheet = _open_rgba(source)
    if sheet.width % columns or sheet.height % rows:
        raise PackageError(f"sprite sheet 无法按 {columns}x{rows} 等分")
    width, height = sheet.width // columns, sheet.height // rows
    count = raw.get("frame_count", columns * rows)
    if not isinstance(count, int) or not 1 <= count <= columns * rows:
        raise PackageError("frame_count 超出 sprite sheet 网格范围")
    return [
        sheet.crop(((index % columns) * width, (index // columns) * height,
                    (index % columns + 1) * width, (index // columns + 1) * height))
        for index in range(count)
    ]


def _clean_frame(image: Image.Image, canvas: tuple[int, int], anchor: tuple[int, int]) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(lambda value: 0 if value <= 2 else value)
    image.putalpha(alpha)
    box = alpha.getbbox()
    if box is None:
        raise PackageError("源动画包含空白帧")
    content = image.crop(box)
    maximum = (max(1, canvas[0] - 2), max(1, anchor[1] - 1))
    content.thumbnail(maximum, Image.Resampling.LANCZOS)
    x = round(anchor[0] - content.width / 2)
    y = anchor[1] - content.height
    if x <= 0 or x + content.width >= canvas[0] or y <= 0:
        scale = min(
            (canvas[0] - 2) / content.width,
            (anchor[1] - 1) / content.height,
        )
        content = content.resize(
            (max(1, round(content.width * scale)), max(1, round(content.height * scale))),
            Image.Resampling.LANCZOS,
        )
        x = round(anchor[0] - content.width / 2)
        y = anchor[1] - content.height
    result = Image.new("RGBA", canvas, (0, 0, 0, 0))
    result.alpha_composite(content, (x, y))
    return result


def _durations(raw: dict[str, Any], count: int) -> list[int]:
    value = raw.get("duration_ms", 100)
    values = value if isinstance(value, list) else [value] * count
    if len(values) != count or not all(isinstance(item, int) and item > 0 for item in values):
        raise PackageError("duration_ms 必须是正整数，或与帧数相同的正整数列表")
    return values


def _interruptible(raw: dict[str, Any], count: int, loop: bool) -> list[int]:
    value = raw.get("interruptible_frames", [0, count // 2] if loop else [count - 1])
    if not isinstance(value, list) or not all(isinstance(item, int) and 0 <= item < count for item in value):
        raise PackageError("interruptible_frames 包含无效帧序号")
    return value


def _copy_character_spec(root: Path, recipe: dict[str, Any], target: Path) -> None:
    value = recipe.get("character_spec", "character_spec.json")
    if not isinstance(value, str):
        raise PackageError("character_spec 必须是相对路径")
    source = (root / value).resolve()
    if root != source and root not in source.parents:
        raise PackageError("character_spec 不能离开配置目录")
    if not source.is_file():
        raise PackageError(f"找不到角色设定：{value}")
    shutil.copy2(source, target / "character_spec.json")


def _write_archive(root: Path, archive: Path) -> None:
    if archive.suffix.lower() != ".petpack":
        raise PackageError("安装包扩展名必须为 .petpack")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise FileExistsError(f"安装包已存在：{archive}")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as package:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            package.write(path, path.relative_to(root).as_posix())


def _open_rgba(path: Path) -> Image.Image:
    try:
        with Image.open(path) as opened:
            return opened.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise PackageError(f"无法读取图片 {path.name}：{exc}") from exc


def _required_text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PackageError(f"{field} 不能为空")
    return value.strip()


def _pet_id(data: dict[str, Any]) -> str:
    value = _required_text(data, "pet_id")
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is None:
        raise PackageError("pet_id 只能包含小写字母、数字、点、下划线和连字符")
    return value


def _pair(value: Any, field: str, *, positive: bool = False) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) for item in value):
        raise PackageError(f"{field} 必须包含两个整数")
    result = (value[0], value[1])
    if positive and any(item <= 0 for item in result):
        raise PackageError(f"{field} 必须为正数")
    return result


def _quad(value: Any, field: str) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(item, int) for item in value):
        raise PackageError(f"{field} 必须包含四个整数")
    return value[0], value[1], value[2], value[3]
