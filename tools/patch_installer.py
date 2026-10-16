#!/usr/bin/env python3
"""Install a version-specific ORBITclip patch; never touches user data or runtime."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import sys

# When Windows launches Python with redirected output, stdout can default to
# cp1252; printing Russian diagnostics would then crash the installer.
if os.name=='nt':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='backslashreplace')

HERE=Path(__file__).resolve().parent

def digest(data):
    return hashlib.sha256(data).hexdigest()

def version(folder):
    try:
        tree=ast.parse((folder/'orbit_version.py').read_text('utf-8'))
        for stmt in tree.body:
            if isinstance(stmt,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CLIENT_VERSION' for t in stmt.targets):
                return ast.literal_eval(stmt.value)
    except (OSError,ValueError,SyntaxError):
        pass
    return None

def preflight(folder):
    """Validate every path and hash before touching the installation."""
    folder=Path(folder).resolve()
    data=json.loads((HERE/'manifest.json').read_text('utf-8'))
    if data.get('app')!='ORBITclip' or version(folder)!=data.get('from_version'):
        raise RuntimeError('Версия ORBITclip не соответствует патчу: '+str(version(folder)))
    changes=data.get('changes')
    if not isinstance(changes,list) or not changes:
        raise RuntimeError('Пустой или повреждённый манифест обновления')
    seen=set()
    for item in changes:
        if not isinstance(item,dict) or not isinstance(item.get('path'),str):
            raise RuntimeError('Некорректная запись манифеста')
        rel=Path(item['path'])
        if (rel.is_absolute() or '..' in rel.parts or not rel.parts
                or rel.parts[0].startswith('.') or rel.as_posix() in seen):
            raise RuntimeError('Недопустимый путь обновления: '+str(rel))
        seen.add(rel.as_posix())
        if item.get('before') is None and item.get('after') is None:
            raise RuntimeError('Пустое изменение: '+str(rel))
        destination=folder/rel
        # Checking the leaf alone misses a symlink in parent directories.
        for ancestor in (destination,*destination.parents):
            if ancestor == folder.parent:
                break
            if ancestor.is_symlink():
                raise RuntimeError('Символьная ссылка в пути обновления: '+str(rel))
        if item['before'] is not None:
            if not destination.is_file() or digest(destination.read_bytes())!=item['before']:
                raise RuntimeError('Файл изменён, обновление остановлено: '+str(rel))
        elif destination.exists():
            raise RuntimeError('Новый путь уже существует: '+str(rel))
        if item['after'] is not None:
            payload=HERE/'payload'/rel
            if not payload.is_file() or digest(payload.read_bytes())!=item['after']:
                raise RuntimeError('Повреждён патч: '+str(rel))
    backup=folder/'.orbitclip_patch_backups'/('v'+data['from_version']+'_to_v'+data['to_version'])
    if backup.exists() or backup.is_symlink():
        raise RuntimeError('Резервная копия предыдущей попытки уже существует: '+str(backup))
    return folder,data,backup


def install(folder,dry_run=False):
    folder,data,backup=preflight(folder)
    if dry_run:
        print('Проверка пройдена; файлы не изменены:',len(data['changes']))
        return
    changes=data['changes']
    backup.mkdir(parents=True)
    applied=[]
    try:
        # Finish ALL backups before the first write.
        for item in changes:
            rel=Path(item['path'])
            destination=folder/rel
            if destination.exists():
                saved=backup/rel
                saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(destination,saved)
        for item in changes:
            rel=Path(item['path'])
            destination=folder/rel
            # Mark BEFORE mutation: even a failure after os.replace succeeded
            # must trigger rollback of that file.
            applied.append(rel)
            if item['after'] is None:
                destination.unlink()
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                fd,tmp=tempfile.mkstemp(prefix='.orbit_tmp_',dir=destination.parent)
                try:
                    with os.fdopen(fd,'wb') as stream:
                        stream.write((HERE/'payload'/rel).read_bytes())
                    os.replace(tmp,destination)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            if item['after'] is not None and digest(destination.read_bytes())!=item['after']:
                raise RuntimeError('Контрольная сумма после записи не совпала: '+str(rel))
        if version(folder)!=data['to_version']:
            raise RuntimeError('Версия после установки не совпала')
    except BaseException:
        for rel in reversed(applied):
            destination=folder/rel
            saved=backup/rel
            if saved.is_file():
                shutil.copy2(saved,destination)
            elif destination.is_file():
                destination.unlink()
        raise
    print('Обновлено до ORBITclip',data['to_version'])
    print('Резервные копии:',backup)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',help='Папка ORBITclip; по умолчанию — рядом с патчем')
    parser.add_argument('--dry-run',action='store_true',help='Проверить патч и файлы без установки')
    args=parser.parse_args()
    candidates=[
        HERE.parent/'ORBITclip', HERE.parent,
        HERE.parent.parent/'ORBITclip', HERE.parent.parent,
    ]
    expected=json.loads((HERE/'manifest.json').read_text('utf-8'))['from_version']
    target=Path(args.target).expanduser() if args.target else next(
        (p for p in candidates if version(p)==expected),None)
    if target is None:
        try:
            entered=input('Введите полный путь к папке ORBITclip: ').strip().strip('"')
        except EOFError:
            entered=''
        if not entered:
            raise SystemExit('Укажи путь: python apply_patch.py --target ПУТЬ')
        target=Path(entered).expanduser()
    install(target,dry_run=args.dry_run)
