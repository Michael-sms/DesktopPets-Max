import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from desktoppet.creation.models import ProjectStage
from desktoppet.creation.photo import PhotoValidationError, validate_photo
from desktoppet.creation.project import approve_candidate, create_project, generate_candidates
from desktoppet.creation.providers import BundledSampleProvider
from desktoppet.manifest import load_manifest


def make_source(path: Path, size: tuple[int, int] = (1024, 1024)) -> None:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((256, 80, 768, 592), fill=(255, 220, 200, 255))
    draw.rounded_rectangle((300, 500, 724, 980), 60, fill=(80, 100, 220, 255))
    image.save(path)


class CreationTests(unittest.TestCase):
    def test_unreadable_photo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.png"
            path.write_text("not an image", encoding="utf-8")
            with self.assertRaises(PhotoValidationError):
                validate_photo(path)

    def test_small_photo_report_contains_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.png"
            make_source(path, (320, 320))
            report = validate_photo(path)
            self.assertFalse(report.accepted)
            self.assertIn("图片短边必须至少为 512 px", report.errors)

    def test_rights_confirmation_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            make_source(source)
            with self.assertRaisesRegex(ValueError, "使用授权"):
                create_project(source, root / "projects", name="测试", rights_confirmed=False)

    def test_offline_project_reaches_approved_idle_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            pose = root / "pose.png"
            make_source(source)
            make_source(pose)
            project = create_project(
                source, root / "projects", name="Test Pet", rights_confirmed=True
            )
            provider = BundledSampleProvider(source, pose)

            generate_candidates(project, provider)
            manifest_path = approve_candidate(
                project, provider, 1, root / "approved-pet"
            )
            manifest = load_manifest(manifest_path)

            self.assertEqual(project.stage, ProjectStage.APPROVED)
            self.assertEqual(len(project.candidate_files), 3)
            self.assertEqual(len(manifest.animations["idle"].frames), 12)
            self.assertTrue((manifest_path.parent / "approval.json").is_file())
            with Image.open(manifest.animations["idle"].frames[0].file) as frame:
                self.assertEqual(frame.size, (512, 512))
                self.assertEqual(frame.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
