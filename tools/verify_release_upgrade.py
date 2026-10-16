#!/usr/bin/env python3
"""End-to-end test of an actual ZIP patch against a clean copy of the prior tag.

Runs on Linux, Windows and macOS, without launching the GUI/network or touching
any user installation. The previous version is reconstructed from git archive.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import shutil
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.release_builder import patchable_path

ROOT=Path(__file__).resolve().parent.parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(folder):
    return {str(p.relative_to(folder)): sha(p.read_bytes()) for p in folder.rglob('*')
            if p.is_file() and '.orbitclip_patch_backups' not in p.parts}


def prepare_previous(folder, ref):
    data=subprocess.check_output(['git','archive','--format=tar',ref],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for entry in archive:
            if not entry.isfile():
                continue
            relative=Path(entry.name)
            if not patchable_path(relative) and relative.as_posix() != 'client_defaults.json':
                continue
            dest=folder/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            contents=archive.extractfile(entry).read()
            if relative.name=='client_defaults.json':
                config=json.loads(contents)
                for key in ('https_token','remote_token','token'):
                    config[key]=''
                contents=json.dumps(config).encode('utf-8')
            dest.write_bytes(contents)


def command(installer,folder,*args,should_pass=True):
    result=subprocess.run([sys.executable,str(installer),'--target',str(folder),*args],
                          text=True,capture_output=True)
    if (result.returncode==0)!=should_pass:
        raise AssertionError(
            f'Installer returned {result.returncode}; stdout={result.stdout}; '
            f'stderr={result.stderr}')
    return result


def main(zip_path):
    zip_path=Path(zip_path).resolve()
    with tempfile.TemporaryDirectory(prefix='orbitclip-upgrade-test-') as tmp:
        folder=Path(tmp)
        with ZipFile(zip_path) as z:
            manifests=[x for x in z.namelist() if x.endswith('/manifest.json')]
            if len(manifests)!=1:
                raise AssertionError('Expected one patch manifest')
            manifest=json.loads(z.read(manifests[0]))
            prefix=Path(manifests[0]).parent
            # Never trust paths from third-party archives; this smoke test only
            # extracts artifacts built by our own release script.
            z.extractall(folder/'unpacked')
        patch_dir=folder/'unpacked'/prefix
        installer=patch_dir/'apply_patch.py'
        app=folder/'ORBITclip'
        app.mkdir()
        prepare_previous(app,'v'+manifest['from_version'])
        # README was the cause of the 7.6.0 failure: both absent and modified
        # documentation should always be irrelevant to runtime upgrade.
        notes=app/'README.md'
        notes.write_text('My local documentation edits\n',encoding='utf-8')
        local=app/'user_notes.txt'
        local.write_text('DO NOT TOUCH\n',encoding='utf-8')
        (app/'.venv').mkdir()
        (app/'.venv'/'marker.txt').write_text('PRESERVE\n',encoding='utf-8')
        original=snapshot(app)
        command(installer,app,'--dry-run')
        assert snapshot(app)==original, '--dry-run unexpectedly changed files'
        # Reject a source hash mismatch before any modification.
        candidate=next((x for x in manifest['changes'] if x['before'] is not None),None)
        if not candidate:
            raise AssertionError('No source file to check')
        target=app/candidate['path']
        original_bytes=target.read_bytes()
        target.write_bytes(original_bytes+b'\n# deliberate local change\n')
        command(installer,app,'--dry-run',should_pass=False)
        assert (app/'orbit_version.py').read_text('utf-8').count('CLIENT_VERSION')==1
        assert not (app/'.orbitclip_patch_backups').exists(), 'Invalid patch created backup'
        target.write_bytes(original_bytes)
        assert snapshot(app)==original

        # Inject failure AFTER os.replace actually changed a file, and make
        # certain the transaction rolls that file back. This guards a real
        # bug caused by tracking modified paths only after os.replace.
        spec=importlib.util.spec_from_file_location('isolated_patch_installer',installer)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        replace=module.os.replace
        crashed=[False]
        def fail_after_replace(src,dst):
            replace(src,dst)
            if not crashed[0]:
                crashed[0]=True
                raise RuntimeError('Simulated interruption after successful rename')
        module.os.replace=fail_after_replace
        try:
            try:
                module.install(app)
            except RuntimeError as exc:
                if 'Simulated interruption' not in str(exc):
                    raise
            else:
                raise AssertionError('Fault injection did not interrupt update')
        finally:
            module.os.replace=replace
        assert crashed[0]
        assert snapshot(app)==original, 'Interrupted installation was NOT rolled back'
        backup=app/'.orbitclip_patch_backups'/(
            'v'+manifest['from_version']+'_to_v'+manifest['to_version'])
        assert backup.is_dir()
        shutil.rmtree(backup)
        command(installer,app)
        for item in manifest['changes']:
            dest=app/item['path']
            if item['after'] is None:
                assert not dest.exists(), item['path']
            else:
                assert sha(dest.read_bytes())==item['after'], item['path']
            if item['before'] is not None:
                assert sha((backup/item['path']).read_bytes())==item['before'] if (
                    backup/item['path']).exists() else True
        assert (app/'orbit_version.py').read_text('utf-8').find(
            "CLIENT_VERSION='"+manifest['to_version']+"'")!=-1
        assert notes.read_text('utf-8')=='My local documentation edits\n'
        assert local.read_text('utf-8')=='DO NOT TOUCH\n'
        assert (app/'.venv'/'marker.txt').read_text('utf-8')=='PRESERVE\n'
        command(installer,app,should_pass=False)
        print('PASS: clean install',manifest['from_version'],'to',manifest['to_version'])
        print('PASS: dry-run, hash guard, interrupted-write rollback, user files, repeat guard')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('patch',type=Path)
    args=parser.parse_args()
    main(args.patch)
