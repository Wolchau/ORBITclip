"""Regression: full-release upgrade works without ANY intermediate patch.

Tests are entirely offline, including rollback after an already written file.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from orbit_update import UpdateError, read_version
from orbit_update_full import (
    MANIFEST, stage_snapshot, install_snapshot, validate_snapshot_manifest,
    digest, _checked_plan,
)


def code(version):
    return ("APP_NAME='ORBITclip'\nCLIENT_VERSION='" + version + "'\n").encode()


def manifest(version, payload):
    return {"schema":1, "app":"ORBITclip", "version":version,
            "files":{path:{"sha256":digest(data),"size":len(data)}
                     for path,data in payload.items()}}


def write_archive(path, version, payload, bad_hash=False):
    data=manifest(version,payload)
    if bad_hash:
        data["files"]["orbit_version.py"]["sha256"]="0"*64
    with ZipFile(path,"w") as z:
        z.writestr("ORBITclip/"+MANIFEST,json.dumps(data,sort_keys=True))
        for name,raw in payload.items():
            z.writestr("ORBITclip/"+name,raw)
        # Defaults must NEVER overwrite user's own configuration.
        z.writestr("ORBITclip/client_defaults.json",'{"https_token":""}')
    return path


class OneHopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.target=self.root/"installed"
        self.target.mkdir()
        self.old={"orbit_version.py":code("7.8.2"),
                  "launcher.py":b"print('launcher')\n",
                  "feature.py":b"first version\n",
                  "assets/obsolete.svg":b"<svg>obsolete</svg>"}
        for name,raw in self.old.items():
            dest=self.target/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(raw)
        (self.target/MANIFEST).write_text(
            json.dumps(manifest("7.8.2",self.old),sort_keys=True),encoding="utf-8")
        (self.target/"client_defaults.json").write_text("SECRET USER TOKEN")
        (self.target/"custom.json").write_text("USER DATA")
        (self.target/".venv").mkdir()
        (self.target/".venv"/"marker").write_text("PRESERVE")
        self.new={"orbit_version.py":code("7.9.3"),
                  "launcher.py":self.old["launcher.py"],
                  "feature.py":b"great new features\n",
                  "new_module.py":b"print('new')\n"}
        self.archive=write_archive(self.root/"release.zip","7.9.3",self.new)

    def test_skip_any_number_of_versions_with_single_archive(self):
        stage,plan=stage_snapshot(self.archive,self.target)
        self.assertEqual(plan["from_version"],"7.8.2")
        self.assertEqual(plan["to_version"],"7.9.3")
        self.assertEqual(read_version(self.target),"7.8.2")
        self.assertNotIn("launcher.py",plan["changes"])
        self.assertIn("assets/obsolete.svg",plan["changes"])
        self.assertEqual(install_snapshot(stage,self.target),"7.9.3")
        self.assertEqual(read_version(self.target),"7.9.3")
        self.assertFalse((self.target/"assets/obsolete.svg").exists())
        self.assertTrue((self.target/"new_module.py").is_file())
        self.assertEqual((self.target/"feature.py").read_bytes(),self.new["feature.py"])
        self.assertEqual((self.target/"custom.json").read_text(),"USER DATA")
        self.assertEqual((self.target/"client_defaults.json").read_text(),"SECRET USER TOKEN")
        self.assertEqual((self.target/".venv"/"marker").read_text(),"PRESERVE")
        backups=self.target/".orbitclip_patch_backups"/"snapshots"/"v7.8.2_to_v7.9.3"
        self.assertEqual((backups/"files"/"feature.py").read_bytes(),b"first version\n")
        self.assertEqual(json.loads((backups/"transaction.json").read_text())["state"],"committed")

    def test_corrupted_download_does_not_modify_client(self):
        corrupt=write_archive(self.root/"corrupt.zip","7.9.3",self.new,bad_hash=True)
        with self.assertRaises(UpdateError):
            stage_snapshot(corrupt,self.target)
        self.assertEqual(read_version(self.target),"7.8.2")
        self.assertFalse((self.target/".orbitclip_patch_backups").exists())

    def test_modified_managed_file_blocks_update_safely(self):
        (self.target/"feature.py").write_bytes(b"local modifications")
        with self.assertRaisesRegex(UpdateError,"Изменён"):
            stage_snapshot(self.archive,self.target)
        self.assertEqual(read_version(self.target),"7.8.2")

    def test_injected_failure_restores_every_file(self):
        stage,plan=stage_snapshot(self.archive,self.target)
        import orbit_update_full
        original_replace=os.replace
        count=[0]
        def interrupt(src,dst):
            original_replace(src,dst)
            if str(dst).endswith("feature.py"):
                count[0]+=1
                raise OSError("Simulated I/O failure after atomic rename")
        with patch.object(orbit_update_full.os,"replace",side_effect=interrupt):
            with self.assertRaises(OSError):
                install_snapshot(stage,self.target)
        self.assertEqual(count[0],1)
        self.assertEqual(read_version(self.target),"7.8.2")
        self.assertEqual((self.target/"feature.py").read_bytes(),self.old["feature.py"])
        self.assertEqual((self.target/"assets/obsolete.svg").read_bytes(),
                         self.old["assets/obsolete.svg"])
        self.assertFalse((self.target/"new_module.py").exists())
        self.assertEqual((self.target/"client_defaults.json").read_text(),"SECRET USER TOKEN")
        backups=self.target/".orbitclip_patch_backups"/"snapshots"/"v7.8.2_to_v7.9.3"
        self.assertEqual(json.loads((backups/"transaction.json").read_text())["state"],
                         "rolled_back")

    def test_stage_change_after_preflight_is_rejected(self):
        stage,plan=stage_snapshot(self.archive,self.target)
        (stage/"payload"/"feature.py").write_bytes(b"replaced after download")
        with self.assertRaises(UpdateError):
            install_snapshot(stage,self.target)
        self.assertFalse((self.target/".orbitclip_patch_backups").exists())

    def test_rejects_unsafe_full_archive_paths(self):
        for path in ("../unsafe.py","client_defaults.json","tools/external.py"):
            data=manifest("7.9.3",self.new)
            data["files"][path]={"sha256":"0"*64,"size":3}
            with self.subTest(path=path):
                with self.assertRaises(UpdateError):
                    validate_snapshot_manifest(data)


if __name__=="__main__":
    unittest.main()
