#!/usr/bin/env python3
"""Verify a release ZIP is a complete, self-described ORBITclip baseline."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from tools.release_builder import patchable_path
from orbit_update_full import validate_snapshot_manifest


def check(archive):
    archive=Path(archive)
    with ZipFile(archive) as z:
        all_names=[x.filename for x in z.infolist() if not x.is_dir()]
        assert len(all_names)==len(set(all_names)), "Duplicate ZIP path"
        packed=json.loads(z.read("ORBITclip/update-manifest.json"))
        validate_snapshot_manifest(packed)
        expected={"ORBITclip/"+name for name in packed["files"]}
        expected.update({"ORBITclip/update-manifest.json","ORBITclip/client_defaults.json"})
        assert set(all_names)==expected, "Missing or unexpected files"
        for name,spec in packed["files"].items():
            data=z.read("ORBITclip/"+name)
            assert patchable_path(Path(name)), name
            assert len(data)==spec["size"], name
            assert hashlib.sha256(data).hexdigest()==spec["sha256"], name
        source=z.read("ORBITclip/orbit_version.py").decode("utf-8")
        assert "CLIENT_VERSION='"+packed["version"]+"'" in source
        defaults=json.loads(z.read("ORBITclip/client_defaults.json"))
        assert not any(defaults.get(k) for k in ("https_token","remote_token","token"))
        print("PASS: complete managed runtime and SHA-256:",packed["version"],
              len(packed["files"]),"files")
        print("PASS: defaults sanitized; no unmanaged files in full ZIP")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("archive")
    check(parser.parse_args().archive)
