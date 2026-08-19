"""Local-only photo validation and palette extraction."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .models import PhotoReport


SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PhotoValidationError(ValueError):
    pass


def validate_photo(path: str | Path) -> PhotoReport:
    image_path = Path(path)
    try:
        with Image.open(image_path) as opened:
            image_format = (opened.format or "").upper()
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise PhotoValidationError(f"无法读取图片：{exc}") from exc

    width, height = image.size
    warnings: list[str] = []
    errors: list[str] = []
    if image_format not in SUPPORTED_FORMATS:
        errors.append("仅支持 JPG、PNG、WebP")
    if min(width, height) < 512:
        errors.append("图片短边必须至少为 512 px")
    elif min(width, height) < 1024:
        warnings.append("图片短边低于推荐的 1024 px")
    if max(width, height) / min(width, height) > 4:
        warnings.append("图片比例过长，主体可能难以完整裁切")

    sample = ImageOps.contain(image.convert("L"), (256, 256))
    brightness = float(ImageStat.Stat(sample).mean[0])
    edge_energy = float(ImageStat.Stat(sample.filter(ImageFilter.FIND_EDGES)).rms[0])
    if brightness < 35:
        warnings.append("图片整体偏暗，建议使用光线更均匀的照片")
    elif brightness > 225:
        warnings.append("图片整体过亮，面部细节可能丢失")
    if edge_energy < 12:
        warnings.append("图片细节较少或可能失焦")

    return PhotoReport(
        width=width,
        height=height,
        format=image_format,
        brightness=round(brightness, 1),
        edge_energy=round(edge_energy, 1),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def dominant_palette(path: str | Path, count: int = 3) -> tuple[str, ...]:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    sample = ImageOps.contain(image, (160, 160))
    quantized = sample.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    ranked = sorted(quantized.getcolors() or [], reverse=True)
    colors: list[str] = []
    for _, index in ranked[:count]:
        offset = index * 3
        red, green, blue = palette[offset : offset + 3]
        colors.append(f"#{red:02X}{green:02X}{blue:02X}")
    defaults = ["#6878E8", "#27324A", "#72E2D1"]
    return tuple((colors + defaults)[:count])
