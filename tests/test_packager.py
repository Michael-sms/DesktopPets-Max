import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from desktoppet.manifest import load_manifest
from desktoppet.packager import PackageError, build_package, install_package
from desktoppet.quality import inspect_package


def make_frame(path: Path, *, color: tuple[int, int, int, int], x: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (80, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((x, 10, x + 38, 96), 8, fill=color)
    image.save(path)


def make_recipe(root: Path) -> Path:
    for state, color in {
        "idle": (70, 90, 220, 255),
        "loading": (80, 210, 190, 255),
        "working": (120, 100, 230, 255),
    }.items():
        make_frame(root / state / "00.png", color=color)
        make_frame(root / state / "01.png", color=color, x=21)

    sheet = Image.new("RGBA", (160, 100), (0, 0, 0, 0))
    for index in range(2):
        cell = Image.new("RGBA", (80, 100), (0, 0, 0, 0))
        ImageDraw.Draw(cell).ellipse((20 + index, 10, 58 + index, 96), fill=(245, 140, 180, 255))
        sheet.alpha_composite(cell, (index * 80, 0))
    sheet.save(root / "hover_sheet.png")
    (root / "character_spec.json").write_text(
        json.dumps({"name": "测试角色", "locked_traits": ["蓝色服装"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    recipe = {
        "schema_version": 1,
        "pet_id": "m4-test-pet",
        "name": "M4 测试角色",
        "canvas": [128, 128],
        "display_size": [256, 256],
        "anchor": [64, 120],
        "hitbox": [8, 8, 112, 112],
        "animations": {
            "idle": {"source": "idle", "duration_ms": [180, 220]},
            "hover": {"source": "hover_sheet.png", "grid": [2, 1], "frame_count": 2},
            "loading": {"source": "loading"},
            "working": {"source": "working"},
        },
    }
    path = root / "pet-package.json"
    path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
    return path


class PackageTests(unittest.TestCase):
    def test_build_splits_cleans_checks_and_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = make_recipe(root / "source")
            archive = root / "m4-test.petpack"
            manifest_path, report = build_package(recipe, root / "built", archive_path=archive)

            manifest = load_manifest(manifest_path)
            self.assertTrue(report.passed)
            self.assertEqual(report.frame_count, 8)
            self.assertEqual(len(manifest.animations["hover"].frames), 2)
            self.assertEqual([frame.duration_ms for frame in manifest.animations["idle"].frames], [180, 220])
            self.assertTrue((manifest_path.parent / "preview.webp").is_file())
            self.assertTrue((manifest_path.parent / "character_spec.json").is_file())
            self.assertTrue((manifest_path.parent / "quality_report.json").is_file())
            with Image.open(manifest.animations["hover"].frames[0].file) as frame:
                self.assertEqual(frame.size, (128, 128))
                self.assertEqual(frame.mode, "RGBA")
            with zipfile.ZipFile(archive) as package:
                self.assertIn("manifest.json", package.namelist())

    def test_petpack_installs_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = make_recipe(root / "source")
            archive = root / "m4-test.petpack"
            build_package(recipe, root / "built", archive_path=archive)

            manifest_path, report = install_package(archive, root / "pets")

            self.assertEqual(manifest_path.parent.name, "m4-test-pet")
            self.assertTrue(report.passed)
            self.assertEqual(load_manifest(manifest_path).pet_id, "m4-test-pet")

    def test_unsafe_archive_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.petpack"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("../outside.txt", "bad")
            with self.assertRaisesRegex(PackageError, "不安全路径"):
                install_package(archive, root / "pets")

    def test_pet_id_cannot_escape_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = make_recipe(root / "source")
            data = json.loads(recipe.read_text(encoding="utf-8"))
            data["pet_id"] = "../outside"
            recipe.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(PackageError, "pet_id"):
                build_package(recipe, root / "built")

    def test_quality_check_reports_non_rgba_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = make_recipe(root / "source")
            manifest_path, _ = build_package(recipe, root / "built")
            manifest = load_manifest(manifest_path)
            broken = manifest.animations["idle"].frames[0].file
            Image.new("RGB", (128, 128), "white").save(broken, "WEBP", lossless=True)

            report = inspect_package(manifest_path)

            self.assertFalse(report.passed)
            self.assertIn("alpha_channel", {item.code for item in report.issues})
            self.assertIn("opaque_background", {item.code for item in report.issues})


if __name__ == "__main__":
    unittest.main()
