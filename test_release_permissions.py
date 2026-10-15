"""Regression: .command scripts work after GitHub ZIP downloads on macOS."""
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from tools.release_builder import add_zip_member


class ReleaseZipPermissions(unittest.TestCase):
    def test_macos_launchers_are_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            launcher = base / "install_mac.command"
            launcher.write_text("#!/bin/zsh\\necho hello\\n", encoding="utf-8")
            launcher.chmod(0o644)  # Mimic files uploaded through GitHub's web UI.
            text_file = base / "README.txt"
            text_file.write_text("Readme", encoding="utf-8")
            bundle = base / "release.zip"
            with ZipFile(bundle, "w") as zf:
                add_zip_member(zf, launcher, "patch/install_mac.command")
                add_zip_member(zf, text_file, "patch/README.txt")
            with ZipFile(bundle) as zf:
                script = zf.getinfo("patch/install_mac.command")
                self.assertEqual(script.create_system, 3)
                self.assertEqual((script.external_attr >> 16) & 0o777, 0o755)
                self.assertEqual((zf.getinfo("patch/README.txt").external_attr >> 16) & 0o111, 0)
                self.assertEqual(zf.read("patch/install_mac.command"), launcher.read_bytes())


if __name__ == "__main__":
    unittest.main()
