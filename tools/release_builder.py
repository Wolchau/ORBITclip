#!/usr/bin/env python3
"""Build sanitized client and versioned installable patch for GitHub Releases."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo
import argparse, ast, json, re, sys, shutil, hashlib

ROOT=Path(__file__).resolve().parent.parent
def version():
    tree=ast.parse((ROOT/'orbit_version.py').read_text(encoding='utf-8'))
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='CLIENT_VERSION' for t in n.targets))

def files_in(folder):
    return sorted(p for p in folder.rglob('*') if p.is_file() and
                  not any(s in p.parts for s in ('__pycache__','.git','.venv','dist','.orbitclip_patch_backups')))

def check_security():
    cfg=json.loads((ROOT/'client_defaults.json').read_text(encoding='utf-8'))
    # Test-only exception explicitly requested by repository owner.
    # Never deploy a public release using this default token; rotate and remove it first.
    if cfg.get('https_token'):
        print('WARNING: test relay token will be embedded in published archive')
    # Scan only tracked project and installer payload, never inspect local user state.
    for p in files_in(ROOT):
        if p.suffix not in ('.py','.json','.md','.txt','.bat','.command','.yml','.yaml','.svg'):
            continue
        if 'patches' in p.parts and p.name=='patch_manifest.json':
            continue
        if p.stat().st_size>2_000_000:continue
        s=p.read_text(encoding='utf-8',errors='replace')
        if re.search(r'(?i)(?:ghp_|github_pat_|sk-proj-)[a-z0-9_\-]{15,}',s):
            raise SystemExit('Suspected credential in '+str(p))
    return True

def add_zip_member(zf, path, arcname):
    """Keep macOS .command files executable even after a web upload.

    GitHub's upload interface may store these files as 100644. Setting the
    POSIX executable bit explicitly in the ZIP avoids a permission error
    when users double-click a downloaded command script on macOS.
    """
    info=ZipInfo.from_file(path, arcname=arcname)
    info.create_system=3  # Unix permission semantics for Archive Utility.
    info.compress_type=ZIP_DEFLATED
    if path.suffix.lower()=='.command':
        info.external_attr=(0o100755 << 16)
    with path.open('rb') as source, zf.open(info,'w') as target:
        shutil.copyfileobj(source,target)


def bundle(version):
    """Minimal clean first-install distribution: only app modules and runtime assets."""
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    out=dist/f'ORBITclip_CleanInstall_v{version.replace(".","_")}.zip'
    root_files=sorted(p for p in ROOT.glob('*.py') if not p.name.startswith('test_')
                      and p.name!='orbit_capture.py')
    root_files += [ROOT/n for n in ('requirements-client.txt','start_windows.bat',
                                     'start_mac.command','client_defaults.json')]
    root_files=[p for p in root_files if p.is_file()]
    with ZipFile(out,'w',compression=ZIP_DEFLATED,compresslevel=9) as z:
        for p in root_files:
            arcname=str(Path('ORBITclip')/p.name)
            if p.name=='client_defaults.json':
                cfg=json.loads(p.read_text(encoding='utf-8'))
                # An initial-install archive must never ship embedded relay credentials.
                for key in ('https_token','remote_token','token'):
                    if key in cfg:cfg[key]=''
                z.writestr(arcname,json.dumps(cfg,ensure_ascii=False,indent=2))
            else:add_zip_member(z,p,arcname)
        for folder in ('assets',):
            asset_dir=ROOT/folder
            if not asset_dir.is_dir():continue
            for p in files_in(asset_dir):
                if p.suffix.lower() not in ('.png','.svg','.ico','.icns','.gif','.jpg','.jpeg','.webp'):
                    continue
                add_zip_member(z,p,str(Path('ORBITclip')/p.relative_to(ROOT)))
    print(out.name,out.stat().st_size,'bytes,',len(root_files),'root files')

def incremental_patch(version):
    """Build only changed client modules since the preceding version."""
    import subprocess
    oldtag='v7.5.1'
    def git(*args):
        return subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True).stdout
    try:
        changes=git('diff','--name-status',oldtag,'HEAD').decode().splitlines()
    except (OSError,subprocess.CalledProcessError):
        print('Previous tag unavailable; incremental patch skipped')
        return
    allowed={'.py','.json','.txt','.md','.command','.bat','.svg','.png','.ico','.icns','.gif'}
    records=[]; contents={}
    for line in changes:
        columns=line.split(chr(9))
        status=columns[0][0]
        if status not in ('A','M','D') or len(columns)!=2: continue
        rel=Path(columns[1])
        if rel.name.startswith('test_') or rel.parts[0] in ('.github','tools','docs','patches','dist') or rel.suffix.lower() not in allowed: continue
        before=hashlib.sha256(git('show',oldtag+':'+rel.as_posix())).hexdigest() if status!='A' else None
        body=(ROOT/rel).read_bytes() if status!='D' else None
        after=hashlib.sha256(body).hexdigest() if body is not None else None
        records.append({'path':rel.as_posix(),'before':before,'after':after})
        if body is not None: contents[rel.as_posix()]=body
    prefix='ORBITclip_Patch_v'+version.replace('.','_')+'/'
    (ROOT/'dist').mkdir(exist_ok=True)
    output=ROOT/'dist'/(prefix.rstrip('/')+'.zip')
    manifest={'app':'ORBITclip','from_version':'7.5.1','to_version':version,'changes':records}
    with ZipFile(output,'w',compression=ZIP_DEFLATED,compresslevel=9) as z:
        z.writestr(prefix+'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        z.write(ROOT/'tools'/'patch_installer.py',prefix+'apply_patch.py')
        z.writestr(prefix+'apply_windows.bat',
            '@echo off\r\ncd /d "%~dp0"\r\nwhere py >nul 2>nul && (py -3 apply_patch.py & goto END)\r\npython apply_patch.py\r\n:END\r\npause\r\n')
        command=ZipInfo(prefix+'apply_mac.command')
        command.create_system=3
        command.external_attr=(0o100755 << 16)
        command.compress_type=ZIP_DEFLATED
        z.writestr(command,'#!/bin/bash\ncd "$(dirname "$0")" || exit 1\npython3 apply_patch.py\nread -r -p "Press Enter to close..." _\n')
        for path,body in contents.items(): z.writestr(prefix+'payload/'+path,body)
    print(output.name,output.stat().st_size,'bytes,',len(records),'files')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    check_security()
    v=version()
    print('Checked version',v,'test credential policy')
    if not args.check_only:
        bundle(v)
        if v=='7.6.0':
            incremental_patch(v)
