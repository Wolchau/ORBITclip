"""Offline, three-release updater regression; no internet or user state."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from orbit_update import read_version, UpdateError
from orbit_update_chain import (
    shortest_path, prepare_chain_from_archives, install_chain,
    inspect_zip_manifest, _plan_stages
)
from orbit_version import CLIENT_VERSION


def hash_bytes(b):
    return hashlib.sha256(b).hexdigest()


def patch_zip(directory, from_version, to_version, old_code, new_code, *,
              broken=False):
    path=directory/('patch-'+to_version+'.zip')
    previous=("APP_NAME='ORBITclip'\nCLIENT_VERSION='"+from_version+"'\n").encode()
    following=("APP_NAME='ORBITclip'\nCLIENT_VERSION='"+to_version+"'\n").encode()
    changes=[
        {'path':'orbit_version.py','before':hash_bytes(previous),
         'after':hash_bytes(following)},
        {'path':'app.py','before':hash_bytes(old_code),
         'after':hash_bytes(new_code) if not broken else 'b'*64},
    ]
    prefix='ORBITclip_Patch_v'+to_version.replace('.','_')+'/'
    with ZipFile(path,'w') as z:
        z.writestr(prefix+'manifest.json',json.dumps({
            'app':'ORBITclip','from_version':from_version,
            'to_version':to_version,'changes':changes}))
        z.writestr(prefix+'payload/orbit_version.py',following)
        z.writestr(prefix+'payload/app.py',new_code)
        z.writestr(prefix+'apply_patch.py',
                   'raise Exception("This script must never execute")')
    return path


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.app=self.root/'app'
        self.app.mkdir()
        (self.app/'orbit_version.py').write_text("APP_NAME='ORBITclip'\nCLIENT_VERSION='7.8.1'\n")
        (self.app/'app.py').write_bytes(b'original')
        (self.app/'README.md').write_text('mine')
        (self.app/'client_defaults.json').write_text('custom preferences')
        (self.app/'.venv').mkdir()
        (self.app/'.venv'/'sentinel').write_text('keep')
        versions=['7.8.1','7.8.2','7.8.4','7.9.3']
        payloads=[b'original',b'feature a',b'feature b',b'feature c']
        self.patches=[patch_zip(self.root,a,b,old,new)
                      for a,b,old,new in zip(versions,versions[1:],
                                             payloads,payloads[1:])]

    def prepare(self,patches=None,destination='7.9.3'):
        archives=[(inspect_zip_manifest(p)['to_version'],p)
                  for p in (patches or self.patches)]
        return prepare_chain_from_archives('7.8.1',self.app,archives,destination)

    def test_three_skipped_versions_in_one_transaction(self):
        self.assertEqual(CLIENT_VERSION,'7.8.1')
        plan,manifests=self.prepare()
        info,stages,chain=_plan_stages(plan)
        self.assertEqual(len(stages),3)
        self.assertEqual(info['to_version'],'7.9.3')
        self.assertEqual(read_version(self.app),'7.8.1') # dry-run did not touch target
        self.assertEqual(install_chain(plan,self.app),'7.9.3')
        self.assertEqual((self.app/'app.py').read_bytes(),b'feature c')
        self.assertEqual((self.app/'README.md').read_text(),'mine')
        self.assertEqual((self.app/'client_defaults.json').read_text(),'custom preferences')
        self.assertEqual((self.app/'.venv'/'sentinel').read_text(),'keep')
        backup=self.app/'.orbitclip_patch_backups'/'chains'/'v7.8.1_to_v7.9.3'
        self.assertEqual((backup/'files'/'app.py').read_bytes(),b'original')
        self.assertFalse((plan/'step-000'/'apply_patch.py').exists())

    def test_middle_patch_missing_prevents_any_writes(self):
        with self.assertRaisesRegex(UpdateError,'нет полной цепочки'):
            self.prepare(patches=[self.patches[0],self.patches[2]])
        self.assertEqual(read_version(self.app),'7.8.1')
        self.assertFalse((self.app/'.orbitclip_patch_backups').exists())

    def test_corrupt_last_patch_detected_before_first_write(self):
        # Patch declares a wrong final checksum; stage preflight fails.
        broken=patch_zip(self.root,'7.8.4','7.9.3',b'feature b',b'feature c',broken=True)
        with self.assertRaises((UpdateError,ValueError)):
            self.prepare(patches=self.patches[:2]+[broken])
        self.assertEqual(read_version(self.app),'7.8.1')
        self.assertEqual((self.app/'app.py').read_bytes(),b'original')

    def test_failure_after_second_step_restores_all_original_files(self):
        plan,manifests=self.prepare()
        import orbit_update_chain
        original=orbit_update_chain.install_staged
        calls=[0]
        def interrupt(stage,target):
            if Path(target).resolve()==self.app.resolve():
                calls[0]+=1
                if calls[0]==3:
                    # Assert this is a REAL failure during the third step;
                    # the first two patches are already written to actual files.
                    self.assertEqual(read_version(self.app),'7.8.4')
                    raise OSError('deliberate simulated failure after two successful steps')
            return original(stage,target)
        with patch.object(orbit_update_chain,'install_staged',side_effect=interrupt):
            with self.assertRaises(OSError):
                install_chain(plan,self.app)
        self.assertEqual(calls[0],3)
        self.assertEqual(read_version(self.app),'7.8.1')
        self.assertEqual((self.app/'app.py').read_bytes(),b'original')
        self.assertFalse((self.app/'.orbitclip_patch_backups'/'v7.8.1_to_v7.8.2').exists())
        self.assertEqual((self.app/'README.md').read_text(),'mine')
        failed=list((self.app/'.orbitclip_patch_backups'/'failed').glob('v7.8.1_to_v7.9.3-*'))
        self.assertEqual(len(failed),1)
        self.assertEqual((failed[0]/'files'/'app.py').read_bytes(),b'original')
        # A successful rollback must not permanently block a user retry.
        self.assertEqual(install_chain(plan,self.app),'7.9.3')
        self.assertEqual(read_version(self.app),'7.9.3')

    def test_download_orchestration_and_cleanup_with_skipped_versions(self):
        import orbit_update_chain
        releases=[
            {'version':v,'url':'https://api.github.com/repos/Wolchau/ORBITclip/releases/assets/'+str(n),
             'size':archive.stat().st_size,'digest':''}
            for n,(v,archive) in enumerate(zip(['7.8.2','7.8.4','7.9.3'],self.patches),1)
        ]
        temp_folders=[]
        def mocked_download(item,token=None,progress=None):
            directory=Path(tempfile.mkdtemp(prefix='download-test-'))
            temp_folders.append(directory)
            destination=directory/'update.zip'
            shutil.copy2(self.patches[['7.8.2','7.8.4','7.9.3'].index(item['version'])],destination)
            if progress:progress(destination.stat().st_size,destination.stat().st_size)
            return destination
        with patch.object(orbit_update_chain,'download_release',side_effect=mocked_download):
            plan,manifests=orbit_update_chain.download_and_prepare(releases,self.app)
        self.assertEqual([x['to_version'] for x in manifests],['7.8.2','7.8.4','7.9.3'])
        self.assertEqual(read_version(self.app),'7.8.1')
        self.assertTrue(all(not folder.exists() for folder in temp_folders))
        self.assertEqual(install_chain(plan,self.app),'7.9.3')

    def test_route_uses_manifest_dependencies_not_sorted_versions(self):
        manifests=[({'from_version':'7.8.1','to_version':'7.8.2'},'a'),
                   ({'from_version':'7.8.1','to_version':'7.8.4'},'shortcut'),
                   ({'from_version':'7.8.4','to_version':'7.9.3'},'end')]
        plan=shortest_path('7.8.1','7.9.3',manifests)
        self.assertEqual([x[2] for x in plan],['shortcut','end'])


if __name__=='__main__':
    unittest.main()
