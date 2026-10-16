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
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    out=dist/f'ORBITclip_Client_v{version.replace(".","_")}.zip'
    allowed={'.py','.json','.txt','.md','.command','.bat','.svg','.png','.ico','.icns','.gif'}
    with ZipFile(out,'w',compression=ZIP_DEFLATED,compresslevel=8) as z:
        for p in sorted(ROOT.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in allowed:continue
            rel=p.relative_to(ROOT)
            if rel.parts[0] in ('.git','.github','tools','docs','patches','dist'):continue
            if any(part in ('__pycache__','.venv') for part in rel.parts):continue
            add_zip_member(z,p,arcname=str(Path('ORBITclip')/rel))
    print(out.name,out.stat().st_size)
    patch=ROOT/'patches'/('v'+version)
    if patch.is_dir():
        dest=dist/f'ORBITclip_Patch_v{version.replace(".","_")}.zip'
        with ZipFile(dest,'w',compression=ZIP_DEFLATED,compresslevel=8) as z:
            for p in files_in(patch):
                add_zip_member(z,p,arcname=str(Path('ORBITclip_Patch_v'+version.replace('.','_'))/p.relative_to(patch)))
        print(dest.name,dest.stat().st_size)


def incremental_patch(version):
    """Build only changed client modules since the preceding version."""
    import subprocess
    oldtag='v7.4.2'
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
        if rel.parts[0] in ('.github','tools','docs','patches','dist') or rel.suffix.lower() not in allowed: continue
        before=hashlib.sha256(git('show',oldtag+':'+rel.as_posix())).hexdigest() if status!='A' else None
        body=(ROOT/rel).read_bytes() if status!='D' else None
        after=hashlib.sha256(body).hexdigest() if body is not None else None
        records.append({'path':rel.as_posix(),'before':before,'after':after})
        if body is not None: contents[rel.as_posix()]=body
    prefix='ORBITclip_Patch_v'+version.replace('.','_')+'/'
    output=ROOT/'dist'/(prefix.rstrip('/')+'.zip')
    manifest={'app':'ORBITclip','from_version':'7.4.2','to_version':version,'changes':records}
    with ZipFile(output,'w',compression=ZIP_DEFLATED,compresslevel=9) as z:
        z.writestr(prefix+'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        z.write(ROOT/'tools'/'patch_installer.py',prefix+'apply_patch.py')
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
        incremental_patch(v)
