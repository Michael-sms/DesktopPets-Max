import json
import tempfile
import unittest
from pathlib import Path

from desktoppet.manifest import ManifestError, load_manifest
from desktoppet.state_machine import PetState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_MANIFEST = PROJECT_ROOT / "assets" / "pets" / "prototype" / "manifest.json"


class ManifestTests(unittest.TestCase):
    def test_prototype_manifest_and_files_are_valid(self) -> None:
        manifest = load_manifest(PROTOTYPE_MANIFEST)

        self.assertEqual(manifest.pet_id, "prototype-orbit")
        self.assertEqual(set(manifest.animations), {state.value for state in PetState})
        self.assertTrue(all(frame.file.is_file() for animation in manifest.animations.values() for frame in animation.frames))

    def test_missing_required_animation_is_rejected(self) -> None:
        data = json.loads(PROTOTYPE_MANIFEST.read_text(encoding="utf-8"))
        del data["animations"]["working"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "missing required animations"):
                load_manifest(path, check_files=False)

    def test_frame_cannot_escape_pet_directory(self) -> None:
        data = json.loads(PROTOTYPE_MANIFEST.read_text(encoding="utf-8"))
        data["animations"]["idle"]["frames"][0]["file"] = "../outside.svg"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "escapes pet directory"):
                load_manifest(path, check_files=False)


if __name__ == "__main__":
    unittest.main()
