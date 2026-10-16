"""Release packaging guard: patch files must exist in clean first-install bundle."""
import unittest
from pathlib import Path
from tools.release_builder import patchable_path


class PatchBundleContractTests(unittest.TestCase):
    def test_runtime_files_allowed(self):
        for value in (
            'orbitclip.py', 'orbit_version.py', 'orbit_drum.py',
            'orbit_drum_layout.py', 'orbit_palette.py',
            'requirements-client.txt', 'start_windows.bat',
            'start_mac.command', 'assets/orbit_icon.png',
        ):
            with self.subTest(value=value):
                self.assertTrue(patchable_path(Path(value)), value)

    def test_readme_and_unshipped_files_never_required(self):
        for value in (
            'README.md', 'client_defaults.json', 'docs/releases/v7.6.1.md',
            'test_v760.py', 'test_v761_qt.py', 'tools/release_builder.py',
            'patches/v7.5.1/file.py', '.github/workflows/release.yml',
            'my-notes.txt', 'assets/readme.md', '../orbitclip.py',
        ):
            with self.subTest(value=value):
                self.assertFalse(patchable_path(Path(value)), value)


if __name__ == '__main__':
    unittest.main()
