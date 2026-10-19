"""7.7 updater regressions: accepts only data-only patches, verifies and rolls back."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os
from zipfile import ZipFile

from orbit_update import (
    UpdateError, version_tuple, safe_path, validate_manifest,
    stage_archive, install_staged, read_version, digest,
)
from orbit_version import CLIENT_VERSION
from orbit_messenger_logic import validate_dropped_files


class UpdateCoreTests(unittest.TestCase):
    def test_version_and_safe_paths(self):
        self.assertEqual(CLIENT_VERSION,'7.8.3')
        self.assertLess(version_tuple('v7.6.3'),version_tuple('7.7.0'))
        self.assertEqual(str(safe_path('orbit_drum.py')),'orbit_drum.py')
        for bad in ('README.md','../settings.json','client_defaults.json',
                    'tools/evil.py','.orbitclip/secrets.json',
                    'assets/../client_defaults.json','C:\\evil.py',
                    'test_inject.py'):
            with self.subTest(bad=bad):
                with self.assertRaises(UpdateError):
                    safe_path(bad)

    def _make(self,folder,corrupt=False):
        app=folder/'app'
        app.mkdir()
        old=b"APP_NAME='ORBITclip'\nCLIENT_VERSION='7.6.3'\n"
        new=b"APP_NAME='ORBITclip'\nCLIENT_VERSION='7.7.0'\n"
        (app/'orbit_version.py').write_bytes(old)
        (app/'README.md').write_text('user edited documentation')
        (app/'client_defaults.json').write_text('private user config')
        patch=folder/'patch.zip'
        manifest={'app':'ORBITclip','from_version':'7.6.3','to_version':'7.7.0',
                  'changes':[{'path':'orbit_version.py','before':digest(old),
                              'after':digest(new) if not corrupt else 'a'*64}]}
        with ZipFile(patch,'w') as z:
            z.writestr('ORBITclip_Patch_v7_7_0/manifest.json',json.dumps(manifest))
            z.writestr('ORBITclip_Patch_v7_7_0/payload/orbit_version.py',new)
            # Malicious installer code in ZIP must NEVER be executed.
            z.writestr('ORBITclip_Patch_v7_7_0/apply_patch.py',
                       "raise RuntimeError('ZIP code was executed')")
        return app,patch

    def test_verified_offline_patch_preserves_local_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,patch=self._make(Path(tmp))
            stage,manifest=stage_archive(patch,app)
            self.assertEqual(manifest['to_version'],'7.7.0')
            self.assertFalse((stage/'apply_patch.py').exists())
            self.assertEqual(read_version(app),'7.6.3')
            self.assertEqual(install_staged(stage,app),'7.7.0')
            self.assertEqual(read_version(app),'7.7.0')
            self.assertEqual((app/'README.md').read_text(),'user edited documentation')
            self.assertEqual((app/'client_defaults.json').read_text(),'private user config')
            backup=app/'.orbitclip_patch_backups'/'v7.6.3_to_v7.7.0'
            self.assertTrue((backup/'orbit_version.py').is_file())

    def test_install_rollback_when_replace_raises_after_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,archive=self._make(Path(tmp))
            stage,_=stage_archive(archive,app)
            original=(app/'orbit_version.py').read_bytes()
            import orbit_update
            actual=orbit_update.os.replace
            called=[False]
            def interrupted(source,dest):
                actual(source,dest)
                if not called[0]:
                    called[0]=True
                    raise OSError("simulated crash after atomic replacement")
            with patch('orbit_update.os.replace',side_effect=interrupted):
                with self.assertRaises(OSError):
                    install_staged(stage,app)
            self.assertTrue(called[0])
            self.assertEqual(read_version(app),'7.6.3')
            self.assertEqual((app/'orbit_version.py').read_bytes(),original)

    def test_wrong_hash_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,patch=self._make(Path(tmp),corrupt=True)
            with self.assertRaises(UpdateError):
                stage_archive(patch,app)
            self.assertEqual(read_version(app),'7.6.3')
            self.assertFalse((app/'.orbitclip_patch_backups').exists())

    def test_changed_source_and_downgrade_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,patch=self._make(Path(tmp))
            (app/'orbit_version.py').write_text("APP_NAME='ORBITclip'\nCLIENT_VERSION='7.6.3'\n# locally edited\n")
            with self.assertRaises(UpdateError):
                stage_archive(patch,app)

    def test_attachment_review_uses_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'small.txt';a.write_text('hello')
            b=Path(tmp)/'oversize.bin'
            with b.open('wb') as out:
                out.truncate(42_500_000)
            accepted,rejected=validate_dropped_files([a,b])
            self.assertEqual([item[0].name for item in accepted],['small.txt'])
            self.assertEqual(len(rejected),1)


if __name__=='__main__':
    unittest.main()
